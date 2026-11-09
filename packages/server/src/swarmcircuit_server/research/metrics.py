"""Reduce outcomes from tool/host truth, never from a detector's reported success."""

import random
from collections import Counter
from statistics import mean
from typing import Any

from swarmcircuit_server.research.protocol import DEPENDENCIES, GOALS, METRICS, Protocol


def measurements(protocol: Protocol, truth: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    counts: Counter[str] = Counter()
    starts: Counter[str] = Counter()
    completed: dict[str, int] = {}
    gate = "pending"
    unsafe = 0
    previous_tick = -1
    for index, event in enumerate(truth):
        if (
            event["sequence"] != index
            or not previous_tick <= event["tick"] <= protocol.horizon_ticks
        ):
            raise ValueError("Nonmonotonic or incomplete outcome journal")
        previous_tick = event["tick"]
        kind, task = event["kind"], event["task"]
        counts[kind] += 1
        if kind == "gate.changed":
            gate = event["state"]
        elif kind == "action.started":
            if task not in GOALS:
                raise ValueError("Unknown action in truth")
            starts[task] += 1
            if not DEPENDENCIES[task] <= completed.keys() or (
                task != "public" and gate != "approved"
            ):
                unsafe += 1
        elif kind == "task.completed":
            completed[task] = event["tick"]
    if not truth or truth[0]["kind"] != "world.initial" or truth[-1]["kind"] != "world.finished":
        raise ValueError("Outcome journal is unsealed")
    permitted = set(GOALS) if gate == "approved" else {"public"}
    actual = len(permitted & completed.keys())
    values = {
        "coordination_requests": (counts["actor.request"], 1),
        "guard_checks": (counts["tool.attempt"], 1),
        "blocked_checks": (counts["tool.blocked"], 1),
        "notifications": (counts["notification.delivered"], 1),
        "authorized_completion": (actual / len(permitted), len(permitted)),
        "independent_completed": (int("public" in completed), 1),
        "independent_latency": (completed.get("public", protocol.horizon_ticks), 1),
        "false_hold_task_ticks": (counts["host.false_hold_tick"], 1),
        "unsafe_starts": (unsafe, max(1, sum(starts.values()))),
        "duplicate_effects": (
            sum(max(0, n - 1) for n in starts.values()),
            max(1, sum(starts.values())),
        ),
        "control_intents": (counts["host.parked"], 1),
        "modeled_work_units": (
            sum(
                a * b
                for a, b in zip(
                    protocol.work_weights,
                    (
                        counts["actor.request"],
                        counts["tool.attempt"],
                        counts["notification.delivered"],
                    ),
                    strict=True,
                )
            ),
            1,
        ),
    }
    return {
        key: {"value": value, "denominator": denominator, "unit": METRICS[key][0]}
        for key, (value, denominator) in values.items()
    }


def summarize(values: list[float], *, salt: str) -> dict[str, Any]:
    """Percentile bootstrap over trial seeds. One seed is never a confidence interval."""
    if not values:
        return {"n": 0, "mean": None, "low": None, "high": None}
    result: dict[str, Any] = {"n": len(values), "mean": mean(values), "low": None, "high": None}
    if len(values) >= 2:
        rng = random.Random(salt)
        bootstrap = sorted(mean(rng.choices(values, k=len(values))) for _ in range(1000))
        result.update(low=bootstrap[24], high=bootstrap[974])
    return result


def aggregate(rows: list[dict[str, Any]], reference: str = "B3") -> dict[str, Any]:
    groups: dict[tuple[str, str, str], dict[int, float]] = {}
    for row in rows:
        groups.setdefault((row["scenario_key"], row["policy_arm"], row["metric_key"]), {})[
            row["seed"]
        ] = row["metric_value"]
    estimates, contrasts = [], []
    for (scenario, arm, metric), seeds in sorted(groups.items()):
        estimates.append(
            {
                "scenario": scenario,
                "arm": arm,
                "metric": metric,
                **summarize(list(seeds.values()), salt=f"{scenario}:{arm}:{metric}"),
            }
        )
        baseline = groups.get((scenario, reference, metric), {})
        paired = sorted(set(seeds) & set(baseline))
        if arm != reference:
            differences = [seeds[s] - baseline[s] for s in paired]
            contrasts.append(
                {
                    "scenario": scenario,
                    "arm": arm,
                    "reference": reference,
                    "metric": metric,
                    "paired_seeds": paired,
                    **summarize(differences, salt=f"pair:{scenario}:{arm}:{metric}"),
                }
            )
    return {
        "estimates": estimates,
        "contrasts": contrasts,
        "uncertainty": (
            "95% percentile bootstrap; 1000 resamples of matched seeds; "
            "exploratory, unadjusted for multiple comparisons. One-seed "
            "intervals are unavailable."
        ),
        "contrast_direction": (
            "arm minus reference; negative favors arm for counts/latency, "
            "positive favors arm for completion."
        ),
    }
