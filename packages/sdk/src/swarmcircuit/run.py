"""Lifecycle contexts using public REST and an existing OpenTelemetry tracer."""

import hashlib
import json
import logging
import random
import time
from collections.abc import Callable
from threading import RLock
from types import TracebackType
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4, uuid5

import httpx
from opentelemetry import trace
from opentelemetry.trace import Tracer
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

if TYPE_CHECKING:
    from swarmcircuit.runtime import RuntimeController

log = logging.getLogger("swarmcircuit.sdk")


class SDKError(RuntimeError):
    """Permanent rejection of an SDK request."""


class SwarmCircuit:
    def __init__(
        self,
        project_id: str,
        token: str,
        endpoint: str = "http://127.0.0.1:8000",
        *,
        tracer: Tracer | None = None,
        client: Any = None,
        attempts: int = 3,
        pending_limit: int = 250,
        clock_ms: Callable[[], int] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.project_id = str(UUID(project_id))
        self.endpoint, self.token = endpoint.rstrip("/"), token
        self.tracer = tracer or trace.get_tracer("swarmcircuit", "0.5.0")
        self.client = client or httpx.Client(timeout=5)
        self.owns_client = client is None
        self.attempts, self.pending_limit = attempts, pending_limit
        if attempts < 1 or not 1 <= pending_limit <= 250:
            raise ValueError("Invalid retry or pending queue bound")
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self.sleep = sleep
        self.pending: list[tuple[str, dict[str, Any]]] = []
        self.telemetry_degraded = False
        self.dropped_events = 0
        self._lock = RLock()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        for attempt in range(self.attempts):
            try:
                response = self.client.request(
                    method,
                    self.endpoint + path,
                    headers={"Authorization": f"Bearer {self.token}"},
                    **kwargs,
                )
                if response.status_code not in {429, 502, 503, 504}:
                    return response
            except httpx.TransportError:
                pass
            if attempt + 1 < self.attempts:
                self.sleep(min(2.0, 0.1 * 2**attempt) + random.uniform(0, 0.05))
        raise SDKError("Telemetry endpoint unavailable after bounded retries")

    def run(
        self,
        name: str,
        *,
        external_run_key: str | None = None,
        mode: str = "observe",
        simulation: bool = False,
    ) -> "RunContext":
        if mode not in {"observe", "control"}:
            raise ValueError("Mode must be observe or control")
        key = external_run_key or str(uuid4())
        response = self._request(
            "POST",
            f"/api/v1/projects/{self.project_id}/runs",
            json={
                "name": name,
                "mode": mode,
                "external_run_key": key,
                "simulation": simulation,
            },
        )
        if response.status_code == 409:
            # Reconcile a lost creation response by the same external identity.
            cursor = None
            while True:
                page = self._request(
                    "GET",
                    f"/api/v1/projects/{self.project_id}/runs",
                    params={"limit": 100, **({"cursor": cursor} if cursor else {})},
                )
                page.raise_for_status()
                for item in page.json()["items"]:
                    if item["external_run_key"] == key:
                        if (
                            item["name"] != name
                            or item["mode"] != mode
                            or item["metadata"].get("simulation", False) != simulation
                        ):
                            raise SDKError("Run identity conflicts with an existing run")
                        return RunContext(self, item["run_id"], name, mode, simulation)
                cursor = page.json().get("next_cursor")
                if not cursor:
                    break
        if response.status_code != 201:
            raise SDKError(f"Run creation rejected with HTTP {response.status_code}")
        return RunContext(self, response.json()["run_id"], name, mode, simulation)

    def emit(
        self,
        run_id: str,
        kind: str,
        *,
        agent_id: str | None = None,
        task_id: str | None = None,
        approval_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        with self._lock:
            return self._emit(
                run_id,
                kind,
                agent_id=agent_id,
                task_id=task_id,
                approval_id=approval_id,
                payload=payload,
            )

    def _emit(
        self,
        run_id: str,
        kind: str,
        *,
        agent_id: str | None = None,
        task_id: str | None = None,
        approval_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        eid = str(uuid4())
        event: dict[str, Any] = {
            "event_id": eid,
            "source_event_key": f"sdk:{eid}",
            "event_kind": kind,
            "occurred_at_ms": self.clock_ms(),
            "payload": payload or {},
        }
        for key, value in (
            ("agent_id", agent_id),
            ("task_id", task_id),
            ("approval_id", approval_id),
        ):
            if value:
                event[key] = value
        if len(self.pending) >= self.pending_limit:
            self.dropped_events += 1
            self.telemetry_degraded = True
            log.warning("telemetry_queue_full")
            return eid
        self.pending.append((run_id, event))
        self.flush()
        return eid

    def flush(self) -> bool:
        """Retry stable envelopes in order; a transport outage never completes/fails host work."""
        with self._lock:
            return self._flush()

    def _flush(self) -> bool:
        while self.pending:
            rid, event = self.pending[0]
            try:
                response = self._request(
                    "POST", f"/api/v1/runs/{rid}/events", json={"events": [event]}
                )
            except SDKError:
                self.telemetry_degraded = True
                log.warning("telemetry_degraded")
                return False
            if response.status_code != 200 or response.json()["rejected"]:
                self.telemetry_degraded = True
                log.warning("telemetry_record_rejected")
                # A permanent rejection must not pin later independent telemetry forever.
                self.pending.pop(0)
                self.dropped_events += 1
                continue
            self.pending.pop(0)
        self.telemetry_degraded = self.dropped_events > 0
        return not self.telemetry_degraded

    def close(self) -> None:
        self.flush()
        if self.owns_client:
            self.client.close()

    def __enter__(self) -> "SwarmCircuit":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


class RunContext:
    def __init__(
        self,
        sdk: SwarmCircuit,
        run_id: str,
        name: str,
        mode: str = "observe",
        simulation: bool = False,
    ) -> None:
        self.sdk, self.run_id, self.name = sdk, run_id, name
        self.mode = mode
        self.simulation = simulation
        self.agents: dict[str, str] = {}
        self.tasks: list[TaskContext] = []
        self._span_context: Any = None

    def attributes(self) -> dict[str, str]:
        return {
            "swarmcircuit.project_id": self.sdk.project_id,
            "swarmcircuit.run_id": self.run_id,
            "swarmcircuit.operation_kind": "workflow",
        }

    def __enter__(self) -> "RunContext":
        self._span_context = self.sdk.tracer.start_as_current_span(
            self.name, attributes=self.attributes()
        )
        self._span_context.__enter__()
        self.sdk.emit(self.run_id, "workflow.started")
        return self

    def __exit__(self, kind: Any, value: Any, tb: Any) -> None:
        if kind is None and self.tasks and all(task.completed for task in self.tasks):
            self.sdk.emit(self.run_id, "workflow.completed")
        self.sdk.flush()
        self._span_context.__exit__(kind, value, tb)

    def agent(self, name: str, *, role: str | None = None) -> str:
        with self.sdk._lock:
            return self._agent(name, role=role)

    def _agent(self, name: str, *, role: str | None = None) -> str:
        if name not in self.agents:
            aid = str(uuid5(UUID(self.sdk.project_id), f"agent:{name}"))
            self.sdk.emit(
                self.run_id,
                "agent.started",
                agent_id=aid,
                payload={
                    "external_agent_key": name,
                    "display_name": name,
                    "role": role or name,
                },
            )
            self.agents[name] = aid
        return self.agents[name]

    def task(self, name: str, *, agent: str, deadline_at_ms: int | None = None) -> "TaskContext":
        task = TaskContext(self, str(uuid4()), name, self.agent(agent))
        payload: dict[str, Any] = {"external_task_key": task.task_id, "title": name}
        if deadline_at_ms is not None:
            payload["deadline_at_ms"] = deadline_at_ms
        task.emit("task.created", payload=payload)
        with self.sdk._lock:
            self.tasks.append(task)
        return task

    def trace_headers(self) -> dict[str, str]:
        carrier: dict[str, str] = {}
        TraceContextTextMapPropagator().inject(carrier)
        return carrier

    def runtime(self, runtime_key: str, **kwargs: Any) -> "RuntimeController":
        from swarmcircuit.runtime import RuntimeController

        return RuntimeController(self, runtime_key, **kwargs)


class TaskContext:
    def __init__(self, run: RunContext, task_id: str, name: str, agent_id: str) -> None:
        self.run, self.task_id, self.name, self.agent_id = run, task_id, name, agent_id
        self.waiting = False
        self.completed = False
        self._span_context: Any = None

    def emit(
        self, kind: str, *, payload: dict[str, Any] | None = None, approval_id: str | None = None
    ) -> str:
        return self.run.sdk.emit(
            self.run.run_id,
            kind,
            agent_id=self.agent_id,
            task_id=self.task_id,
            payload=payload,
            approval_id=approval_id,
        )

    def __enter__(self) -> "TaskContext":
        self.emit("task.started")
        attrs = {
            **self.run.attributes(),
            "swarmcircuit.task_id": self.task_id,
            "swarmcircuit.agent_id": self.agent_id,
            "swarmcircuit.operation_kind": "agent",
        }
        self._span_context = self.run.sdk.tracer.start_as_current_span(self.name, attributes=attrs)
        self._span_context.__enter__()
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        from swarmcircuit.runtime import ControlError

        if isinstance(value, ControlError):
            self.waiting = True  # Unknown control is neither task success nor failure.
        elif kind:
            self.emit("task.failed")
        elif not self.waiting and not self.completed:
            self.mark_completed()
        self._span_context.__exit__(kind, value, tb)

    def mark_completed(self) -> None:
        """Record host-reported completion only, never proof of an external effect."""
        self.emit("task.completed")
        self.completed = True

    def record_progress(self) -> None:
        """Record a host progress signal; retries/trace spans do not count as progress."""
        self.emit("task.progress")

    def depends_on(self, prerequisite: "TaskContext") -> None:
        if prerequisite.run.run_id != self.run.run_id:
            raise ValueError("Dependencies must belong to the same run")
        self.emit("task.dependency_added", payload={"prerequisite_task_id": prerequisite.task_id})

    def handoff(self, to_agent: str) -> None:
        self.emit("agent.handoff", payload={"to_agent_id": self.run.agent(to_agent)})

    def retry_requested(self, attempt_no: int, logical_action: str) -> None:
        self.emit(
            "task.retry_requested", payload={"attempt_no": attempt_no, "retry_of": logical_action}
        )

    def wait_for_approval(self, scope: dict[str, str]) -> str:
        """Group only identical complete scopes; the host must supply the authority fields."""
        required = {
            "principal",
            "purpose",
            "resource",
            "counterparty",
            "permission_scope",
            "policy_revision",
        }
        if not required <= scope.keys() or any(not isinstance(v, str) for v in scope.values()):
            raise ValueError(
                "Supply full approval scope with string values, including amount/asset if paid"
            )
        canonical = json.dumps(scope, sort_keys=True, separators=(",", ":"))
        fingerprint = "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
        apid = str(uuid5(UUID(self.run.run_id), fingerprint))
        self.last_approval_event_id = self.emit(
            "approval.requested",
            approval_id=apid,
            payload={
                "canonical_approval_key": fingerprint,
                "action_fingerprint": fingerprint,
            },
        )
        self.emit("task.waiting_for_approval", approval_id=apid)
        self.waiting = True
        return apid
