"""Validated, metadata-only lifecycle envelopes and atomic domain projection."""

import json
import sqlite3
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from swarmcircuit_server.db.store import now_ms
from swarmcircuit_server.errors import InvalidRecord
from swarmcircuit_server.payments.models import (
    AttemptObservation,
    DeliveryObservation,
    GateObservation,
)
from swarmcircuit_server.payments.observations import observe as observe_payment

MAX_INT = 2**63 - 1
TERMINAL = {"completed", "failed", "cancelled"}


def dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class LifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: UUID
    source_event_key: str = Field(min_length=1, max_length=180)
    event_kind: str = Field(min_length=1, max_length=100)
    occurred_at_ms: int = Field(ge=0, le=MAX_INT)
    agent_id: UUID | None = None
    task_id: UUID | None = None
    approval_id: UUID | None = None
    payload: dict[str, Any]


class EventBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[LifecycleEvent] = Field(min_length=1, max_length=250)


class Metadata(BaseModel):
    """Unknown keys are discarded before persistence, including nested content."""

    model_config = ConfigDict(extra="ignore", strict=True)


class AgentMetadata(Metadata):
    external_agent_key: str = Field(min_length=1, max_length=150)
    display_name: str = Field(min_length=1, max_length=150)
    role: str | None = Field(default=None, max_length=100)


class TaskMetadata(Metadata):
    external_task_key: str = Field(min_length=1, max_length=150)
    title: str = Field(min_length=1, max_length=150)
    deadline_at_ms: int | None = Field(default=None, ge=0, le=MAX_INT)


class DependencyMetadata(Metadata):
    prerequisite_task_id: str
    relation_kind: str = "depends_on"


class RetryMetadata(Metadata):
    attempt_no: int = Field(ge=2, le=1_000_000)
    retry_of: str = Field(min_length=1, max_length=180)


class HandoffMetadata(Metadata):
    to_agent_id: str


class ApprovalMetadata(Metadata):
    canonical_approval_key: str = Field(min_length=1, max_length=180)
    action_fingerprint: str = Field(min_length=1, max_length=180)


MODELS: dict[str, type[BaseModel]] = {
    "agent.started": AgentMetadata,
    "task.created": TaskMetadata,
    "task.dependency_added": DependencyMetadata,
    "task.retry_requested": RetryMetadata,
    "agent.handoff": HandoffMetadata,
    "approval.requested": ApprovalMetadata,
    "payment.gate_decided": GateObservation,
    "payment.attempt_submitted": AttemptObservation,
    "payment.delivery_checked": DeliveryObservation,
}
STATES = {
    "task.started": "running",
    "task.completed": "completed",
    "task.failed": "failed",
    "task.waiting_for_approval": "waiting_for_human",
}


def require_row(conn: sqlite3.Connection, sql: str, values: tuple[Any, ...]) -> sqlite3.Row:
    row = conn.execute(sql, values).fetchone()
    if row is None:
        raise InvalidRecord("Reference is not registered in this run")
    return row


def outbox(conn: sqlite3.Connection, run_id: str, topic: str, entity_id: str) -> None:
    conn.execute(
        "INSERT INTO ui_outbox(notification_id,run_id,topic,entity_id,created_at_ms) "
        "VALUES (?,?,?,?,?)",
        (str(uuid4()), run_id, topic, entity_id, now_ms()),
    )


