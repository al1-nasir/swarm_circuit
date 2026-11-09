"""Managed fixture workers; protocol facts and useful outputs remain separate."""

import hashlib
import json
import secrets
import sqlite3
import threading
from dataclasses import replace
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import uuid4

from swarmcircuit_server.config import Settings
from swarmcircuit_server.controller.service import invalidate
from swarmcircuit_server.db.store import Database, now_ms
from swarmcircuit_server.demo.agents import (
    CALL_LIMIT,
    LiveConfig,
    LiveFailure,
    Reply,
    call_model,
    request_body,
    sha,
)
from swarmcircuit_server.errors import Problem
from swarmcircuit_server.ingest.events import outbox
from swarmcircuit_server.payments.models import ApprovalCallback
from swarmcircuit_server.payments.service import callback

ACTIVE = ("starting", "waiting", "running")
TITLE = "Sales brief · guided local workflow"
DURATION_MS = 600_000
ROLES = ("plan", "public", "access", "analysis", "validation", "brief")


def require(conn: sqlite3.Connection, project_id: str, demo_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM guided_demo_sessions WHERE demo_id=? AND project_id=?",
        (demo_id, project_id),
    ).fetchone()
    if row is None:
        raise Problem(404, "not_found", "Guided workflow not found in this project")
    return dict(row)


def note(conn: sqlite3.Connection, demo_id: str, kind: str, message: str) -> None:
    at = now_ms()
    conn.execute(
        "INSERT INTO guided_demo_actions(demo_id,at_ms,kind,message) VALUES (?,?,?,?)",
        (demo_id, at, kind, message),
    )
    conn.execute("UPDATE guided_demo_sessions SET updated_at_ms=? WHERE demo_id=?", (at, demo_id))
    run = conn.execute(
        "SELECT run_id FROM guided_demo_sessions WHERE demo_id=?", (demo_id,)
    ).fetchone()
    if run and run[0]:
        outbox(conn, run[0], "guided_demo.updated", demo_id)


def artifact(conn: sqlite3.Connection, demo_id: str, slug: str, title: str, content: str) -> None:
    conn.execute(
        "INSERT INTO guided_demo_artifacts VALUES (?,?,?,'text/markdown',?,?,?)",
        (demo_id, slug, title, content, hashlib.sha256(content.encode()).hexdigest(), now_ms()),
    )


