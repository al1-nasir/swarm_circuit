"""Project-scoped research persistence. Every completed trial seals replayable evidence."""

import csv
import io
import json
import sqlite3
from typing import Any
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from swarmcircuit_server.config import Settings
from swarmcircuit_server.db.store import Database, now_ms
from swarmcircuit_server.errors import Problem
from swarmcircuit_server.ingest.events import EventBatch, ingest_batch, outbox
from swarmcircuit_server.research.metrics import aggregate, measurements
from swarmcircuit_server.research.protocol import (
    ARMS,
    DEPENDENCIES,
    METRICS,
    SCENARIOS,
    TASKS,
    Protocol,
    canonical,
    digest,
)
from swarmcircuit_server.research.simulator import simulate


class CreateExperiment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    experiment_id: UUID
    title: str = Field(min_length=1, max_length=150)
    protocol: Protocol
    implementation_sha: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_kind: str = Field(default="synthetic", pattern=r"^(synthetic|llm_workload_replay)$")


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tick: int = Field(ge=0, le=120)
    task: str = Field(pattern=r"^(access|research|validate|report|public)$")
    action: str = Field(pattern=r"^(attempt|wait)$")


class ModelProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(default="none", max_length=100)
    provider_host: str = Field(default="none", max_length=150, pattern=r"^[a-zA-Z0-9.:-]+$")
    calls: int = Field(default=0, ge=0, le=60)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    transcript_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    limitation: str = Field(default="Synthetic actors; no LLM calls.", max_length=500)


class TrialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: str = Field(max_length=50)
    arm: str = Field(max_length=50)
    seed: int = Field(ge=0, lt=2**31)
    expected_artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    proposals: list[Proposal] | None = Field(default=None, max_length=300)
    provenance: ModelProvenance = Field(default_factory=ModelProvenance)
    failure_code: str | None = Field(
        default=None,
        pattern=r"^(provider_unavailable|budget_exhausted|invalid_model_output|runner_failure)$",
    )


def plan(conn: sqlite3.Connection, project_id: str, eid: str) -> dict[str, Any]:
    found = conn.execute(
        "SELECT * FROM experiment_plans WHERE experiment_id=? AND project_id=?", (eid, project_id)
    ).fetchone()
    if not found:
        raise Problem(404, "not_found", "Experiment not found in this project")
    result = dict(found)
    result["specification"] = json.loads(result.pop("specification_json"))
    return result


def create(db: Database, config: Settings, body: CreateExperiment) -> dict[str, Any]:
    eid = str(body.experiment_id)
    specification = {
        "protocol": body.protocol.model_dump(mode="json"),
        "implementation_sha": body.implementation_sha,
        "source_kind": body.source_kind,
        "preparation_date": "2026-11-05",
        "evidence_scope": (
            "Simulated tool effects. LLM workload replay, if present, is "
            "open-loop, not a closed-loop agent benchmark."
        ),
    }

    def save(conn: sqlite3.Connection) -> dict[str, Any]:
        existing = conn.execute(
            "SELECT * FROM experiment_plans WHERE experiment_id=?", (eid,)
        ).fetchone()
        if existing:
            if (
                existing["project_id"] != config.project_id
                or existing["title"] != body.title
                or existing["specification_json"] != canonical(specification)
            ):
                raise Problem(
                    409, "experiment_conflict", "Experiment identity already seals different inputs"
                )
        else:
            conn.execute(
                "INSERT INTO experiment_plans VALUES (?,?,?,?,?,?,?)",
                (
                    eid,
                    config.project_id,
                    body.title,
                    body.protocol.version,
                    digest(body.protocol.model_dump(mode="json")),
                    canonical(specification),
                    now_ms(),
                ),
            )
        return plan(conn, config.project_id, eid)

    return db.write(save)


