"""Live cooperative group review: four guarded tasks, one independent mock task.

No model calls, approval resolution, payments or protected business effects occur.
The CLI is bounded; start a fresh run for each recording instead of reusing expired hosts.
"""

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from swarmcircuit import SwarmCircuit
from swarmcircuit.runtime import ControlError


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=int, default=300)
    parser.add_argument("--exit-after-applied", action="store_true")
    args = parser.parse_args()
    if not 30 <= args.duration <= 600:
        parser.error("Use a 30–600 second bounded demo")
    endpoint = os.getenv("SWARM_API_URL", "http://127.0.0.1:18005")
    with SwarmCircuit(
        os.environ["SWARM_PROJECT_ID"], os.environ["SWARM_SDK_PROJECT_TOKEN"], endpoint
    ) as sdk:
        with sdk.run("Live dependency containment · mock", mode="control", simulation=True) as run:
            plan = run.task("Plan study", agent="demo-planner")
            root = run.task("Request dataset access", agent="demo-access")
            research = run.task("Research gated dataset", agent="demo-research")
            validate = run.task("Validate gated dataset", agent="demo-validator")
            report = run.task("Write gated report", agent="demo-writer")
            independent = run.task("Independent public reference", agent="demo-public")
            root.depends_on(plan)
            research.depends_on(root)
            validate.depends_on(root)
            report.depends_on(research)
            report.depends_on(validate)
            independent.depends_on(plan)
            with plan:
                pass
            scope = {
                "principal": "containment-demo",
                "purpose": "mock dataset read",
                "resource": "mock:shared-dataset",
                "counterparty": "mock.example",
                "permission_scope": "read",
                "policy_revision": "demo-v1",
                "amount": "0.01",
                "asset": "MOCK",
            }
            protected = [root, research, validate, report]
            approval_id = ""
            for task in protected:
                with task:
                    approval_id = task.wait_for_approval(scope)
            entered = [Event() for _ in protected]
            with run.runtime("containment-demo-host", poll_interval=0.15) as runtime:

                def worker(index):
                    try:
                        runtime.checkpoint(
                            protected[index],
                            action="before_mock_dataset_read",
                            timeout=args.duration + 10,
                            on_enter=lambda point: entered[index].set(),
                        )
                    except ControlError:
                        return "closed_guarded"
                    raise RuntimeError(
                        "A pending approval unexpectedly released a protected checkpoint"
                    )

                with ThreadPoolExecutor(max_workers=4) as pool:
                    futures = [pool.submit(worker, i) for i in range(4)]
                    try:
                        if not all(e.wait(10) for e in entered):
                            raise RuntimeError("Not all guarded actors reached their boundaries")
                        print(
                            json.dumps(
                                {
                                    "run_id": run.run_id,
                                    "approval_id": approval_id,
                                    "simulation": True,
                                    "instruction": (
                                        "Open Approvals, review dependency containment, preview "
                                        "four targets, request holds."
                                    ),
                                    "url": f"http://127.0.0.1:3300/runs/{run.run_id}?tab=approvals",
                                }
                            ),
                            flush=True,
                        )
                        until = time.monotonic() + args.duration
                        applied = []
                        while time.monotonic() < until:
                            response = sdk._request(
                                "GET", f"/api/v1/runs/{run.run_id}/control-commands?limit=100"
                            )
                            response.raise_for_status()
                            applied = [
                                c
                                for c in response.json()["items"]
                                if c["state"] == "applied"
                                and c["command_kind"] == "hold_task"
                                and c["acknowledgements"]
                            ]
                            if applied and not independent.completed:
                                with independent:
                                    pass
                            for f in futures:
                                if f.done():
                                    f.result()
                            if len(applied) == 4 and args.exit_after_applied:
                                break
                            time.sleep(0.2)
                        print(
                            json.dumps(
                                {
                                    "run_id": run.run_id,
                                    "matching_applied_holds": len(applied),
                                    "independent_completed": independent.completed,
                                    "protected_mock_effects": 0,
                                    "approval_remains_pending": True,
                                    "telemetry_degraded": sdk.telemetry_degraded,
                                }
                            ),
                            flush=True,
                        )
                    finally:
                        runtime.stopping.set()
                    for future in futures:
                        future.result(timeout=10)


if __name__ == "__main__":
    main()