class DemoManager:
    def __init__(self, db: Database, settings: Settings, origin: str) -> None:
        url = urlparse(origin)
        if (
            url.scheme != "http"
            or url.hostname not in {"127.0.0.1", "::1", "localhost"}
            or url.username
            or url.password
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
        ):
            raise ValueError(
                "Guided workflow endpoint must be an explicitly configured loopback origin"
            )
        self.db, self.settings, self.origin = db, settings, origin.rstrip("/")
        # This config is used only after a dedicated owned-demo lookup. It does not
        # enable the general mock-broker HTTP routes or grant authority over other runs.
        self.authority = replace(
            settings, mock_broker_enabled=True, mock_broker_token=secrets.token_urlsafe(32)
        )
        self.lock = threading.RLock()
        self.workers: dict[str, tuple[threading.Thread, threading.Event]] = {}
        self.live_configs: dict[str, LiveConfig] = {}
        self.model_transport: Any = None
        self.closed = False

    def start(self) -> None:
        def recover(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE guided_demo_model_calls SET state='unknown',error_code='interrupted',"
                "completed_at_ms=? WHERE state='started' AND demo_id IN "
                "(SELECT demo_id FROM guided_demo_sessions WHERE project_id=?)",
                (now_ms(), self.settings.project_id),
            )
            for row in conn.execute(
                "SELECT demo_id FROM guided_demo_sessions WHERE project_id=? "
                "AND state IN ('starting','waiting','running')",
                (self.settings.project_id,),
            ).fetchall():
                self._terminal(
                    conn, row[0], "interrupted", "Server restarted; start a fresh workflow."
                )

        self.db.write(recover)

    def close(self) -> None:
        with self.lock:
            self.closed = True
            workers = list(self.workers.values())
            for _, stop in workers:
                stop.set()
            ids = list(self.workers)

        def interrupt(conn: sqlite3.Connection) -> None:
            for demo_id in ids:
                if not conn.execute(
                    "SELECT 1 FROM guided_demo_sessions WHERE demo_id=? AND project_id=?",
                    (demo_id, self.settings.project_id),
                ).fetchone():
                    continue
                self._terminal(
                    conn,
                    demo_id,
                    "interrupted",
                    "The local worker stopped. Existing outputs are retained.",
                )

        self.db.write(interrupt)
        for thread, _ in workers:
            # Provider I/O has a 30-second absolute deadline and observes stop
            # every 50ms. Allow its cancellation and SDK teardown before DB close.
            thread.join(timeout=35)

    def capabilities(self, project_id: str) -> dict[str, Any]:
        if project_id != self.settings.project_id:
            raise Problem(404, "not_found", "Project not found")
        try:
            config = LiveConfig.from_env()
        except LiveFailure:
            config = None
        return {
            "fixture": True,
            "live": {
                "available": config is not None,
                "configured_model": config.model if config else None,
                "provider_host": config.host if config else None,
                "call_limit": CALL_LIMIT,
                "reason": None if config else "Configure the server-side model provider first.",
            },
        }

    def _terminal(self, conn: sqlite3.Connection, demo_id: str, state: str, message: str) -> None:
        demo = require(conn, self.settings.project_id, demo_id)
        if demo["state"] not in ACTIVE:
            return
        at = now_ms()
        conn.execute(
            "UPDATE guided_demo_sessions SET state=?,updated_at_ms=? WHERE demo_id=?",
            (state, at, demo_id),
        )
        if demo["run_id"] and state != "completed":
            # A bounded host has stopped. Never invent completion of unfinished tasks.
            conn.execute(
                "UPDATE workflow_runs SET status=?,ended_at_ms=?,updated_at_ms=? "
                "WHERE run_id=? AND status NOT IN ('completed','failed','cancelled')",
                ("failed" if state == "failed" else "cancelled", at, at, demo["run_id"]),
            )
        note(conn, demo_id, state, message)

    def create(
        self, project_id: str, key: str, mode: Literal["fixture", "live"] = "fixture"
    ) -> dict[str, Any]:
        if project_id != self.settings.project_id:
            raise Problem(404, "not_found", "Project not found")
        with self.lock:
            if self.closed:
                raise Problem(503, "demo_unavailable", "Guided workflow service is stopping")

            payload_sha = sha({"mode": mode})
            live_config: LiveConfig | None = None

            def save(conn: sqlite3.Connection) -> tuple[str, bool]:
                nonlocal live_config
                old = conn.execute(
                    (
                        "SELECT demo_id,execution_mode,start_payload_sha256 "
                        "FROM guided_demo_sessions "
                        "WHERE project_id=? AND idempotency_key=?"
                    ),
                    (project_id, key),
                ).fetchone()
                if old:
                    if old["execution_mode"] != mode or (
                        old["start_payload_sha256"] and old["start_payload_sha256"] != payload_sha
                    ):
                        raise Problem(
                            409, "idempotency_conflict", "Original walkthrough mode differs"
                        )
                    return old[0], False
                if mode == "live":
                    try:
                        live_config = LiveConfig.from_env()
                    except LiveFailure as exc:
                        raise Problem(
                            409, exc.code, "Configure the server-side model provider first"
                        ) from exc
                if conn.execute(
                    "SELECT 1 FROM guided_demo_sessions WHERE project_id=? "
                    "AND state IN ('starting','waiting','running')",
                    (project_id,),
                ).fetchone():
                    raise Problem(
                        409,
                        "demo_already_active",
                        "Open the active guided workflow before starting another.",
                    )
                demo_id, at = str(uuid4()), now_ms()
                conn.execute(
                    "INSERT INTO guided_demo_sessions(demo_id,project_id,idempotency_key,state,"
                    "created_at_ms,updated_at_ms,expires_at_ms,execution_mode,start_payload_sha256,"
                    "model_name,provider_host) VALUES (?,?,?,'starting',?,?,?,?,?,?,?)",
                    (
                        demo_id,
                        project_id,
                        key,
                        at,
                        at,
                        at + DURATION_MS,
                        mode,
                        payload_sha,
                        live_config.model if live_config else "",
                        live_config.host if live_config else "",
                    ),
                )
                note(
                    conn,
                    demo_id,
                    "starting",
                    (
                        "Starting a live writer/reviewer workflow over local sample data. "
                        "At most three model requests; no production tools or permissions."
                        if mode == "live"
                        else "Starting six local Python workers. No model or external tool calls."
                    ),
                )
                return demo_id, True

            demo_id, created = self.db.write(save)
            if created:
                if live_config:
                    self.live_configs[demo_id] = live_config
                stop = threading.Event()
                thread = threading.Thread(
                    target=self._entry, args=(demo_id, stop), daemon=True, name="guided-workflow"
                )
                self.workers[demo_id] = (thread, stop)
                thread.start()
        return self.status(demo_id)

    def list(self, project_id: str, key: str | None = None) -> dict[str, Any]:
        if project_id != self.settings.project_id:
            raise Problem(404, "not_found", "Project not found")
        with self.db.read() as conn:
            ids = [
                r[0]
                for r in conn.execute(
                    "SELECT demo_id FROM guided_demo_sessions WHERE project_id=? "
                    + ("AND idempotency_key=? " if key is not None else "")
                    + "ORDER BY created_at_ms DESC,demo_id DESC LIMIT 20",
                    (project_id, key) if key is not None else (project_id,),
                )
            ]
        return {"items": [self.status(did) for did in ids]}

    def status(self, demo_id: str) -> dict[str, Any]:
        with self.db.read() as conn:
            demo = require(conn, self.settings.project_id, demo_id)
            run_id = demo["run_id"]
            tasks = json.loads(demo["task_ids_json"])
            completed = set()
            request_count = active_holds = waiting_count = 0
            connected = False
            if run_id:
                completed = {
                    r[0]
                    for r in conn.execute(
                        "SELECT task_id FROM tasks WHERE run_id=? AND state='completed'", (run_id,)
                    )
                }
                request_count = conn.execute(
                    "SELECT COUNT(*) FROM approval_requests WHERE run_id=?", (run_id,)
                ).fetchone()[0]
                if demo["permission"] == "pending":
                    protected_ids = {
                        tasks.get(role) for role in ("access", "analysis", "validation", "brief")
                    } - {None}
                    waiting_count = len(protected_ids - completed)
                active_holds = conn.execute(
                    "SELECT COUNT(*) FROM tasks WHERE run_id=? AND state='held'", (run_id,)
                ).fetchone()[0]
                connected = bool(
                    conn.execute(
                        "SELECT 1 FROM runtime_sessions s JOIN runtime_credentials k "
                        "ON k.runtime_session_id=s.runtime_session_id WHERE s.run_id=? "
                        "AND s.state='connected' AND s.last_heartbeat_ms>? AND k.expires_at_ms>? "
                        "AND s.fencing_epoch=(SELECT MAX(s2.fencing_epoch) "
                        "FROM runtime_sessions s2 WHERE s2.run_id=s.run_id "
                        "AND s2.runtime_key=s.runtime_key) LIMIT 1",
                        (
                            run_id,
                            now_ms() - self.settings.runtime_heartbeat_timeout_ms,
                            now_ms(),
                        ),
                    ).fetchone()
                )
            artifacts = [
                dict(r)
                for r in conn.execute(
                    "SELECT slug,title,media_type,sha256,created_at_ms FROM guided_demo_artifacts "
                    "WHERE demo_id=? ORDER BY created_at_ms,slug",
                    (demo_id,),
                )
            ]
            timeline = [
                dict(r)
                for r in conn.execute(
                    "SELECT at_ms,kind,message FROM guided_demo_actions WHERE demo_id=? "
                    "ORDER BY action_id LIMIT 100",
                    (demo_id,),
                )
            ]
            effects = conn.execute(
                "SELECT COUNT(*) FROM guided_demo_effects WHERE demo_id=?", (demo_id,)
            ).fetchone()[0]
            model_calls = [
                dict(r)
                for r in conn.execute(
                    "SELECT phase,state,input_tokens,output_tokens,response_model FROM "
                    "guided_demo_model_calls WHERE demo_id=? ORDER BY call_index",
                    (demo_id,),
                )
            ]
            handoff = conn.execute(
                "SELECT status FROM guided_demo_handoffs WHERE demo_id=?", (demo_id,)
            ).fetchone()
        with self.lock:
            worker = self.workers.get(demo_id)
            alive = bool(worker and worker[0].is_alive())
        return {
            "demo_id": demo_id,
            "run_id": run_id,
            "state": demo["state"],
            "permission": demo["permission"],
            "approval_id": demo["approval_id"],
            "created_at_ms": demo["created_at_ms"],
            "updated_at_ms": demo["updated_at_ms"],
            "expires_at_ms": demo["expires_at_ms"],
            "failure_code": demo["failure_code"],
            "worker_connected": connected and alive and demo["state"] in ACTIVE,
            "progress": {
                "completed": len(completed),
                "total": 6,
                "waiting": waiting_count if demo["state"] in ACTIVE else 0,
            },
            "request_count": request_count,
            "protected_effects": effects,
            "public_completed": tasks.get("public") in completed,
            "active_holds": active_holds,
            "task_ids": tasks,
            "artifacts": artifacts,
            "timeline": timeline,
            "simulation": True,
            "execution_mode": demo["execution_mode"],
            "model_calls": len(model_calls),
            "model": {
                "configured_model": demo["model_name"] or None,
                "provider_host": demo["provider_host"] or None,
                "call_limit": CALL_LIMIT,
                "calls": len(model_calls),
                "input_tokens": sum(c["input_tokens"] for c in model_calls)
                if all(c["input_tokens"] is not None for c in model_calls)
                else None,
                "output_tokens": sum(c["output_tokens"] for c in model_calls)
                if all(c["output_tokens"] is not None for c in model_calls)
                else None,
                "repair_used": any(c["phase"] == "repair" for c in model_calls),
                "review_status": handoff["status"] if handoff else "not_started",
                "provider_reported_model": next(
                    (c["response_model"] for c in reversed(model_calls) if c["response_model"]),
                    None,
                ),
            },
            "title": TITLE,
        }

    def check_live_authority(self, conn: sqlite3.Connection, demo_id: str, task_id: str) -> None:
        demo = require(conn, self.settings.project_id, demo_id)
        if demo["expires_at_ms"] <= now_ms():
            raise LiveFailure("expired")
        approval = conn.execute(
            "SELECT state,verified_resolution_source FROM approvals WHERE approval_id=?",
            (demo["approval_id"],),
        ).fetchone()
        task = conn.execute(
            "SELECT state FROM tasks WHERE task_id=? AND run_id=?", (task_id, demo["run_id"])
        ).fetchone()
        if (
            self.closed
            or demo["state"] not in ACTIVE
            or demo["permission"] != "approved"
            or not approval
            or approval[0] != "approved"
            or not approval[1]
            or not task
            or task[0] != "running"
            or conn.execute(
                "SELECT 1 FROM control_commands WHERE task_id=? "
                "AND state IN ('queued','dispatched','unknown')",
                (task_id,),
            ).fetchone()
            or not conn.execute(
                "SELECT 1 FROM runtime_task_owners o JOIN runtime_sessions s "
                "ON s.runtime_session_id=o.runtime_session_id JOIN runtime_credentials k "
                "ON k.runtime_session_id=s.runtime_session_id WHERE o.run_id=? AND o.task_id=? "
                "AND s.state='connected' AND s.last_heartbeat_ms>? AND k.expires_at_ms>? "
                "AND s.fencing_epoch=(SELECT MAX(s2.fencing_epoch) FROM runtime_sessions s2 "
                "WHERE s2.run_id=s.run_id AND s2.runtime_key=s.runtime_key)",
                (
                    demo["run_id"],
                    task_id,
                    now_ms() - self.settings.runtime_heartbeat_timeout_ms,
                    now_ms(),
                ),
            ).fetchone()
        ):
            raise LiveFailure("interrupted")

    def model_call(
        self,
        demo_id: str,
        task_id: str,
        phase: Literal["writer", "reviewer", "repair"],
        payload: dict[str, Any],
        stop: threading.Event,
    ) -> Reply:
        config = self.live_configs.get(demo_id)
        if config is None:
            raise LiveFailure("live_unconfigured")
        body = request_body(config, phase, payload)

        def attempt(conn: sqlite3.Connection) -> int:
            if stop.is_set():
                raise LiveFailure("interrupted")
            self.check_live_authority(conn, demo_id, task_id)
            index = (
                conn.execute(
                    "SELECT COUNT(*) FROM guided_demo_model_calls WHERE demo_id=?", (demo_id,)
                ).fetchone()[0]
                + 1
            )
            if index > CALL_LIMIT:
                raise LiveFailure("model_budget_exhausted")
            conn.execute(
                "INSERT INTO guided_demo_model_calls(demo_id,call_index,phase,started_at_ms,"
                "state,request_sha256) VALUES (?,?,?,?,'started',?)",
                (demo_id, index, phase, now_ms(), sha(body)),
            )
            note(
                conn,
                demo_id,
                "model." + phase + ".started",
                f"Live {phase} request {index}/3 started.",
            )
            return int(index)

        index = self.db.write(attempt)
        try:
            reply = call_model(config, phase, payload, stop, self.model_transport)
        except LiveFailure as exc:
            code = exc.code
            self.db.write(
                lambda c: c.execute(
                    "UPDATE guided_demo_model_calls SET state=?,error_code=?,completed_at_ms=? "
                    "WHERE demo_id=? AND call_index=? AND state='started'",
                    (
                        "unknown" if code in {"interrupted", "provider_timeout"} else "failed",
                        code,
                        now_ms(),
                        demo_id,
                        index,
                    ),
                )
            )
            raise
        self.db.write(
            lambda c: c.execute(
                "UPDATE guided_demo_model_calls SET state='succeeded',completed_at_ms=?,"
                "input_tokens=?,output_tokens=?,response_sha256=?,response_model=? "
                "WHERE demo_id=? AND call_index=? AND state='started'",
                (
                    now_ms(),
                    reply.input_tokens,
                    reply.output_tokens,
                    reply.response_sha256,
                    reply.response_model,
                    demo_id,
                    index,
                ),
            )
        )
        with self.db.read() as conn:
            if stop.is_set():
                raise LiveFailure("interrupted")
            self.check_live_authority(conn, demo_id, task_id)
        return reply

    def decision(
        self, demo_id: str, decision: Literal["approved", "denied"], reason: str, key: str
    ) -> dict[str, Any]:
        payload_sha = hashlib.sha256(
            json.dumps({"decision": decision, "reason": reason}, sort_keys=True).encode()
        ).hexdigest()

        def save(conn: sqlite3.Connection) -> None:
            demo = require(conn, self.settings.project_id, demo_id)
            old = conn.execute(
                (
                    "SELECT request_sha256 FROM "
                    "guided_demo_actions WHERE demo_id=? AND "
                    "idempotency_key=?"
                ),
                (demo_id, key),
            ).fetchone()
            if old:
                if old[0] != payload_sha:
                    raise Problem(
                        409,
                        "idempotency_conflict",
                        "This decision key already seals another decision or reason",
                    )
                return
            if demo["state"] not in ACTIVE or not demo["approval_id"]:
                raise Problem(
                    409,
                    "demo_not_ready",
                    "The workflow must be live and waiting for demo permission",
                )
            if demo["permission"] != "pending":
                raise Problem(
                    409, "already_resolved", "Demo permission already has a terminal decision"
                )
            if now_ms() >= demo["expires_at_ms"]:
                raise Problem(
                    409, "demo_expired", "This guided workflow has expired; start a fresh one"
                )
            # Ownership, simulation, exact scope, resolution journal and separate local
            # demo ledger all validate/commit in the same writer transaction.
            run = conn.execute(
                "SELECT metadata_json FROM workflow_runs WHERE run_id=? AND project_id=?",
                (demo["run_id"], self.settings.project_id),
            ).fetchone()
            if not run or json.loads(run[0]).get("guided_demo_id") != demo_id:
                raise Problem(
                    409, "demo_scope_mismatch", "Only this guided fixture workflow may be changed"
                )
            approval = conn.execute(
                "SELECT action_fingerprint FROM approvals WHERE run_id=? AND approval_id=?",
                (demo["run_id"], demo["approval_id"]),
            ).fetchone()
            if not approval:
                raise Problem(
                    409, "demo_not_ready", "The mock permission request has not been recorded"
                )
            callback(
                conn,
                self.authority,
                demo["run_id"],
                demo["approval_id"],
                ApprovalCallback(action_fingerprint=approval[0], decision=decision),
                "guided:" + key,
            )
            conn.execute(
                (
                    "UPDATE guided_demo_sessions SET "
                    "permission=?,state='running',updated_at_ms=? "
                    "WHERE demo_id=?"
                ),
                (decision, now_ms(), demo_id),
            )
            conn.execute(
                (
                    "INSERT INTO "
                    "guided_demo_actions(demo_id,at_ms,kind,messag"
                    "e,idempotency_key,request_sha256) VALUES "
                    "(?,?,?,?,?,?)"
                ),
                (
                    demo_id,
                    now_ms(),
                    "permission." + decision,
                    f"Local demo dataset access {decision}. Reason: {reason}",
                    key,
                    payload_sha,
                ),
            )
            note(
                conn,
                demo_id,
                "permission.changed",
                "Demo permission updated. Existing operator pauses still require explicit resume.",
            )

        self.db.write(save)
        return self.status(demo_id)

    def get_artifact(self, demo_id: str, slug: str) -> dict[str, Any]:
        with self.db.read() as conn:
            require(conn, self.settings.project_id, demo_id)
            row = conn.execute(
                "SELECT * FROM guided_demo_artifacts WHERE demo_id=? AND slug=?", (demo_id, slug)
            ).fetchone()
            if row is None:
                raise Problem(404, "not_found", "This output has not been produced")
            return dict(row)

    def _entry(self, demo_id: str, stop: threading.Event) -> None:
        try:
            from swarmcircuit_server.demo.worker import run_workflow

            run_workflow(self, demo_id, stop)
        except Exception as exc:
            code = exc.code if isinstance(exc, LiveFailure) else "worker_unavailable"
            if not self.closed:

                def fail(conn: sqlite3.Connection) -> None:
                    current = require(conn, self.settings.project_id, demo_id)
                    if current["state"] not in ACTIVE:
                        return
                    conn.execute(
                        ("UPDATE guided_demo_sessions SET failure_code=? WHERE demo_id=?"),
                        (
                            code,
                            demo_id,
                        ),
                    )
                    self._terminal(
                        conn,
                        demo_id,
                        "expired" if code == "expired" else "failed",
                        "The local worker stopped before completing. Start a fresh workflow.",
                    )

                self.db.write(fail)
        finally:

            def disconnect(conn: sqlite3.Connection) -> None:
                demo = require(conn, self.settings.project_id, demo_id)
                for session in conn.execute(
                    "SELECT runtime_session_id FROM runtime_sessions WHERE run_id=? "
                    "AND runtime_key='guided-fixture-worker' AND state='connected'",
                    (demo["run_id"],),
                ).fetchall():
                    # This process owns the managed worker, so its exit is confirmed
                    # disconnection rather than a heartbeat-timeout inference.
                    invalidate(conn, session[0], now_ms(), "disconnected")

            try:
                self.db.write(disconnect)
            finally:
                with self.lock:
                    # Keep terminal facts in the DB; retain no past thread registry.
                    self.workers.pop(demo_id, None)
                    self.live_configs.pop(demo_id, None)