def _projection(
    conn: sqlite3.Connection,
    config: Settings,
    rid: str,
    body: TrialRequest,
    outcome: dict[str, Any],
    at: int,
    horizon: int,
) -> None:
    base = at - (horizon + 60) * 1000
    events: list[dict[str, Any]] = []
    tids = {name: str(uuid5(UUID(rid), "task:" + name)) for name in TASKS}
    aids = {name: str(uuid5(UUID(config.project_id), "research-actor:" + name)) for name in TASKS}

    def event(kind: str, task: str = "", tick: int = 0, **payload: Any) -> None:
        index = len(events)
        events.append(
            {
                "event_id": str(uuid5(UUID(rid), f"event:{index}")),
                "source_event_key": f"research:{rid}:{index}",
                "event_kind": kind,
                "occurred_at_ms": base + tick * 1000,
                **({"agent_id": aids[task], "task_id": tids[task]} if task else {}),
                "payload": payload,
            }
        )

    event("workflow.started")
    for task in TASKS:
        # Register the agent before its task; neither represents a live model process.
        index = len(events)
        events.append(
            {
                "event_id": str(uuid5(UUID(rid), f"event:{index}")),
                "source_event_key": f"research:{rid}:{index}",
                "event_kind": "agent.started",
                "occurred_at_ms": base,
                "agent_id": aids[task],
                "payload": {
                    "external_agent_key": f"research:{task}",
                    "display_name": f"Simulated {task}",
                    "role": "research actor",
                },
            }
        )
        event("task.created", task, external_task_key=task, title=task.title())
    for child, parents in DEPENDENCIES.items():
        for parent in sorted(parents):
            event("task.dependency_added", child, prerequisite_task_id=tids[parent])
    completed = {e["task"] for e in outcome["truth"] if e["kind"] == "task.completed"}
    for item in outcome["truth"]:
        if item["kind"] == "task.completed":
            event("task.completed", item["task"], item["tick"])
        elif item["kind"] == "action.started":
            event("task.started", item["task"], item["tick"])
    if len(completed) == len(TASKS):
        event("workflow.completed", tick=horizon)
    result = ingest_batch(
        conn,
        rid,
        config.project_id,
        config.source_id("sdk"),
        EventBatch.model_validate({"events": events}),
    )
    if result["rejected"]:
        raise RuntimeError("Research projection rejected; trial transaction rolled back")
    if len(completed) != len(TASKS):
        # End a bounded replay without inventing a human approval or a live runtime.
        conn.execute(
            (
                "UPDATE workflow_runs SET "
                "status='cancelled',ended_at_ms=?,updated_at_ms=? WHERE run_id=?"
            ),
            (base + horizon * 1000, at, rid),
        )