def ingest_event(
    conn: sqlite3.Connection, run_id: str, project_id: str, source_id: str, event: LifecycleEvent
) -> bool:
    """Return False for an identical replay; conflicting replays reject without mutation."""
    if event.occurred_at_ms > now_ms() + 300_000:
        raise InvalidRecord("Event clock is more than five minutes in the future")
    model = MODELS.get(event.event_kind, Metadata)
    payload = model.model_validate(event.payload).model_dump(exclude_none=True)
    eid = str(event.event_id)
    aid = str(event.agent_id) if event.agent_id else None
    tid = str(event.task_id) if event.task_id else None
    apid = str(event.approval_id) if event.approval_id else None
    encoded = dump(payload)
    identity = (
        run_id,
        project_id,
        source_id,
        event.source_event_key,
        event.event_kind,
        aid,
        tid,
        apid,
        event.occurred_at_ms,
        encoded,
    )
    existing = conn.execute(
        "SELECT * FROM run_events WHERE event_id=? OR (source_id=? AND source_event_key=?)",
        (eid, source_id, event.source_event_key),
    ).fetchall()
    if existing:
        row = existing[0]
        stored = tuple(
            row[k]
            for k in (
                "run_id",
                "project_id",
                "source_id",
                "source_event_key",
                "event_kind",
                "agent_id",
                "task_id",
                "approval_id",
                "occurred_at_ms",
                "payload_json",
            )
        )
        if len(existing) == 1 and row["event_id"] == eid and stored == identity:
            return False
        raise InvalidRecord("Event identity conflicts with persisted evidence")
    t = event.occurred_at_ms
    if event.event_kind == "agent.started":
        if not aid:
            raise InvalidRecord("agent.started requires agent_id")
        agent = conn.execute("SELECT * FROM agents WHERE agent_id=?", (aid,)).fetchone()
        if agent and (
            agent["project_id"] != project_id
            or agent["external_agent_key"] != payload["external_agent_key"]
        ):
            raise InvalidRecord("Agent identity collision")
        if not agent:
            conn.execute(
                "INSERT INTO agents(agent_id,project_id,external_agent_key,display_name,role,"
                "created_at_ms) VALUES (?,?,?,?,?,?)",
                (
                    aid,
                    project_id,
                    payload["external_agent_key"],
                    payload["display_name"],
                    payload.get("role"),
                    t,
                ),
            )
        conn.execute(
            "INSERT INTO run_agents(run_id,agent_id,project_id,joined_at_ms,last_seen_at_ms) "
            "VALUES (?,?,?,?,?) ON CONFLICT(run_id,agent_id) DO UPDATE SET "
            "last_seen_at_ms=MAX(last_seen_at_ms,excluded.last_seen_at_ms)",
            (run_id, aid, project_id, t, t),
        )
    if aid:
        require_row(conn, "SELECT 1 FROM run_agents WHERE run_id=? AND agent_id=?", (run_id, aid))
    if event.event_kind == "task.created":
        if not tid or not aid:
            raise InvalidRecord("task.created requires task_id and agent_id")
        task = conn.execute("SELECT * FROM tasks WHERE task_id=?", (tid,)).fetchone()
        if task and (
            task["run_id"] != run_id
            or task["external_task_key"] != payload["external_task_key"]
            or task["assigned_agent_id"] != aid
        ):
            raise InvalidRecord("Task identity collision")
        if not task:
            conn.execute(
                "INSERT INTO tasks(task_id,run_id,external_task_key,assigned_agent_id,title,"
                "deadline_at_ms,created_at_ms,updated_at_ms) VALUES (?,?,?,?,?,?,?,?)",
                (
                    tid,
                    run_id,
                    payload["external_task_key"],
                    aid,
                    payload["title"],
                    payload.get("deadline_at_ms"),
                    t,
                    t,
                ),
            )
    task = None
    if tid:
        task = require_row(conn, "SELECT * FROM tasks WHERE run_id=? AND task_id=?", (run_id, tid))
        if aid and task["assigned_agent_id"] != aid:
            raise InvalidRecord("Task is assigned to a different agent")
    if event.event_kind in STATES or event.event_kind.startswith("task."):
        if not tid or task is None:
            raise InvalidRecord("Task lifecycle requires a registered task")
    if event.event_kind in STATES and tid:
        # Observation credentials cannot overwrite an active/uncertain runtime boundary.
        if conn.execute(
            "SELECT 1 FROM runtime_checkpoints WHERE task_id=? AND state<>'released'", (tid,)
        ).fetchone():
            raise InvalidRecord("Runtime boundary requires an authenticated checkpoint transition")
    if event.event_kind == "approval.requested":
        if not apid or not tid:
            raise InvalidRecord("Approval requires approval_id and task_id")
        approval = conn.execute(
            "SELECT * FROM approvals WHERE approval_id=? OR "
            "(run_id=? AND canonical_approval_key=?)",
            (apid, run_id, payload["canonical_approval_key"]),
        ).fetchone()
        if approval:
            if (
                approval["run_id"] != run_id
                or approval["approval_id"] != apid
                or approval["canonical_approval_key"] != payload["canonical_approval_key"]
                or approval["action_fingerprint"] != payload["action_fingerprint"]
            ):
                raise InvalidRecord("Approval fingerprint conflict")
        else:
            conn.execute(
                "INSERT INTO approvals(approval_id,run_id,canonical_approval_key,"
                "action_fingerprint,"
                "related_task_id,requested_at_ms) VALUES (?,?,?,?,?,?)",
                (
                    apid,
                    run_id,
                    payload["canonical_approval_key"],
                    payload["action_fingerprint"],
                    tid,
                    t,
                ),
            )
        # Observe requests; no claim that a runtime coalesced or approved anything.
        conn.execute(
            "INSERT INTO approval_requests VALUES (?,?,?,?,?,?,?)",
            (str(uuid4()), run_id, apid, tid, event.source_event_key, "presented", t),
        )
    if apid:
        require_row(
            conn, "SELECT 1 FROM approvals WHERE run_id=? AND approval_id=?", (run_id, apid)
        )
    if event.event_kind == "task.waiting_for_approval" and not apid:
        raise InvalidRecord("Waiting for approval requires approval_id")
    conn.execute(
        "INSERT INTO run_events(event_id,run_id,project_id,source_id,source_event_key,event_kind,"
        "trust_class,agent_id,task_id,approval_id,occurred_at_ms,ingested_at_ms,payload_json) "
        "VALUES (?,?,?,?,?,?,'sdk_observation',?,?,?,?,?,?)",
        (
            eid,
            run_id,
            project_id,
            source_id,
            event.source_event_key,
            event.event_kind,
            aid,
            tid,
            apid,
            t,
            now_ms(),
            encoded,
        ),
    )
    if event.event_kind in {
        "payment.gate_decided",
        "payment.attempt_submitted",
        "payment.delivery_checked",
    }:
        observe_payment(conn, run_id, tid, apid, event.event_kind, payload, eid, t)
        outbox(conn, run_id, "payment.updated", payload["payment_intent_id"])
    if event.event_kind in STATES and task is not None:
        metadata = json.loads(task["metadata_json"])
        key = [t, eid]
        state = STATES[event.event_kind]
        last_timestamp = metadata.get("state_event_order", [-1, ""])[0]
        rank = {
            "created": 0,
            "ready": 1,
            "running": 2,
            "waiting_for_human": 3,
            "completed": 4,
            "failed": 4,
            "cancelled": 4,
        }
        newer = t > last_timestamp or (
            t == last_timestamp and rank.get(state, 0) > rank.get(task["state"], 0)
        )
        # UUIDs carry identity, not causal ordering. Terminal states remain absorbing.
        if task["state"] not in TERMINAL and newer:
            metadata["state_event_order"] = key
            if apid:
                metadata["approval_id"] = apid
            conn.execute(
                "UPDATE tasks SET state=?,state_version=state_version+1,updated_at_ms=?,"
                "started_at_ms=COALESCE(started_at_ms,?),ended_at_ms=?,metadata_json=? "
                "WHERE task_id=?",
                (
                    state,
                    max(t, task["updated_at_ms"]),
                    t,
                    t if state in TERMINAL else None,
                    dump(metadata),
                    tid,
                ),
            )
            if event.event_kind == "task.started":
                conn.execute(
                    "INSERT INTO task_attempts(attempt_id,run_id,task_id,attempt_no,state,"
                    "started_at_ms) VALUES (?,?,?,1,'started',?) ON CONFLICT(task_id,attempt_no) "
                    "DO NOTHING",
                    (str(uuid4()), run_id, tid, t),
                )
            if state in TERMINAL:
                conn.execute(
                    "UPDATE task_attempts SET state=?,ended_at_ms=? WHERE task_id=? AND "
                    "state='started'",
                    ("succeeded" if state == "completed" else "failed", t, tid),
                )
    if event.event_kind == "task.dependency_added":
        prerequisite = str(UUID(payload["prerequisite_task_id"]))
        if prerequisite == tid or payload["relation_kind"] not in {"depends_on", "waits_for"}:
            raise InvalidRecord("Invalid explicit dependency")
        require_row(
            conn, "SELECT 1 FROM tasks WHERE run_id=? AND task_id=?", (run_id, prerequisite)
        )
        conn.execute(
            "INSERT INTO task_dependencies VALUES (?,?,?,?,?,1,?,?) "
            "ON CONFLICT(run_id,blocked_task_id,prerequisite_task_id,relation_kind) DO NOTHING",
            (str(uuid4()), run_id, tid, prerequisite, payload["relation_kind"], eid, t),
        )
    if event.event_kind == "task.retry_requested":
        conn.execute(
            "INSERT INTO task_attempts(attempt_id,run_id,task_id,attempt_no,state,retry_reason,"
            "idempotency_key,started_at_ms) VALUES (?,?,?,?,'unknown',?,?,?)",
            (
                str(uuid4()),
                run_id,
                tid,
                payload["attempt_no"],
                "host_requested",
                event.source_event_key,
                t,
            ),
        )
    if event.event_kind == "agent.handoff":
        target = str(UUID(payload["to_agent_id"]))
        if not aid or aid == target:
            raise InvalidRecord("Handoff requires distinct registered agents")
        require_row(
            conn, "SELECT 1 FROM run_agents WHERE run_id=? AND agent_id=?", (run_id, target)
        )
        conn.execute(
            "INSERT INTO agent_messages(message_id,run_id,from_agent_id,to_agent_id,task_id,"
            "occurred_at_ms,evidence_event_id) VALUES (?,?,?,?,?,?,?)",
            (str(uuid4()), run_id, aid, target, tid, t, eid),
        )
    refresh_run(conn, run_id, t)
    outbox(conn, run_id, "event.appended", eid)
    return True


