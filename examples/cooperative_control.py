"""Real local hold/resume through cooperative checkpoints; mock reversible work only."""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Any
from uuid import uuid4

import httpx
from swarmcircuit import SwarmCircuit
from swarmcircuit.instrumentation import create_otlp_provider


def main() -> None:
    endpoint = os.getenv("SWARM_API_URL", "http://127.0.0.1:8000")
    token = os.environ["SWARM_SDK_PROJECT_TOKEN"]
    provider = create_otlp_provider(endpoint, token, service_name="swarm-control-demo")
    try:
        with httpx.Client(
            base_url=endpoint,
            headers={"Authorization": "Bearer " + os.environ["SWARM_OPERATOR_TOKEN"]},
            timeout=5,
        ) as operator:
            with SwarmCircuit(
                os.environ["SWARM_PROJECT_ID"],
                token,
                endpoint,
                tracer=provider.get_tracer("control-demo"),
            ) as sdk:
                with sdk.run("cooperative-hold-resume", mode="control", simulation=True) as run:
                    protected = run.task("Mock reversible read", agent="protected-reader")
                    independent = run.task("Independent branch", agent="independent-reader")
                    entered, allow_poll = Event(), Event()
                    executed: list[str] = []
                    with run.runtime("demo-host", poll_interval=0.02) as runtime:

                        def on_enter(point: dict[str, Any]) -> None:
                            entered.set()
                            if not allow_poll.wait(5):
                                raise RuntimeError(
                                    "Operator did not request the demonstration hold"
                                )

                        def worker() -> None:
                            with protected:
                                runtime.checkpoint(
                                    protected,
                                    action="before_mock_read",
                                    timeout=10,
                                    on_enter=on_enter,
                                )
                                executed.append("mock-read-completed")

                        def request(kind: str) -> dict[str, Any]:
                            graph = operator.get(f"/api/v1/runs/{run.run_id}/graph")
                            graph.raise_for_status()
                            task = next(
                                n for n in graph.json()["nodes"] if n["id"] == protected.task_id
                            )
                            response = operator.post(
                                f"/api/v1/runs/{run.run_id}/control-commands",
                                headers={"Idempotency-Key": str(uuid4())},
                                json={
                                    "command_kind": kind,
                                    "runtime_session_id": runtime.session_id,
                                    "task_id": protected.task_id,
                                    "expected_task_version": task["state_version"],
                                    "reason": "Local mock-work checkpoint demonstration",
                                },
                            )
                            response.raise_for_status()
                            return response.json()

                        def wait_applied(cid: str) -> dict[str, Any]:
                            until = time.monotonic() + 5
                            while time.monotonic() < until:
                                response = operator.get(f"/api/v1/control-commands/{cid}")
                                response.raise_for_status()
                                result = response.json()
                                if result["state"] == "applied":
                                    return result
                                if result["state"] not in {"queued", "dispatched"}:
                                    raise RuntimeError(
                                        "Control outcome is not applied: " + result["state"]
                                    )
                                time.sleep(0.02)
                            raise RuntimeError("Runtime acknowledgement did not arrive")

                        with ThreadPoolExecutor(max_workers=1) as pool:
                            future = pool.submit(worker)
                            try:
                                if not entered.wait(5):
                                    raise RuntimeError("Runtime did not reach its boundary")
                                hold = request("hold_task")
                                if executed:
                                    raise RuntimeError(
                                        "Mock work ran before the checkpoint was released"
                                    )
                                allow_poll.set()
                                held = wait_applied(hold["command_id"])
                                if executed or future.done():
                                    raise RuntimeError("Protected branch did not remain parked")
                                with independent:
                                    pass
                                resume = request("resume_task")
                                resumed = wait_applied(resume["command_id"])
                                future.result(timeout=5)
                            finally:
                                allow_poll.set()
                                if not future.done():
                                    runtime.stopping.set()
                        if len(executed) != 1:
                            raise RuntimeError("Mock action did not execute exactly once")
                    summary = {
                        "run_id": run.run_id,
                        "mode": run.mode,
                        "mock_work": True,
                        "hold_command_id": held["command_id"],
                        "hold_state": held["state"],
                        "resume_command_id": resumed["command_id"],
                        "resume_state": resumed["state"],
                        "independent_task_completed": independent.completed,
                        "mock_action_executions": len(executed),
                        "telemetry_degraded": sdk.telemetry_degraded,
                    }
            summary["trace_flush_completed"] = provider.force_flush(timeout_millis=10000)
            print(json.dumps(summary, indent=2))
    finally:
        provider.shutdown()


if __name__ == "__main__":
    main()
