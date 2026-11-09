"""Durable fenced commands and active-boundary validation; no payment authority."""

import hashlib
import hmac
import json
import logging
import sqlite3
from collections.abc import Callable
from threading import Event, Thread
from typing import Any, TypeVar
from uuid import UUID, uuid4, uuid5

from swarmcircuit_server.config import Settings
from swarmcircuit_server.controller.models import (
    Ack,
    Backpressure,
    CheckpointEnter,
    CommandRequest,
    Registration,
)
from swarmcircuit_server.db.store import Database, now_ms
from swarmcircuit_server.detectors.rules import Snapshot, reverse_closure
from swarmcircuit_server.errors import Problem
from swarmcircuit_server.ingest.events import MAX_INT, TERMINAL, dump, outbox, refresh_run
from swarmcircuit_server.payments.service import payment_guard

T = TypeVar("T")
ACTIVE = {"queued", "dispatched"}
logger = logging.getLogger("swarmcircuit.control")


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def row(conn: sqlite3.Connection, sql: str, args: tuple[Any, ...]) -> dict[str, Any]:
    result = conn.execute(sql, args).fetchone()
    if result is None:
        raise Problem(404, "not_found", "Control entity not found in this scope")
    return dict(result)


def audit(
    conn: sqlite3.Connection,
    run_id: str,
    topic: str,
    entity: str,
    payload: dict[str, Any],
    at: int,
    *,
    runtime: bool = False,
) -> None:
    project = row(conn, "SELECT project_id FROM workflow_runs WHERE run_id=?", (run_id,))[
        "project_id"
    ]
    source = str(uuid5(UUID(project), "local:control"))
    conn.execute(
        "INSERT INTO telemetry_sources(source_id,project_id,source_key,source_kind,display_name,"
        "created_at_ms) VALUES (?,?,'local:control','runtime','Local runtime control',?) "
        "ON CONFLICT(project_id,source_key) DO NOTHING",
        (source, project, at),
    )
    eid = str(uuid4())
    conn.execute(
        "INSERT INTO run_events(event_id,run_id,project_id,source_id,source_event_key,event_kind,"
        "trust_class,occurred_at_ms,ingested_at_ms,payload_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            eid,
            run_id,
            project,
            source,
            eid,
            topic,
            "sdk_observation" if runtime else "derived",
            at,
            now_ms(),
            dump(payload),
        ),
    )
    outbox(conn, run_id, topic, entity)


def command(conn: sqlite3.Connection, project: str, cid: str) -> dict[str, Any]:
    result = row(
        conn,
        "SELECT c.* FROM control_commands c JOIN workflow_runs r ON r.run_id=c.run_id "
        "WHERE c.command_id=? AND r.project_id=?",
        (cid, project),
    )
    context = conn.execute(
        "SELECT checkpoint_id FROM control_command_context WHERE command_id=?", (cid,)
    ).fetchone()
    result["checkpoint_id"] = context[0] if context else None
    result["acknowledgements"] = [
        {
            "acknowledgement_id": a["acknowledgement_id"],
            "result": a["result"],
            "received_at_ms": a["received_at_ms"],
            "runtime_session_id": a["runtime_session_id"],
            "session_fencing_epoch": a["session_fencing_epoch"],
        }
        for a in conn.execute(
            "SELECT * FROM control_acknowledgements WHERE command_id=? ORDER BY received_at_ms",
            (cid,),
        )
    ]
    return result


def finish_command(conn: sqlite3.Connection, cmd: dict[str, Any], state: str, at: int) -> None:
    conn.execute(
        "UPDATE control_commands SET state=?,completed_at_ms=? WHERE command_id=?",
        (state, at, cmd["command_id"]),
    )
    if state == "unknown":
        conn.execute(
            "UPDATE runtime_checkpoints SET state='unknown',updated_at_ms=? "
            "WHERE checkpoint_id=(SELECT checkpoint_id FROM control_command_context "
            "WHERE command_id=?) AND state<>'released'",
            (at, cmd["command_id"]),
        )
    audit(
        conn,
        cmd["run_id"],
        "command.updated",
        cmd["command_id"],
        {"command_id": cmd["command_id"], "state": state},
        at,
    )


def invalidate(conn: sqlite3.Connection, sid: str, at: int, state: str) -> None:
    session = row(conn, "SELECT * FROM runtime_sessions WHERE runtime_session_id=?", (sid,))
    if session["state"] != "connected":
        return
    conn.execute("UPDATE runtime_sessions SET state=? WHERE runtime_session_id=?", (state, sid))
    conn.execute(
        "UPDATE runtime_checkpoints SET state='unknown',updated_at_ms=? "
        "WHERE runtime_session_id=? AND state IN ('available','parked')",
        (at, sid),
    )
    for cmd in conn.execute(
        "SELECT * FROM control_commands WHERE runtime_session_id=? "
        "AND state IN ('queued','dispatched')",
        (sid,),
    ).fetchall():
        finish_command(
            conn, dict(cmd), "unknown" if cmd["state"] == "dispatched" else "timed_out", at
        )
    audit(
        conn,
        session["run_id"],
        "runtime.disconnected",
        sid,
        {"runtime_session_id": sid, "state": state},
        at,
    )