def refresh_run(conn: sqlite3.Connection, run_id: str, timestamp: int) -> None:
    """Observed status: a waiting task never becomes a confirmed stalled incident."""
    states = [r[0] for r in conn.execute("SELECT state FROM tasks WHERE run_id=?", (run_id,))]
    workflow_done = conn.execute(
        "SELECT MAX(occurred_at_ms) FROM run_events WHERE run_id=? "
        "AND event_kind='workflow.completed' AND trust_class='sdk_observation'",
        (run_id,),
    ).fetchone()[0]
    if workflow_done is not None and states and all(s == "completed" for s in states):
        status = "completed"
    elif "failed" in states:
        status = "failed"
    elif "waiting_for_human" in states or "held" in states:
        status = "waiting"
    else:
        status = "running"
    last_end = conn.execute(
        "SELECT MAX(ended_at_ms) FROM tasks WHERE run_id=?",
        (run_id,),
    ).fetchone()[0]
    ended = max(workflow_done or 0, last_end or 0) if status in {"completed", "failed"} else None
    conn.execute(
        # Late telemetry remains evidence; it cannot restart an explicitly cancelled host.
        "UPDATE workflow_runs SET status=CASE WHEN status='cancelled' THEN status ELSE ? END,"
        "started_at_ms=CASE WHEN started_at_ms IS NULL "
        "THEN ? ELSE MIN(started_at_ms,?) END,updated_at_ms=MAX(updated_at_ms,?),"
        "ended_at_ms=CASE WHEN status='cancelled' THEN ended_at_ms ELSE ? END WHERE run_id=?",
        (
            status,
            timestamp,
            timestamp,
            timestamp,
            ended,
            run_id,
        ),
    )


def ingest_batch(
    conn: sqlite3.Connection, run_id: str, project_id: str, source_id: str, batch: EventBatch
) -> dict[str, Any]:
    counts: dict[str, Any] = {"accepted": 0, "duplicates": 0, "rejected": 0, "rejected_keys": []}
    for event in batch.events:
        conn.execute("SAVEPOINT record")
        try:
            accepted = ingest_event(conn, run_id, project_id, source_id, event)
        except (InvalidRecord, ValidationError, sqlite3.IntegrityError, ValueError, TypeError):
            conn.execute("ROLLBACK TO record")
            counts["rejected"] += 1
            counts["rejected_keys"].append(event.source_event_key)
        else:
            counts["accepted" if accepted else "duplicates"] += 1
        finally:
            conn.execute("RELEASE record")
    return counts
