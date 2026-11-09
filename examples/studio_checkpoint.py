"""Bounded interactive Studio exercise: one reversible mock action, no external effects."""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Any

from swarmcircuit import SwarmCircuit


def main() -> None:
    endpoint = os.getenv("SWARM_API_URL", "http://127.0.0.1:8000")
    with SwarmCircuit(
        os.environ["SWARM_PROJECT_ID"], os.environ["SWARM_SDK_PROJECT_TOKEN"], endpoint
    ) as sdk:
        with sdk.run("Studio checkpoint exercise", mode="control", simulation=True) as run:
            protected = run.task("Review public references", agent="researcher")
            independent = run.task("Independent source check", agent="validator")
            entered = Event()
            executed: list[str] = []

            def commands() -> list[dict[str, Any]]:
                response = sdk._request(
                    "GET", f"/api/v1/runs/{run.run_id}/control-commands?limit=100"
                )
                response.raise_for_status()
                return list(response.json()["items"])

            with run.runtime("studio-exercise", poll_interval=0.05) as runtime:

                def on_enter(point: dict[str, Any]) -> None:
                    entered.set()
                    # Explicit host coordination makes the available boundary visible to the UI.
                    until = time.monotonic() + 240
                    while time.monotonic() < until and not runtime.stopping.is_set():
                        if any(
                            c["command_kind"] == "hold_task" and c["task_id"] == protected.task_id
                            for c in commands()
                        ):
                            return
                        time.sleep(0.15)
                    from swarmcircuit import ControlError

                    raise ControlError("demonstration_hold_deadline")

                def worker() -> None:
                    with protected:
                        runtime.checkpoint(
                            protected,
                            action="before_mock_reference_read",
                            timeout=240,
                            on_enter=on_enter,
                        )
                        executed.append("mock-reference-read")

                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(worker)
                    try:
                        if not entered.wait(5):
                            raise RuntimeError("Checkpoint did not become available")
                        print(
                            json.dumps(
                                {
                                    "run_id": run.run_id,
                                    "task_id": protected.task_id,
                                    "simulation": True,
                                    "instruction": "Use Studio: hold, then resume.",
                                }
                            ),
                            flush=True,
                        )
                        until = time.monotonic() + 240
                        while time.monotonic() < until:
                            if any(
                                c["command_kind"] == "hold_task" and c["state"] == "applied"
                                for c in commands()
                            ):
                                with independent:
                                    pass
                                break
                            if future.done():
                                future.result()
                            time.sleep(0.1)
                        future.result(timeout=245)
                    finally:
                        runtime.stopping.set()
                print(
                    json.dumps(
                        {
                            "run_id": run.run_id,
                            "mock_action_executions": len(executed),
                            "independent_completed": independent.completed,
                            "telemetry_degraded": sdk.telemetry_degraded,
                        }
                    ),
                    flush=True,
                )


if __name__ == "__main__":
    main()