def maintain(conn: sqlite3.Connection, config: Settings, at: int, *, restart: bool = False) -> None:
    for session in conn.execute(
        "SELECT s.*,k.expires_at_ms FROM runtime_sessions s JOIN runtime_credentials k "
        "ON k.runtime_session_id=s.runtime_session_id JOIN workflow_runs r ON r.run_id=s.run_id "
        "WHERE r.project_id=? AND s.state='connected'",
        (config.project_id,),
    ).fetchall():
        if (
            restart
            or at >= session["expires_at_ms"]
            or at - session["last_heartbeat_ms"] >= config.runtime_heartbeat_timeout_ms
        ):
            invalidate(
                conn, session["runtime_session_id"], at, "disconnected" if restart else "expired"
            )
    for cmd in conn.execute(
        "SELECT c.* FROM control_commands c JOIN workflow_runs r ON r.run_id=c.run_id "
        "WHERE r.project_id=? AND c.state IN ('queued','dispatched') AND c.created_at_ms<=?",
        (config.project_id, at - config.command_timeout_ms),
    ).fetchall():
        finish_command(
            conn, dict(cmd), "unknown" if cmd["state"] == "dispatched" else "timed_out", at
        )


def live(conn: sqlite3.Connection, config: Settings, sid: str, at: int) -> dict[str, Any]:
    result = row(
        conn,
        "SELECT s.*,k.expires_at_ms FROM runtime_sessions s JOIN runtime_credentials k "
        "ON k.runtime_session_id=s.runtime_session_id JOIN workflow_runs r ON r.run_id=s.run_id "
        "WHERE s.runtime_session_id=? AND r.project_id=?",
        (sid, config.project_id),
    )
    epoch = conn.execute(
        "SELECT MAX(fencing_epoch) FROM runtime_sessions WHERE run_id=? AND runtime_key=?",
        (result["run_id"], result["runtime_key"]),
    ).fetchone()[0]
    if (
        result["state"] != "connected"
        or result["fencing_epoch"] != epoch
        or at >= result["expires_at_ms"]
        or at - result["last_heartbeat_ms"] >= config.runtime_heartbeat_timeout_ms
    ):
        raise Problem(409, "stale_session", "Runtime session is disconnected, expired or fenced")
    return result


def boundary(conn: sqlite3.Connection, run_id: str, tid: str, sid: str) -> dict[str, Any]:
    return row(
        conn,
        "SELECT p.* FROM runtime_checkpoints p JOIN runtime_task_owners o "
        "ON o.run_id=p.run_id AND o.task_id=p.task_id "
        "WHERE p.run_id=? AND p.task_id=? AND p.runtime_session_id=? "
        "AND o.runtime_session_id=? AND p.state IN ('available','parked','unknown')",
        (run_id, tid, sid, sid),
    )


def safe_to_release(conn: sqlite3.Connection, run_id: str, tid: str) -> None:
    # Include declared future-dated evidence conservatively; clock skew cannot erase a guard.
    snapshot = Snapshot(conn, run_id, MAX_INT)
    ancestors, pending = {tid}, [tid]
    while pending:
        current = pending.pop()
        for d in snapshot.dependencies:
            if d["blocked_task_id"] == current and d["prerequisite_task_id"] not in ancestors:
                ancestors.add(d["prerequisite_task_id"])
                pending.append(d["prerequisite_task_id"])
    if any(snapshot.tasks[t]["state"] != "completed" for t in ancestors - {tid}):
        raise Problem(409, "unresolved_dependency", "Declared prerequisites are not completed")
    for approval in conn.execute("SELECT * FROM approvals WHERE run_id=?", (run_id,)):
        linked = (
            approval["related_task_id"] in ancestors
            or conn.execute(
                "SELECT 1 FROM approval_requests WHERE approval_id=? AND requester_task_id IN ("
                + ",".join("?" for _ in ancestors)
                + ")",
                (approval["approval_id"], *sorted(ancestors)),
            ).fetchone()
        )
        if linked and (
            approval["state"] != "approved" or not approval["verified_resolution_source"]
        ):
            raise Problem(
                409, "approval_unresolved", "Required approval is pending, denied or unverified"
            )
    placeholders = ",".join("?" for _ in ancestors)
    intents = conn.execute(
        "SELECT * FROM payment_intents WHERE run_id=? AND task_id IN (" + placeholders + ")",
        (run_id, *sorted(ancestors)),
    ).fetchall()
    if any(payment_guard(conn, dict(intent)) for intent in intents):
        raise Problem(
            409,
            "payment_boundary",
            "Payment authorization or outcome requires external reconciliation",
        )


