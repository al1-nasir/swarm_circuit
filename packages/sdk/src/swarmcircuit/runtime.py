"""Opt-in cooperative boundaries. This module never interrupts an in-flight action."""

import secrets
import time
from collections.abc import Callable
from threading import Event, RLock, Thread
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4, uuid5

import httpx

if TYPE_CHECKING:
    from swarmcircuit.run import RunContext, TaskContext


class ControlError(RuntimeError):
    """Fail-closed control outcome; callers must not continue past the boundary."""

    def __init__(self, code: str, status: int | None = None) -> None:
        self.code, self.status = code, status
        super().__init__(f"Cooperative boundary blocked: {code}")


class RuntimeController:
    def __init__(
        self,
        run: "RunContext",
        runtime_key: str,
        *,
        capabilities: tuple[str, ...] = ("hold_task", "resume_task"),
        poll_interval: float = 0.05,
        heartbeat_interval: float = 1,
    ) -> None:
        if run.mode != "control":
            raise ControlError("observe_only")
        if poll_interval <= 0 or heartbeat_interval <= 0:
            raise ValueError("Runtime polling intervals must be positive")
        self.run, self.sdk = run, run.sdk
        self.runtime_key = runtime_key
        self.capabilities = capabilities
        self.poll_interval, self.heartbeat_interval = poll_interval, heartbeat_interval
        self.client_nonce = secrets.token_urlsafe(32)
        self.session_id = ""
        self.token = ""
        self.epoch = 0
        self.stopping, self.degraded = Event(), Event()
        self.thread: Thread | None = None
        self.lock = RLock()
        self.inbox: dict[str, dict[str, Any]] = {}
        self.applied: dict[str, dict[str, Any]] = {}
        self.presentation_results: dict[str, str] = {}

    def __enter__(self) -> "RuntimeController":
        response = self.sdk._request(
            "POST",
            f"/api/v1/runs/{self.run.run_id}/runtime-sessions",
            json={
                "runtime_key": self.runtime_key,
                "client_nonce": self.client_nonce,
                "capabilities": list(self.capabilities),
            },
        )
        if response.status_code != 201:
            raise ControlError("registration_rejected", response.status_code)
        session = response.json()
        self.session_id, self.token = session["runtime_session_id"], session["session_token"]
        self.epoch = session["fencing_epoch"]
        self.thread = Thread(target=self._heartbeats, name="swarm-runtime-heartbeat", daemon=True)
        self.thread.start()
        return self

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        for attempt in range(self.sdk.attempts):
            try:
                response = self.sdk.client.request(
                    method,
                    self.sdk.endpoint + path,
                    headers={"Authorization": f"Bearer {self.token}"},
                    **kwargs,
                )
                if response.status_code < 300:
                    return response.json()
                if response.status_code not in {429, 502, 503, 504}:
                    raise ControlError(
                        response.json().get("code", "request_rejected"), response.status_code
                    )
            except httpx.TransportError:
                pass
            if attempt + 1 < self.sdk.attempts:
                self.sdk.sleep(min(1, 0.05 * 2**attempt))
        raise ControlError("transport_outcome_unknown")

    def _heartbeats(self) -> None:
        while not self.stopping.wait(self.heartbeat_interval):
            try:
                result = self._request(
                    "POST", f"/api/v1/runtime-sessions/{self.session_id}/heartbeat"
                )
                if result["fencing_epoch"] != self.epoch:
                    raise ControlError("stale_session")
            except Exception:
                self.degraded.set()
                return

    def _ack(self, cmd: dict[str, Any], result: str) -> dict[str, Any]:
        payload = {
            "runtime_session_id": self.session_id,
            "fencing_epoch": self.epoch,
            "ack_key": str(uuid5(UUID(self.session_id), cmd["command_id"])),
            "result": result,
        }
        try:
            return self._request(
                "POST", f"/api/v1/control-commands/{cmd['command_id']}/ack", json=payload
            )
        except ControlError as exc:
            if exc.status is not None:
                raise
            # Lost ACK response: inspect canonical state, never repeat the local effect.
            response = self.sdk._request("GET", f"/api/v1/control-commands/{cmd['command_id']}")
            if response.status_code == 200:
                item = response.json()
                if (
                    item["state"] == "applied"
                    and item["runtime_session_id"] == self.session_id
                    and item["session_fencing_epoch"] == self.epoch
                ):
                    return item
            raise ControlError("ack_outcome_unknown") from exc

    def checkpoint(
        self,
        task: "TaskContext",
        *,
        action: str,
        reversible: bool = True,
        timeout: float = 60,
        on_enter: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        if (
            not reversible
            or task.run is not self.run
            or not self.session_id
            or self.degraded.is_set()
            or self.stopping.is_set()
        ):
            raise ControlError("unsupported_boundary")
        point = self._request(
            "POST",
            f"/api/v1/runtime-sessions/{self.session_id}/checkpoints",
            json={
                "task_id": task.task_id,
                "checkpoint_key": str(uuid4()),
                "label": action,
                "reversible": True,
            },
        )
        if on_enter:
            on_enter(point)
        deadline = time.monotonic() + timeout
        held = False
        while time.monotonic() < deadline:
            if self.degraded.is_set() or self.stopping.is_set():
                raise ControlError("runtime_disconnected")
            with self.lock:
                batch = self._request(
                    "GET",
                    f"/api/v1/runtime-sessions/{self.session_id}/commands",
                    params={"wait_ms": 0},
                )
                for item in batch["commands"]:
                    self.inbox[item["command_id"]] = item
                own = [item for item in self.inbox.values() if item["task_id"] == task.task_id]
                for cmd in own:
                    if cmd["checkpoint_id"] != point["checkpoint_id"]:
                        raise ControlError("checkpoint_mismatch")
                    if cmd["command_id"] not in self.applied:
                        # The caller is already physically inside this blocking function.
                        held = cmd["command_kind"] == "hold_task"
                        result = self._ack(cmd, "applied")
                        if result["state"] != "applied":
                            raise ControlError("command_effect_unconfirmed")
                        self.applied[cmd["command_id"]] = result
                    self.inbox.pop(cmd["command_id"], None)
            if not held:
                try:
                    self._request(
                        "POST",
                        f"/api/v1/runtime-sessions/{self.session_id}/checkpoints/{point['checkpoint_id']}/leave",
                    )
                    return
                except ControlError as exc:
                    if exc.code not in {
                        "pending_control",
                        "unresolved_dependency",
                        "approval_unresolved",
                    }:
                        raise
            self.stopping.wait(self.poll_interval)
        raise ControlError("checkpoint_timeout")

    def present_approval_once(
        self, task: "TaskContext", scope: dict[str, str], presenter: Callable[[str], None]
    ) -> str:
        """Coalesce a host notification callback; never approve the pending request."""
        with self.lock:
            if (
                task.run is not self.run
                or not self.session_id
                or self.degraded.is_set()
                or self.stopping.is_set()
            ):
                raise ControlError("unsupported_boundary")
            approval_id = task.wait_for_approval(scope)
            if not self.sdk.flush():
                raise ControlError("approval_telemetry_unavailable")
            claim = self._request(
                "POST",
                f"/api/v1/runtime-sessions/{self.session_id}/approval-presentations",
                json={"event_id": task.last_approval_event_id},
            )
            pid = claim["presentation_id"]
            if claim["should_present"] and pid not in self.presentation_results:
                self.presentation_results[pid] = "unknown"
                try:
                    presenter(approval_id)
                except BaseException:
                    try:
                        self._request(
                            "POST",
                            f"/api/v1/runtime-sessions/{self.session_id}/approval-presentations/{pid}/result",
                            json={"state": "unknown"},
                        )
                    finally:
                        raise
                self.presentation_results[pid] = "presented"
                self._request(
                    "POST",
                    f"/api/v1/runtime-sessions/{self.session_id}/approval-presentations/{pid}/result",
                    json={"state": "presented"},
                )
            return approval_id

    def close(self) -> None:
        self.stopping.set()
        if self.thread:
            self.thread.join()

    def __exit__(self, *_: Any) -> None:
        self.close()
