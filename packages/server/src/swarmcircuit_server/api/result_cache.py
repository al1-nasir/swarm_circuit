"""Exact, persistent presentation aggregates; sealed protocol and trial evidence stay unchanged."""

import json
import logging
import random
from statistics import mean
from threading import Lock
from typing import Any

from swarmcircuit_server.db.store import Database, now_ms
from swarmcircuit_server.research.protocol import ARMS, METRICS, SCENARIOS
from swarmcircuit_server.research.store import plan

log = logging.getLogger("swarmcircuit")


def summarize(values: list[float], *, salt: str) -> dict[str, Any]:
    """Same percentile bootstrap as the frozen reducer, using exact binary-rational sums.

    IEEE float denominators are powers of two. Summing their scaled integer
    numerators avoids repeated Fraction construction while preserving the exact
    sample means and random draw sequence of statistics.mean.
    """
    if not values:
        return {"n": 0, "mean": None, "low": None, "high": None}
    n = len(values)
    result: dict[str, Any] = {"n": n, "mean": mean(values), "low": None, "high": None}
    if n < 2:
        return result
    if all(value == values[0] for value in values):
        return {**result, "low": values[0], "high": values[0]}
    ratios = [float(value).as_integer_ratio() for value in values]
    denominator = max(d for _, d in ratios)
    numerators = [a * (denominator // b) for a, b in ratios]
    divisor = denominator * n
    rng = random.Random(salt)
    bootstrap = sorted(sum(rng.choices(numerators, k=n)) / divisor for _ in range(1000))
    return {**result, "low": bootstrap[24], "high": bootstrap[974]}


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
            contrasts.append(
                {
                    "scenario": scenario,
                    "arm": arm,
                    "reference": reference,
                    "metric": metric,
                    "paired_seeds": paired,
                    **summarize(
                        [seeds[s] - baseline[s] for s in paired],
                        salt=f"pair:{scenario}:{arm}:{metric}",
                    ),
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


class ResultCache:
    """Serialize cold computations and persist results across backend restarts."""

    def __init__(self) -> None:
        self.lock = Lock()

    def get(self, db: Database, project_id: str, eid: str) -> dict[str, Any]:
        # Scope checks happen before consulting a cache or waiting for another reader.
        with db.read() as conn:
            plan(conn, project_id, eid)
        with self.lock:
            with db.read() as conn:
                saved = plan(conn, project_id, eid)
                count = conn.execute(
                    "SELECT COUNT(*) FROM experiment_trials WHERE experiment_id=?", (eid,)
                ).fetchone()[0]
                cached = conn.execute(
                    "SELECT result_json FROM research_result_cache "
                    "WHERE experiment_id=? AND trial_count=?",
                    (eid, count),
                ).fetchone()
                if cached:
                    return json.loads(cached[0])
                counts = dict(
                    conn.execute(
                        "SELECT state,COUNT(*) FROM experiment_trials WHERE experiment_id=? "
                        "GROUP BY state",
                        (eid,),
                    ).fetchall()
                )
                rows = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT t.scenario_key,t.policy_arm,t.seed,m.metric_key,m.metric_value "
                        "FROM experiment_trials t JOIN experiment_measurements m "
                        "ON m.trial_id=t.trial_id WHERE t.experiment_id=? AND "
                        "t.state='completed' ORDER BY "
                        "t.scenario_key,t.policy_arm,t.seed,m.metric_key",
                        (eid,),
                    )
                ]
                failures = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT t.trial_id,t.scenario_key,t.policy_arm,t.seed,a.failure_code "
                        "FROM experiment_trials t JOIN research_trial_artifacts a "
                        "ON a.trial_id=t.trial_id WHERE t.experiment_id=? AND t.state='failed' "
                        "ORDER BY t.scenario_key,t.policy_arm,t.seed",
                        (eid,),
                    )
                ]
            protocol = saved["specification"]["protocol"]
            expected = len(protocol["scenarios"]) * len(protocol["arms"]) * len(protocol["seeds"])
            result = {
                "experiment": saved,
                "expected_trials": expected,
                "completed": counts.get("completed", 0),
                "failed": counts.get("failed", 0),
                "missing": expected - count,
                "failures": failures,
                "arms": ARMS,
                "scenarios": SCENARIOS,
                "metrics": {
                    k: {"unit": v[0], "higher_is_better": v[1]} for k, v in METRICS.items()
                },
                **aggregate(rows),
            }
            data = json.dumps(result, separators=(",", ":"), allow_nan=False)
            # If an import raced this snapshot, its newer trial count makes this
            # entry ineligible on the next read. Never invalidate sealed evidence.
            db.write(
                lambda conn: conn.execute(
                    "INSERT INTO research_result_cache VALUES (?,?,?,?) "
                    "ON CONFLICT(experiment_id) DO UPDATE SET trial_count=excluded.trial_count,"
                    "result_json=excluded.result_json,created_at_ms=excluded.created_at_ms "
                    "WHERE research_result_cache.trial_count<=excluded.trial_count",
                    (eid, count, data, now_ms()),
                )
            )
            return result

    def prepare_if_complete(self, db: Database, project_id: str, eid: str) -> None:
        try:
            self._prepare_if_complete(db, project_id, eid)
        except Exception as exc:
            # Derived presentation work must not turn an already-sealed trial's
            # successful response into an ambiguous failed write. GET can retry.
            log.warning(
                "experiment_summary_prepare_failed",
                extra={"experiment_id": eid, "failure_code": type(exc).__name__},
            )

    def _prepare_if_complete(self, db: Database, project_id: str, eid: str) -> None:
        with db.read() as conn:
            saved = plan(conn, project_id, eid)
            p = saved["specification"]["protocol"]
            expected = len(p["scenarios"]) * len(p["arms"]) * len(p["seeds"])
            actual = conn.execute(
                "SELECT COUNT(*) FROM experiment_trials WHERE experiment_id=?", (eid,)
            ).fetchone()[0]
        if actual == expected:
            self.get(db, project_id, eid)