def availability(
    conn: sqlite3.Connection, config: Settings, run_id: str, tid: str, at: int
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "hold_task": False,
        "resume_task": False,
        "reason": "no_active_boundary",
    }
    try:
        run = row(
            conn,
            "SELECT mode FROM workflow_runs WHERE run_id=? AND project_id=?",
            (run_id, config.project_id),
        )
        if run["mode"] != "control":
            result["reason"] = "observe_only"
            return result
        task = row(conn, "SELECT * FROM tasks WHERE run_id=? AND task_id=?", (run_id, tid))
        owner = row(
            conn, "SELECT * FROM runtime_task_owners WHERE run_id=? AND task_id=?", (run_id, tid)
        )
        session = live(conn, config, owner["runtime_session_id"], at)
        point = boundary(conn, run_id, tid, session["runtime_session_id"])
        result.update(
            runtime_session_id=session["runtime_session_id"],
            checkpoint_id=point["checkpoint_id"],
            fencing_epoch=session["fencing_epoch"],
            boundary_state=point["state"],
        )
        if conn.execute(
            "SELECT 1 FROM control_commands WHERE task_id=? "
            "AND state IN ('queued','dispatched','unknown')",
            (tid,),
        ).fetchone():
            result["reason"] = "pending_or_uncertain_command"
            return result
        caps = json.loads(session["capabilities_json"])
        result["hold_task"] = (
            point["state"] == "available" and task["state"] not in TERMINAL and "hold_task" in caps
        )
        if point["state"] == "parked" and task["state"] == "held" and "resume_task" in caps:
            safe_to_release(conn, run_id, tid)
            result["resume_task"] = True
        result["reason"] = (
            "eligible_at_current_boundary"
            if result["hold_task"] or result["resume_task"]
            else "unsupported_boundary"
        )
    except Problem as exc:
        result["reason"] = exc.code
    return result