def record_trial(db: Database, config: Settings, eid: str, body: TrialRequest) -> dict[str, Any]:
    with db.read() as conn:
        saved = plan(conn, config.project_id, eid)
    specification = saved["specification"]
    protocol = Protocol.model_validate(specification["protocol"])
    if (
        body.scenario not in protocol.scenarios
        or body.arm not in protocol.arms
        or body.seed not in protocol.seeds
    ):
        raise Problem(
            422, "trial_outside_protocol", "Trial is outside the sealed experiment protocol"
        )
    source_kind = specification["source_kind"]
    if (body.proposals is not None) != (
        source_kind == "llm_workload_replay"
    ) and not body.failure_code:
        raise Problem(
            422,
            "source_mismatch",
            "LLM workload evidence requires an explicit recorded proposal tape",
        )
    if (
        source_kind == "llm_workload_replay"
        and not body.failure_code
        and (
            body.provenance.calls < 1
            or body.provenance.model == "none"
            or body.provenance.provider_host == "none"
            or body.provenance.transcript_sha256 is None
        )
    ):
        raise Problem(
            422,
            "missing_model_provenance",
            "Record the model, provider, call count and transcript hash for a live workload",
        )
    proposals = [p.model_dump() for p in body.proposals] if body.proposals is not None else None
    if proposals is not None and len({(p["tick"], p["task"]) for p in proposals}) != len(proposals):
        raise Problem(422, "duplicate_proposal", "One action per actor and tick is permitted")
    if any(p["tick"] >= protocol.horizon_ticks for p in proposals or []):
        raise Problem(422, "invalid_proposal", "Proposal exceeds the experiment horizon")
    result: dict[str, Any] = (
        simulate(protocol, body.scenario, body.arm, body.seed, proposals)
        if not body.failure_code
        else {
            "truth": [],
            "observations": [],
            "input_sha256": digest(body.model_dump(mode="json")),
            "artifact_sha256": digest({"failure": body.failure_code}),
        }
    )
    if body.expected_artifact_sha256 and body.expected_artifact_sha256 != result["artifact_sha256"]:
        raise Problem(409, "replay_mismatch", "Runner and server do not produce identical evidence")
    metric_values = measurements(protocol, result["truth"]) if not body.failure_code else {}
    identity = f"{body.scenario}:{body.arm}:{body.seed}"
    tid = str(uuid5(UUID(eid), "trial:" + identity))
    rid = str(uuid5(UUID(eid), "run:" + identity))
    provenance = body.provenance.model_dump(mode="json")
    record_sha = digest(
        {
            "artifact": result["artifact_sha256"],
            "provenance": provenance,
            "proposals": proposals,
            "failure": body.failure_code,
        }
    )
    at = now_ms()

    def save(conn: sqlite3.Connection) -> dict[str, Any]:
        existing = conn.execute(
            "SELECT model_config_json FROM experiment_trials WHERE trial_id=?", (tid,)
        ).fetchone()
        if existing:
            if json.loads(existing[0])["record_sha256"] != record_sha:
                raise Problem(
                    409,
                    "trial_conflict",
                    "A sealed trial cannot be overwritten; use a new experiment",
                )
            return {
                "trial_id": tid,
                "run_id": rid,
                "state": "failed" if body.failure_code else "completed",
                "replayed": True,
            }
        # A workload tape is shared across arms; model sampling is not quietly repeated per arm.
        previous = conn.execute(
            (
                "SELECT a.input_sha256 FROM research_trial_artifacts a JOIN "
                "experiment_trials t ON t.trial_id=a.trial_id WHERE "
                "t.experiment_id=? AND t.scenario_key=? AND t.seed=? AND "
                "t.state='completed' LIMIT 1"
            ),
            (eid, body.scenario, body.seed),
        ).fetchone()
        if previous and not body.failure_code and previous[0] != result["input_sha256"]:
            raise Problem(
                409,
                "unmatched_inputs",
                "Matched policy arms must share the same world and proposal tape",
            )
        metadata = {
            "simulation": True,
            "research": True,
            "experiment_id": eid,
            "scenario": body.scenario,
            "arm": body.arm,
            "seed": body.seed,
            "source_kind": source_kind,
        }
        conn.execute(
            (
                "INSERT INTO "
                "workflow_runs(run_id,project_id,name,mode,status,experiment_seed,cre"
                "ated_at_ms,updated_at_ms,metadata_json) VALUES "
                "(?,?,?,'observe','created',?,?,?,?)"
            ),
            (
                rid,
                config.project_id,
                f"Research · {body.scenario} · {body.arm} · {body.seed}",
                body.seed,
                at,
                at,
                canonical(metadata),
            ),
        )
        state = "failed" if body.failure_code else "completed"
        conn.execute(
            "INSERT INTO experiment_trials VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                tid,
                eid,
                rid,
                body.scenario,
                body.arm,
                body.seed,
                specification["implementation_sha"],
                canonical({**provenance, "record_sha256": record_sha}),
                state,
                at,
                at,
            ),
        )
        conn.execute(
            "INSERT INTO research_trial_artifacts VALUES (?,?,?,?,?,?,?,?,?)",
            (
                tid,
                source_kind,
                result["input_sha256"],
                result["artifact_sha256"],
                "\n".join(canonical(e) for e in result["truth"]),
                "\n".join(canonical(e) for e in result["observations"]),
                canonical(proposals) if proposals is not None else None,
                canonical(provenance),
                body.failure_code,
            ),
        )
        for key, metric in metric_values.items():
            conn.execute(
                "INSERT INTO experiment_measurements VALUES (?,?,?,?,?,?,?)",
                (
                    str(uuid5(UUID(tid), key)),
                    tid,
                    key,
                    metric["value"],
                    metric["unit"],
                    metric["denominator"],
                    at,
                ),
            )
        if not body.failure_code:
            _projection(conn, config, rid, body, result, at, protocol.horizon_ticks)
        else:
            conn.execute("UPDATE workflow_runs SET status='failed' WHERE run_id=?", (rid,))
        outbox(conn, rid, "research.trial_recorded", tid)
        return {"trial_id": tid, "run_id": rid, "state": state, "replayed": False}

    return db.write(save)


