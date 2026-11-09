"""Six deterministic agents, explicit dependencies, shared pending gate, healthy branch."""

import argparse
import json
import os
import random
import time
from typing import Any

import httpx
from swarmcircuit import SwarmCircuit
from swarmcircuit.instrumentation import create_otlp_provider

BASE_MS = 1_793_491_200_000


def run_scenario(sdk: SwarmCircuit, seed: int = 7, *, base_ms: int = BASE_MS) -> dict[str, Any]:
    """Deterministic logical workload, not a comparison study or a real payment."""
    rng = random.Random(seed)
    tick = base_ms

    def clock() -> int:
        nonlocal tick
        tick += 100
        return tick

    old_clock, sdk.clock_ms = sdk.clock_ms, clock
    try:
        with sdk.run(f"shared-approval-seed-{seed}", simulation=True) as run:
            plan = run.task("Plan study", agent="planner")
            public = run.task("Independent public research", agent="researcher-public")
            gated = run.task(
                "Research paid dataset", agent="researcher-gated", deadline_at_ms=tick + 500
            )
            buyer = run.task("Request dataset access", agent="buyer", deadline_at_ms=tick + 500)
            validator = run.task("Validate dataset", agent="validator", deadline_at_ms=tick + 500)
            writer = run.task("Write gated report", agent="writer", deadline_at_ms=tick + 500)
            public.depends_on(plan)
            buyer.depends_on(plan)
            gated.depends_on(buyer)
            validator.depends_on(gated)
            writer.depends_on(validator)
            with plan:
                plan.handoff("buyer")
            scope = {
                "principal": "demo-research-team",
                "purpose": "dataset-access",
                "resource": "mock:dataset-1",
                "counterparty": "mock.vendor.example",
                "permission_scope": "read",
                "policy_revision": "demo-v1",
                "amount": "1.00",
                "asset": "MOCK",
            }
            with buyer:
                approval_id = buyer.wait_for_approval(scope)
            for task in (gated, validator, writer):
                with task:
                    task.wait_for_approval(scope)
                    for attempt in range(2, rng.randint(3, 5) + 1):
                        task.retry_requested(attempt, "mock:dataset-1")
            with public:
                pass  # Independently useful work completes while the shared gate remains pending.
            return {
                "run_id": run.run_id,
                "seed": seed,
                "mode": "observe",
                "approval_id": approval_id,
                "independent_task_id": public.task_id,
                "blocked_task_ids": [t.task_id for t in (buyer, gated, validator, writer)],
                "logical_horizon_ms": tick,
                "simulated": True,
                "telemetry_degraded": sdk.telemetry_degraded,
            }
    finally:
        sdk.clock_ms = old_clock


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    endpoint = os.getenv("SWARM_API_URL", "http://127.0.0.1:8000")
    token = os.environ["SWARM_SDK_PROJECT_TOKEN"]
    provider = create_otlp_provider(endpoint, token)
    try:
        with SwarmCircuit(
            os.environ["SWARM_PROJECT_ID"],
            token,
            endpoint,
            tracer=provider.get_tracer("six-agent-demo"),
        ) as sdk:
            summary = run_scenario(sdk, args.seed, base_ms=time.time_ns() // 1_000_000 - 10_000)
        flushed = provider.force_flush(timeout_millis=10_000)
        summary["trace_flush_completed"] = flushed
        response = httpx.get(
            f"{endpoint}/api/v1/runs/{summary['run_id']}/incidents",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        response.raise_for_status()
        summary["incidents"] = [
            {"incident_id": i["incident_id"], "kind": i["kind"], "state": i["state"]}
            for i in response.json()["items"]
        ]
        print(json.dumps(summary, indent=2))
    finally:
        provider.shutdown()


if __name__ == "__main__":
    main()