class ControlService:
    def __init__(self, db: Database, config: Settings, clock: Callable[[], int] = now_ms) -> None:
        self.db, self.config, self.clock = db, config, clock
        self.stopping = Event()
        self.thread: Thread | None = None
        self.healthy = True
        db.write(lambda conn: maintain(conn, config, clock(), restart=True))

    def write(self, fn: Callable[[sqlite3.Connection, int], T]) -> T:
        at = self.clock()
        self.db.write(lambda conn: maintain(conn, self.config, at))
        return self.db.write(lambda conn: fn(conn, at))

    def authenticate(self, token: str) -> str:
        self.db.write(lambda conn: maintain(conn, self.config, self.clock()))
        with self.db.read() as conn:
            found = conn.execute(
                "SELECT runtime_session_id FROM runtime_credentials WHERE token_sha256=?",
                (sha(token),),
            ).fetchone()
            if not found:
                raise Problem(401, "unauthorized", "A valid runtime session credential is required")
            live(conn, self.config, found[0], self.clock())
            return str(found[0])

    def register(self, run_id: str, body: Registration) -> dict[str, Any]:
        def apply(conn: sqlite3.Connection, at: int) -> dict[str, Any]:
            run = row(
                conn,
                "SELECT * FROM workflow_runs WHERE run_id=? AND project_id=?",
                (run_id, self.config.project_id),
            )
            if run["mode"] != "control":
                raise Problem(409, "observe_only", "Runtime control requires a Control run")
            if len(set(body.capabilities)) != len(body.capabilities):
                raise Problem(422, "invalid_capabilities", "Capabilities must be unique")
            nonce = sha(body.client_nonce)
            old = conn.execute(
                "SELECT * FROM runtime_credentials WHERE run_id=? AND runtime_key=? "
                "AND nonce_sha256=?",
                (run_id, body.runtime_key, nonce),
            ).fetchone()
            if old:
                session = live(conn, self.config, old["runtime_session_id"], at)
                if sorted(json.loads(session["capabilities_json"])) != sorted(body.capabilities):
                    raise Problem(409, "registration_conflict", "Nonce replay changed capabilities")
                sid = session["runtime_session_id"]
                epoch, expires = session["fencing_epoch"], old["expires_at_ms"]
            else:
                existing = conn.execute(
                    "SELECT * FROM runtime_sessions WHERE run_id=? AND runtime_key=?",
                    (run_id, body.runtime_key),
                ).fetchall()
                epoch = max((s["fencing_epoch"] for s in existing), default=0) + 1
                for s in existing:
                    invalidate(conn, s["runtime_session_id"], at, "disconnected")
                sid, expires = str(uuid4()), at + self.config.runtime_token_ttl_ms
                conn.execute(
                    "INSERT INTO runtime_sessions(runtime_session_id,run_id,runtime_key,"
                    "actor_subject,"
                    "capabilities_json,fencing_epoch,connected_at_ms,last_heartbeat_ms) "
                    "VALUES (?,?,?,'local-sdk-host',?,?,?,?)",
                    (sid, run_id, body.runtime_key, dump(sorted(body.capabilities)), epoch, at, at),
                )
            token = (
                "sc_rt_"
                + hmac.new(
                    self.config.sdk_token.encode(),
                    f"runtime-v1:{sid}:{body.client_nonce}".encode(),
                    hashlib.sha256,
                ).hexdigest()
            )
            if not old:
                conn.execute(
                    "INSERT INTO runtime_credentials VALUES (?,?,?,?,?,?)",
                    (sid, run_id, body.runtime_key, nonce, sha(token), expires),
                )
                audit(
                    conn,
                    run_id,
                    "runtime.registered",
                    sid,
                    {
                        "runtime_session_id": sid,
                        "fencing_epoch": epoch,
                        "capabilities": sorted(body.capabilities),
                    },
                    at,
                    runtime=True,
                )
            return {
                "runtime_session_id": sid,
                "fencing_epoch": epoch,
                "session_token": token,
                "expires_at_ms": expires,
            }

        return self.write(apply)

    def heartbeat(self, sid: str) -> dict[str, Any]:
        def apply(conn: sqlite3.Connection, at: int) -> dict[str, Any]:
            session = live(conn, self.config, sid, at)
            conn.execute(
                "UPDATE runtime_sessions SET last_heartbeat_ms=? WHERE runtime_session_id=?",
                (at, sid),
            )
            return {"alive": True, "fencing_epoch": session["fencing_epoch"]}

        return self.write(apply)

    def enter(self, sid: str, body: CheckpointEnter) -> dict[str, Any]:
        def apply(conn: sqlite3.Connection, at: int) -> dict[str, Any]:
            session = live(conn, self.config, sid, at)
            tid, run_id = str(body.task_id), session["run_id"]
            task = row(conn, "SELECT * FROM tasks WHERE run_id=? AND task_id=?", (run_id, tid))
            old = conn.execute(
                "SELECT * FROM runtime_checkpoints WHERE runtime_session_id=? AND checkpoint_key=?",
                (sid, body.checkpoint_key),
            ).fetchone()
            if old:
                if old["task_id"] != tid or old["label"] != body.label:
                    raise Problem(409, "checkpoint_conflict", "Checkpoint key changed its target")
                return dict(old)
            if task["state"] in TERMINAL or task["state"] == "held":
                raise Problem(409, "invalid_task_state", "Task cannot enter a new checkpoint")
            active = conn.execute(
                "SELECT 1 FROM runtime_checkpoints WHERE task_id=? AND state<>'released'", (tid,)
            ).fetchone()
            if active:
                raise Problem(
                    409, "boundary_unresolved", "An existing boundary must be reconciled first"
                )
            owner = conn.execute(
                "SELECT * FROM runtime_task_owners WHERE run_id=? AND task_id=?", (run_id, tid)
            ).fetchone()
            if owner and owner["runtime_session_id"] != sid:
                old_session = row(
                    conn,
                    "SELECT * FROM runtime_sessions WHERE runtime_session_id=?",
                    (owner["runtime_session_id"],),
                )
                if old_session["state"] == "connected":
                    raise Problem(409, "task_owned", "Another live runtime owns this task")
            conn.execute(
                "INSERT INTO runtime_task_owners VALUES (?,?,?) ON CONFLICT(run_id,task_id) "
                "DO UPDATE SET runtime_session_id=excluded.runtime_session_id",
                (run_id, tid, sid),
            )
            generation = conn.execute(
                "SELECT COALESCE(MAX(generation),0)+1 FROM runtime_checkpoints WHERE task_id=?",
                (tid,),
            ).fetchone()[0]
            cid = str(uuid4())
            conn.execute(
                "INSERT INTO runtime_checkpoints VALUES (?,?,?,?,?,?,1,'available',?,?,?,?)",
                (
                    cid,
                    run_id,
                    tid,
                    sid,
                    body.checkpoint_key,
                    body.label,
                    generation,
                    task["state"],
                    at,
                    at,
                ),
            )
            audit(
                conn,
                run_id,
                "runtime.checkpoint_seen",
                cid,
                {
                    "checkpoint_id": cid,
                    "task_id": tid,
                    "runtime_session_id": sid,
                    "generation": generation,
                },
                at,
                runtime=True,
            )
            return row(conn, "SELECT * FROM runtime_checkpoints WHERE checkpoint_id=?", (cid,))

        return self.write(apply)

    def leave(self, sid: str, checkpoint_id: str) -> dict[str, Any]:
        def apply(conn: sqlite3.Connection, at: int) -> dict[str, Any]:
            session = live(conn, self.config, sid, at)
            point = row(
                conn,
                "SELECT * FROM runtime_checkpoints WHERE checkpoint_id=? AND runtime_session_id=?",
                (checkpoint_id, sid),
            )
            if point["state"] == "released":
                return point
            if point["state"] != "available":
                raise Problem(
                    409, "boundary_not_released", "Task is held or its boundary outcome is unknown"
                )
            if conn.execute(
                "SELECT 1 FROM control_commands WHERE task_id=? "
                "AND state IN ('queued','dispatched','unknown')",
                (point["task_id"],),
            ).fetchone():
                raise Problem(
                    409, "pending_control", "A pending or uncertain command prevents release"
                )
            safe_to_release(conn, session["run_id"], point["task_id"])
            conn.execute(
                "UPDATE runtime_checkpoints SET state='released',updated_at_ms=? "
                "WHERE checkpoint_id=?",
                (at, checkpoint_id),
            )
            audit(
                conn,
                session["run_id"],
                "runtime.checkpoint_released",
                checkpoint_id,
                {"checkpoint_id": checkpoint_id, "task_id": point["task_id"]},
                at,
                runtime=True,
            )
            return {**point, "state": "released", "updated_at_ms": at}

        return self.write(apply)

    def enqueue(
        self, run_id: str, body: CommandRequest, key: str, *, initiated_by: str = "operator"
    ) -> dict[str, Any]:
        return self.write(lambda conn, at: self._enqueue(conn, run_id, body, key, at, initiated_by))

    def _enqueue(
        self,
        conn: sqlite3.Connection,
        run_id: str,
        body: CommandRequest,
        key: str,
        at: int,
        initiated_by: str,
    ) -> dict[str, Any]:
        digest = sha(dump({**body.model_dump(mode="json"), "initiated_by": initiated_by}))
        previous = conn.execute(
            "SELECT c.command_id,x.request_sha256 FROM control_commands c "
            "JOIN control_command_context x ON x.command_id=c.command_id "
            "WHERE c.run_id=? AND c.idempotency_key=?",
            (run_id, key),
        ).fetchone()
        if previous:
            if previous["request_sha256"] != digest:
                raise Problem(
                    409, "idempotency_conflict", "Command key was reused with different fields"
                )
            return command(conn, self.config.project_id, previous["command_id"])
        run = row(
            conn,
            "SELECT * FROM workflow_runs WHERE run_id=? AND project_id=?",
            (run_id, self.config.project_id),
        )
        if run["mode"] != "control":
            raise Problem(409, "observe_only", "Observe runs cannot be controlled")
        sid, tid = str(body.runtime_session_id), str(body.task_id)
        session = live(conn, self.config, sid, at)
        if session["run_id"] != run_id or body.command_kind not in json.loads(
            session["capabilities_json"]
        ):
            raise Problem(409, "unsupported_control", "Runtime does not support this target/action")
        task = row(conn, "SELECT * FROM tasks WHERE run_id=? AND task_id=?", (run_id, tid))
        if task["state_version"] != body.expected_task_version:
            raise Problem(
                409, "stale_version", "Task version changed; refresh before requesting control"
            )
        point = boundary(conn, run_id, tid, sid)
        required = "available" if body.command_kind == "hold_task" else "parked"
        if point["state"] != required or task["state"] in TERMINAL:
            raise Problem(409, "invalid_boundary", "The runtime is not at an eligible boundary")
        if body.command_kind == "resume_task":
            if task["state"] != "held":
                raise Problem(409, "not_held", "Resume requires a confirmed runtime hold")
            safe_to_release(conn, run_id, tid)
        if body.incident_id:
            row(
                conn,
                "SELECT 1 FROM incidents WHERE run_id=? AND incident_id=?",
                (run_id, str(body.incident_id)),
            )
        if body.approval_id:
            row(
                conn,
                "SELECT 1 FROM approvals WHERE run_id=? AND approval_id=?",
                (run_id, str(body.approval_id)),
            )
        if conn.execute(
            "SELECT 1 FROM control_commands WHERE task_id=? "
            "AND state IN ('queued','dispatched','unknown')",
            (tid,),
        ).fetchone():
            raise Problem(
                409, "pending_control", "A pending or uncertain command already targets this task"
            )
        cid = str(uuid4())
        conn.execute(
            "INSERT INTO control_commands(command_id,run_id,runtime_session_id,incident_id,"
            "task_id,approval_id,"
            "command_kind,idempotency_key,required_capability,expected_task_version,"
            "session_fencing_epoch,"
            "initiated_by,request_reason,created_at_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                cid,
                run_id,
                sid,
                str(body.incident_id) if body.incident_id else None,
                tid,
                str(body.approval_id) if body.approval_id else None,
                body.command_kind,
                key,
                body.command_kind,
                body.expected_task_version,
                session["fencing_epoch"],
                initiated_by,
                body.reason,
                at,
            ),
        )
        conn.execute(
            "INSERT INTO control_command_context VALUES (?,?,?,?,?)",
            (cid, run_id, point["checkpoint_id"], digest, task["state"]),
        )
        audit(
            conn,
            run_id,
            "command.queued",
            cid,
            {"command_id": cid, "task_id": tid, "initiated_by": initiated_by},
            at,
        )
        return command(conn, self.config.project_id, cid)

    def poll(self, sid: str) -> dict[str, Any]:
        def apply(conn: sqlite3.Connection, at: int) -> dict[str, Any]:
            session = live(conn, self.config, sid, at)
            result = []
            for record in conn.execute(
                "SELECT * FROM control_commands WHERE runtime_session_id=? "
                "AND state IN ('queued','dispatched') ORDER BY created_at_ms,command_id LIMIT 100",
                (sid,),
            ).fetchall():
                cmd = dict(record)
                if cmd["state"] == "queued":
                    task = row(conn, "SELECT * FROM tasks WHERE task_id=?", (cmd["task_id"],))
                    if (
                        task["state_version"] != cmd["expected_task_version"]
                        or cmd["session_fencing_epoch"] != session["fencing_epoch"]
                    ):
                        finish_command(conn, cmd, "rejected", at)
                        continue
                    try:
                        point = boundary(conn, cmd["run_id"], cmd["task_id"], sid)
                        context = row(
                            conn,
                            "SELECT checkpoint_id FROM control_command_context WHERE command_id=?",
                            (cmd["command_id"],),
                        )
                        expected_point = (
                            "available" if cmd["command_kind"] == "hold_task" else "parked"
                        )
                        if (
                            point["checkpoint_id"] != context["checkpoint_id"]
                            or point["state"] != expected_point
                            or cmd["required_capability"]
                            not in json.loads(session["capabilities_json"])
                            or task["state"] in TERMINAL
                            or (cmd["command_kind"] == "resume_task" and task["state"] != "held")
                        ):
                            raise Problem(409, "stale_boundary", "Dispatch boundary changed")
                        if cmd["command_kind"] == "resume_task":
                            safe_to_release(conn, cmd["run_id"], cmd["task_id"])
                    except Problem:
                        finish_command(conn, cmd, "rejected", at)
                        continue
                    conn.execute(
                        "UPDATE control_commands SET state='dispatched',dispatched_at_ms=? "
                        "WHERE command_id=?",
                        (at, cmd["command_id"]),
                    )
                    audit(
                        conn,
                        cmd["run_id"],
                        "command.dispatched",
                        cmd["command_id"],
                        {"command_id": cmd["command_id"]},
                        at,
                    )
                result.append(command(conn, self.config.project_id, cmd["command_id"]))
            return {"commands": result}

        return self.write(apply)

    def ack(self, sid: str, cid: str, body: Ack) -> dict[str, Any]:
        def apply(conn: sqlite3.Connection, at: int) -> dict[str, Any]:
            session = live(conn, self.config, sid, at)
            cmd = command(conn, self.config.project_id, cid)
            if (
                str(body.runtime_session_id) != sid
                or cmd["runtime_session_id"] != sid
                or body.fencing_epoch != session["fencing_epoch"]
                or cmd["session_fencing_epoch"] != session["fencing_epoch"]
            ):
                raise Problem(
                    409, "stale_ack", "ACK does not match the current runtime/session epoch"
                )
            digest = sha(dump(body.model_dump(mode="json")))
            old = conn.execute(
                "SELECT * FROM control_acknowledgements WHERE runtime_session_id=? AND ack_key=?",
                (sid, body.ack_key),
            ).fetchone()
            if old:
                detail = json.loads(old["result_detail"])
                if old["command_id"] != cid or detail["request_sha256"] != digest:
                    raise Problem(409, "ack_conflict", "ACK key replay changed its payload")
                return cmd
            if cmd["state"] != "dispatched":
                raise Problem(
                    409, "invalid_command_state", "ACK requires a currently dispatched command"
                )
            if cmd["required_capability"] not in json.loads(session["capabilities_json"]):
                raise Problem(409, "unsupported_control", "Runtime lacks the required capability")
            task = row(
                conn,
                "SELECT * FROM tasks WHERE run_id=? AND task_id=?",
                (cmd["run_id"], cmd["task_id"]),
            )
            point = boundary(conn, cmd["run_id"], cmd["task_id"], sid)
            if (
                point["checkpoint_id"] != cmd["checkpoint_id"]
                or task["state_version"] != cmd["expected_task_version"]
            ):
                raise Problem(
                    409, "stale_boundary", "Task or checkpoint changed after command dispatch"
                )
            state = "rejected" if body.result == "rejected" else "unknown"
            target = task["state"]
            if body.result == "applied":
                if cmd["command_kind"] == "hold_task" and point["state"] == "available":
                    target = "held"
                elif (
                    cmd["command_kind"] == "resume_task"
                    and point["state"] == "parked"
                    and task["state"] == "held"
                ):
                    safe_to_release(conn, cmd["run_id"], cmd["task_id"])
                    target = point["saved_task_state"]
                else:
                    raise Problem(
                        409, "invalid_boundary", "Runtime ACK is not valid at this boundary"
                    )
                state = "applied"
            conn.execute(
                "INSERT INTO control_acknowledgements VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    str(uuid4()),
                    cmd["run_id"],
                    cid,
                    sid,
                    body.fencing_epoch,
                    body.ack_key,
                    body.result,
                    dump({"code": "runtime_reported", "request_sha256": digest}),
                    at,
                ),
            )
            finish_command(conn, cmd, state, at)
            if state == "applied":
                conn.execute(
                    "UPDATE tasks SET state=?,state_version=state_version+1,updated_at_ms=? "
                    "WHERE task_id=?",
                    (target, at, cmd["task_id"]),
                )
                conn.execute(
                    "UPDATE runtime_checkpoints SET state=?,updated_at_ms=? WHERE checkpoint_id=?",
                    ("parked" if target == "held" else "available", at, point["checkpoint_id"]),
                )
                refresh_run(conn, cmd["run_id"], at)
            audit(
                conn,
                cmd["run_id"],
                "runtime.command_ack",
                cid,
                {
                    "command_id": cid,
                    "runtime_session_id": sid,
                    "fencing_epoch": body.fencing_epoch,
                    "result": body.result,
                    "state": state,
                },
                at,
                runtime=True,
            )
            return command(conn, self.config.project_id, cid)

        return self.write(apply)

    def start(self) -> None:
        def loop() -> None:
            while not self.stopping.wait(0.5):
                try:
                    self.db.write(lambda conn: maintain(conn, self.config, self.clock()))
                    self.healthy = True
                except Exception:
                    self.healthy = False
                    # Do not log exception text, SQL parameters or caller-provided metadata.
                    logger.error("Control maintenance failed; readiness is degraded")

        self.thread = Thread(target=loop, name="swarm-control-maintenance", daemon=True)
        self.thread.start()

    def backpressure(self, run_id: str, body: Backpressure, key: str) -> dict[str, Any]:
        def apply(conn: sqlite3.Connection, at: int) -> dict[str, Any]:
            run = row(
                conn,
                "SELECT * FROM workflow_runs WHERE run_id=? AND project_id=?",
                (run_id, self.config.project_id),
            )
            if run["mode"] != "control":
                raise Problem(409, "observe_only", "Backpressure requires explicit Control mode")
            digest = sha(dump(body.model_dump(mode="json", exclude_none=True)))
            previous = conn.execute(
                "SELECT * FROM control_policy_requests WHERE run_id=? AND idempotency_key=?",
                (run_id, key),
            ).fetchone()
            if previous and body.apply:
                if previous["request_sha256"] != digest:
                    raise Problem(409, "idempotency_conflict", "Policy key changed its request")
                saved = json.loads(previous["result_json"])
                saved["commands"] = [
                    command(conn, self.config.project_id, cid) for cid in saved["command_ids"]
                ]
                return saved
            gate = row(
                conn,
                "SELECT * FROM approvals WHERE run_id=? AND approval_id=?",
                (run_id, str(body.approval_id)),
            )
            if gate["state"] != "pending" or not gate["related_task_id"]:
                raise Problem(
                    409, "no_pending_gate", "Policy needs one explicit pending approval root"
                )
            snapshot = Snapshot(conn, run_id, MAX_INT)
            closure = reverse_closure({gate["related_task_id"]}, snapshot.dependencies)
            targets, skipped = [], []
            for tid in sorted(closure):
                try:
                    task = snapshot.tasks[tid]
                    owner = row(
                        conn,
                        "SELECT runtime_session_id FROM runtime_task_owners WHERE"
                        " run_id=? AND task_id=?",
                        (run_id, tid),
                    )
                    sid = owner["runtime_session_id"]
                    session = live(conn, self.config, sid, at)
                    point = boundary(conn, run_id, tid, sid)
                    if (
                        point["state"] != "available"
                        or task["state"] in TERMINAL
                        or "hold_task" not in json.loads(session["capabilities_json"])
                    ):
                        raise Problem(409, "unsupported_boundary", "No available hold boundary")
                    targets.append(
                        {
                            "task_id": tid,
                            "runtime_session_id": sid,
                            "expected_task_version": task["state_version"],
                            "checkpoint_id": point["checkpoint_id"],
                            "fencing_epoch": session["fencing_epoch"],
                        }
                    )
                except Problem as exc:
                    skipped.append({"task_id": tid, "reason": exc.code})
            if len(targets) > self.config.backpressure_limit:
                raise Problem(
                    409, "policy_bound_exceeded", "Policy target count exceeds configured bound"
                )
            result: dict[str, Any] = {
                "approval_id": str(body.approval_id),
                "root_task_id": gate["related_task_id"],
                "dependent_task_ids": sorted(closure),
                "targets": targets,
                "skipped": skipped,
                "applied": False,
                "commands": [],
                "command_ids": [],
                "policy": "causal-backpressure-v1",
                "auto_apply": False,
                "max_targets": self.config.backpressure_limit,
            }
            result["preview_sha256"] = sha(
                dump(
                    {
                        k: result[k]
                        for k in (
                            "approval_id",
                            "root_task_id",
                            "dependent_task_ids",
                            "targets",
                            "skipped",
                            "policy",
                            "max_targets",
                        )
                    }
                )
            )
            if (
                body.apply
                and body.expected_preview_sha256 is not None
                and body.expected_preview_sha256 != result["preview_sha256"]
            ):
                raise Problem(
                    409,
                    "stale_policy_preview",
                    "Runtime boundaries or dependency scope changed; review a fresh preview",
                )
            if body.apply:
                for target in targets:
                    request = CommandRequest(
                        command_kind="hold_task",
                        approval_id=body.approval_id,
                        reason=body.reason,
                        task_id=target["task_id"],
                        runtime_session_id=target["runtime_session_id"],
                        expected_task_version=target["expected_task_version"],
                    )
                    cmd = self._enqueue(
                        conn, run_id, request, sha(f"{key}:{target['task_id']}"), at, "policy"
                    )
                    result["commands"].append(cmd)
                    result["command_ids"].append(cmd["command_id"])
                # Queued requests are explicitly not runtime effects.
                request_id = str(uuid4())
                result["policy_request_id"] = request_id
                conn.execute(
                    "INSERT INTO control_policy_requests VALUES (?,?,?,?,?,?)",
                    (request_id, run_id, key, digest, dump(result), at),
                )
                audit(
                    conn,
                    run_id,
                    "policy.backpressure_requested",
                    request_id,
                    {
                        "approval_id": str(body.approval_id),
                        "command_ids": result["command_ids"],
                        "initiated_by": "operator",
                        "max_targets": self.config.backpressure_limit,
                    },
                    at,
                )
            return result

        return self.write(apply)

    def present(self, sid: str, event_id: str) -> dict[str, Any]:
        def apply(conn: sqlite3.Connection, at: int) -> dict[str, Any]:
            session = live(conn, self.config, sid, at)
            event = row(
                conn,
                "SELECT e.*,a.state AS approval_state FROM run_events e "
                "JOIN approvals a ON a.run_id=e.run_id AND a.approval_id=e.approval_id "
                "WHERE e.run_id=? AND e.event_id=? AND e.event_kind='approval.requested' "
                "AND e.trust_class='sdk_observation'",
                (session["run_id"], event_id),
            )
            if event["approval_state"] != "pending":
                raise Problem(
                    409,
                    "approval_not_pending",
                    "Only pending requests can enter a presentation boundary",
                )
            old = conn.execute(
                "SELECT * FROM runtime_approval_presentations WHERE run_id=? AND approval_id=?",
                (session["run_id"], event["approval_id"]),
            ).fetchone()
            if old:
                if old["origin_event_id"] != event_id:
                    conn.execute(
                        "UPDATE approval_requests SET disposition='coalesced' "
                        "WHERE run_id=? AND request_key=?",
                        (session["run_id"], event["source_event_key"]),
                    )
                return {
                    "presentation_id": old["presentation_id"],
                    "approval_id": event["approval_id"],
                    "should_present": old["origin_event_id"] == event_id
                    and old["state"] == "claimed"
                    and old["runtime_session_id"] == sid,
                    "state": old["state"],
                }
            pid = str(uuid4())
            conn.execute(
                "INSERT INTO runtime_approval_presentations VALUES (?,?,?,?,?,'claimed',?,?)",
                (pid, session["run_id"], event["approval_id"], sid, event_id, at, at),
            )
            audit(
                conn,
                session["run_id"],
                "runtime.approval_presentation_claimed",
                pid,
                {"presentation_id": pid, "approval_id": event["approval_id"]},
                at,
                runtime=True,
            )
            return {
                "presentation_id": pid,
                "approval_id": event["approval_id"],
                "should_present": True,
                "state": "claimed",
            }

        return self.write(apply)

    def finish_presentation(self, sid: str, pid: str, state: str) -> dict[str, Any]:
        def apply(conn: sqlite3.Connection, at: int) -> dict[str, Any]:
            session = live(conn, self.config, sid, at)
            item = row(
                conn,
                "SELECT * FROM runtime_approval_presentations WHERE presentation_id=? "
                "AND runtime_session_id=? AND run_id=?",
                (pid, sid, session["run_id"]),
            )
            if item["state"] != "claimed" and item["state"] != state:
                raise Problem(
                    409, "presentation_conflict", "An uncertain presentation must not be retried"
                )
            if item["state"] == "claimed":
                conn.execute(
                    "UPDATE runtime_approval_presentations SET state=?,updated_at_ms=? "
                    "WHERE presentation_id=?",
                    (state, at, pid),
                )
                audit(
                    conn,
                    session["run_id"],
                    "runtime.approval_presentation_reported",
                    pid,
                    {"presentation_id": pid, "state": state, "approval_id": item["approval_id"]},
                    at,
                    runtime=True,
                )
            return {"presentation_id": pid, "state": state, "approval_id": item["approval_id"]}

        return self.write(apply)

    def stop(self) -> None:
        self.stopping.set()
        if self.thread:
            self.thread.join()