def result(db: Database, project_id: str, eid: str) -> dict[str, Any]:
    with db.read() as conn:
        saved = plan(conn, project_id, eid)
        counts = dict(
            conn.execute(
                "SELECT state,COUNT(*) FROM experiment_trials WHERE experiment_id=? GROUP BY state",
                (eid,),
            ).fetchall()
        )
        rows = [
            dict(r)
            for r in conn.execute(
                (
                    "SELECT "
                    "t.scenario_key,t.policy_arm,t.seed,m.metric_key,m.metric_value FROM "
                    "experiment_trials t JOIN experiment_measurements m ON "
                    "m.trial_id=t.trial_id WHERE t.experiment_id=? AND "
                    "t.state='completed' ORDER BY "
                    "t.scenario_key,t.policy_arm,t.seed,m.metric_key"
                ),
                (eid,),
            )
        ]
        failures = [
            dict(r)
            for r in conn.execute(
                (
                    "SELECT t.trial_id,t.scenario_key,t.policy_arm,t.seed,a.failure_code "
                    "FROM experiment_trials t JOIN research_trial_artifacts a ON "
                    "a.trial_id=t.trial_id WHERE t.experiment_id=? AND t.state='failed' "
                    "ORDER BY t.scenario_key,t.policy_arm,t.seed"
                ),
                (eid,),
            )
        ]
    p = saved["specification"]["protocol"]
    expected = len(p["scenarios"]) * len(p["arms"]) * len(p["seeds"])
    return {
        "experiment": saved,
        "expected_trials": expected,
        "completed": counts.get("completed", 0),
        "failed": counts.get("failed", 0),
        "missing": expected - sum(counts.values()),
        "failures": failures,
        "arms": ARMS,
        "scenarios": SCENARIOS,
        "metrics": {k: {"unit": v[0], "higher_is_better": v[1]} for k, v in METRICS.items()},
        **aggregate(rows),
    }


def export_csv(conn: sqlite3.Connection, project_id: str, eid: str) -> str:
    saved = plan(conn, project_id, eid)
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "experiment_id",
            "protocol_version",
            "protocol_sha256",
            "source_sha256",
            "source_kind",
            "scenario",
            "arm",
            "seed",
            "trial_id",
            "run_id",
            "state",
            "metric",
            "value",
            "unit",
            "denominator",
            "failure_code",
        ]
    )
    for r in conn.execute(
        (
            "SELECT "
            "t.*,m.metric_key,m.metric_value,m.unit,m.denominator,a.source_kind,a"
            ".failure_code FROM experiment_trials t LEFT JOIN "
            "experiment_measurements m ON m.trial_id=t.trial_id JOIN "
            "research_trial_artifacts a ON a.trial_id=t.trial_id WHERE "
            "t.experiment_id=? ORDER BY "
            "t.scenario_key,t.policy_arm,t.seed,m.metric_key"
        ),
        (eid,),
    ):
        writer.writerow(
            [
                eid,
                saved["protocol_version"],
                saved["protocol_sha256"],
                r["implementation_sha"],
                r["source_kind"],
                r["scenario_key"],
                r["policy_arm"],
                r["seed"],
                r["trial_id"],
                r["run_id"],
                r["state"],
                r["metric_key"],
                r["metric_value"],
                r["unit"],
                r["denominator"],
                r["failure_code"],
            ]
        )
    return output.getvalue()
