"""Sanitized read models and opt-in simulation-only, separately authenticated callbacks."""

import hashlib
import json
import sqlite3
from typing import Any
from uuid import UUID, uuid4, uuid5

from swarmcircuit_server.config import Settings
from swarmcircuit_server.db.store import now_ms
from swarmcircuit_server.errors import Problem
from swarmcircuit_server.ingest.events import dump, outbox
from swarmcircuit_server.payments.models import ApprovalCallback, SettlementCallback
from swarmcircuit_server.repository import decode_cursor, encode_cursor, get_run

MOCK_SOURCE = "mock-broker-v1"


def require(conn: sqlite3.Connection, sql: str, args: tuple[Any, ...]) -> dict[str, Any]:
    found = conn.execute(sql, args).fetchone()
    if found is None:
        raise Problem(404, "not_found", "Entity not found in this run")
    return dict(found)


def approved_ask(conn: sqlite3.Connection, intent: dict[str, Any]) -> bool:
    """Only the exact simulation approval callback may release a simulated ASK."""
    result = conn.execute(
        "SELECT r.metadata_json FROM approvals a JOIN workflow_runs r ON r.run_id=a.run_id "
        "JOIN payment_observation_context p ON p.run_id=a.run_id "
        "AND p.payment_intent_id=? AND p.scope_fingerprint=a.action_fingerprint "
        "JOIN mock_authority_callbacks c ON c.run_id=a.run_id AND c.approval_id=a.approval_id "
        "AND c.event_id=a.resolution_event_id AND c.callback_kind='approval' "
        "WHERE a.run_id=? AND a.approval_id=? AND a.state='approved' "
        "AND a.verified_resolution_source=?",
        (intent["payment_intent_id"], intent["run_id"], intent["approval_id"], MOCK_SOURCE),
    ).fetchone()
    return bool(result and json.loads(result[0]).get("simulation") is True)


def payment_guard(conn: sqlite3.Connection, intent: dict[str, Any]) -> bool:
    """True means blocked; an independent receipt never clears a DENY."""
    if intent["state"] in {"denied", "unknown", "submitted"}:
        return True
    decisions = {
        r[0]
        for r in conn.execute(
            "SELECT decision FROM payment_gate_decisions WHERE payment_intent_id=?",
            (intent["payment_intent_id"],),
        )
    }
    if "deny" in decisions or ("ask" in decisions and not approved_ask(conn, intent)):
        return True
    return bool(
        conn.execute(
            "SELECT 1 FROM payment_attempts WHERE payment_intent_id=? "
            "AND phase IN ('submitted','settlement_unknown')",
            (intent["payment_intent_id"],),
        ).fetchone()
    )


def audit(
    conn: sqlite3.Connection,
    config: Settings,
    run_id: str,
    kind: str,
    payload: dict[str, Any],
    at: int,
    *,
    approval_id: str | None = None,
) -> str:
    source = str(uuid5(UUID(config.project_id), "local:mock-broker"))
    conn.execute(
        "INSERT INTO telemetry_sources(source_id,project_id,source_key,source_kind,display_name,"
        "created_at_ms) VALUES (?,?,'local:mock-broker','simulator','Mock simulation broker',?) "
        "ON CONFLICT(project_id,source_key) DO NOTHING",
        (source, config.project_id, at),
    )
    eid = str(uuid4())
    conn.execute(
        "INSERT INTO run_events(event_id,run_id,project_id,source_id,source_event_key,event_kind,"
        "trust_class,approval_id,occurred_at_ms,ingested_at_ms,payload_json) "
        "VALUES (?,?,?,?,?,?,'simulation_truth',?,?,?,?)",
        (eid, run_id, config.project_id, source, eid, kind, approval_id, at, at, dump(payload)),
    )
    outbox(conn, run_id, kind, approval_id or payload["payment_attempt_id"])
    return eid


def callback(
    conn: sqlite3.Connection,
    config: Settings,
    run_id: str,
    entity_id: str,
    body: ApprovalCallback | SettlementCallback,
    key: str,
) -> dict[str, Any]:
    run = get_run(conn, config.project_id, run_id)
    if not config.mock_broker_enabled or run["metadata"].get("simulation") is not True:
        raise Problem(
            409, "simulation_required", "Mock authority is limited to explicit simulation runs"
        )
    kind = "approval" if isinstance(body, ApprovalCallback) else "settlement"
    digest = hashlib.sha256(
        dump({"kind": kind, "entity_id": entity_id, "body": body.model_dump()}).encode()
    ).hexdigest()
    old = conn.execute(
        "SELECT * FROM mock_authority_callbacks WHERE run_id=? AND idempotency_key=?", (run_id, key)
    ).fetchone()
    if old:
        if old["request_sha256"] != digest:
            raise Problem(409, "idempotency_conflict", "Callback key changed its target or payload")
        return json.loads(old["response_json"])
    at = now_ms()
    approval_id, attempt_id, receipt = None, None, None
    if isinstance(body, ApprovalCallback):
        approval_id = entity_id
        approval = require(
            conn, "SELECT * FROM approvals WHERE run_id=? AND approval_id=?", (run_id, approval_id)
        )
        if approval["action_fingerprint"] != body.action_fingerprint:
            raise Problem(409, "scope_conflict", "Callback does not match the exact approval scope")
        if approval["state"] != "pending":
            raise Problem(409, "already_resolved", "Approval has a terminal decision")
        intents = [
            dict(i)
            for i in conn.execute(
                "SELECT * FROM payment_intents WHERE run_id=? AND approval_id=?",
                (run_id, approval_id),
            )
        ]
        if body.decision == "approved":
            for intent in intents:
                if (
                    intent["state"] not in {"gated", "proposed"}
                    or conn.execute(
                        "SELECT 1 FROM payment_gate_decisions "
                        "WHERE payment_intent_id=? AND decision='deny'",
                        (intent["payment_intent_id"],),
                    ).fetchone()
                    or conn.execute(
                        "SELECT 1 FROM payment_attempts WHERE payment_intent_id=?",
                        (intent["payment_intent_id"],),
                    ).fetchone()
                ):
                    raise Problem(
                        409, "payment_boundary", "DENY or an existing effect cannot be approved"
                    )
                context = require(
                    conn,
                    "SELECT * FROM payment_observation_context WHERE payment_intent_id=?",
                    (intent["payment_intent_id"],),
                )
                if context["scope_fingerprint"] != body.action_fingerprint:
                    raise Problem(409, "scope_conflict", "Payment scope differs from approval")
        result = {
            "approval_id": approval_id,
            "state": body.decision,
            "authority": MOCK_SOURCE,
            "trust_class": "simulation_truth",
            "simulation": True,
        }
        eid = audit(conn, config, run_id, "approval.resolved", result, at, approval_id=approval_id)
        conn.execute(
            "UPDATE approvals SET state=?,resolved_at_ms=?,verified_resolution_source=?,"
            "resolution_actor='simulator',resolution_event_id=? WHERE approval_id=?",
            (body.decision, at, MOCK_SOURCE, eid, approval_id),
        )
        for intent in intents:
            if intent["state"] in {"gated", "proposed"}:
                conn.execute(
                    "UPDATE payment_intents SET state=? WHERE payment_intent_id=?",
                    (
                        "authorized" if body.decision == "approved" else "denied",
                        intent["payment_intent_id"],
                    ),
                )
        outbox(conn, run_id, "approval.updated", approval_id)
    else:
        attempt_id, receipt = entity_id, body.receipt_reference
        attempt = require(
            conn,
            "SELECT * FROM payment_attempts WHERE run_id=? AND payment_attempt_id=?",
            (run_id, attempt_id),
        )
        intent = require(
            conn,
            "SELECT * FROM payment_intents WHERE run_id=? AND payment_intent_id=?",
            (run_id, attempt["payment_intent_id"]),
        )
        context = require(
            conn,
            "SELECT * FROM payment_observation_context WHERE payment_intent_id=?",
            (intent["payment_intent_id"],),
        )
        if context["scope_fingerprint"] != body.scope_fingerprint:
            raise Problem(409, "scope_conflict", "Receipt does not match the payment scope")
        decisions = {
            r[0]
            for r in conn.execute(
                "SELECT decision FROM payment_gate_decisions WHERE payment_intent_id=?",
                (intent["payment_intent_id"],),
            )
        }
        if (
            "deny" in decisions
            or intent["state"] == "denied"
            or not decisions
            or ("ask" in decisions and not approved_ask(conn, intent))
            or attempt["phase"] not in {"submitted", "settlement_unknown"}
        ):
            raise Problem(
                409, "payment_boundary", "Receipt cannot bypass authorization or a terminal effect"
            )
        if conn.execute(
            "SELECT 1 FROM mock_authority_callbacks WHERE receipt_reference=?", (receipt,)
        ).fetchone():
            raise Problem(
                409, "receipt_conflict", "Receipt reference is already bound to an effect"
            )
        result = {
            "payment_attempt_id": attempt_id,
            "payment_intent_id": intent["payment_intent_id"],
            "state": "settled",
            "receipt_reference": receipt,
            "trust_class": "simulation_truth",
            "simulation": True,
        }
        eid = audit(conn, config, run_id, "payment.mock_settled", result, at)
        conn.execute(
            "UPDATE payment_attempts SET phase='settled_confirmed',receipt_trust='simulator_truth',"
            "receipt_reference=?,confirmed_at_ms=? WHERE payment_attempt_id=?",
            (receipt, at, attempt_id),
        )
        conn.execute(
            "UPDATE payment_intents SET state='settled' WHERE payment_intent_id=?",
            (intent["payment_intent_id"],),
        )
        outbox(conn, run_id, "payment.updated", intent["payment_intent_id"])
    result["evidence_event_id"] = eid
    conn.execute(
        "INSERT INTO mock_authority_callbacks VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            str(uuid4()),
            run_id,
            key,
            kind,
            digest,
            approval_id,
            attempt_id,
            receipt,
            eid,
            dump(result),
            at,
        ),
    )
    return result


def list_entities(
    conn: sqlite3.Connection,
    run_id: str,
    kind: str,
    limit: int,
    cursor: str | None,
) -> dict[str, Any]:
    table, identity, timestamp = (
        ("approvals", "approval_id", "requested_at_ms")
        if kind == "approvals"
        else ("payment_intents", "payment_intent_id", "created_at_ms")
    )
    key = decode_cursor(cursor, 2)
    condition = f" AND ({timestamp},{identity})<(?,?)" if key else ""
    rows = conn.execute(
        f"SELECT * FROM {table} WHERE run_id=?{condition} "
        f"ORDER BY {timestamp} DESC,{identity} DESC LIMIT ?",
        (run_id, *(key or []), limit + 1),
    ).fetchall()
    simulation = (
        json.loads(
            require(conn, "SELECT metadata_json FROM workflow_runs WHERE run_id=?", (run_id,))[
                "metadata_json"
            ]
        ).get("simulation")
        is True
    )
    items = []
    for record in rows[:limit]:
        item = dict(record)
        item["simulation"] = simulation
        if kind == "approvals":
            counts = conn.execute(
                "SELECT disposition,COUNT(*) FROM approval_requests "
                "WHERE approval_id=? GROUP BY disposition",
                (item[identity],),
            ).fetchall()
            item["request_counts"] = {r[0]: r[1] for r in counts}
            item["request_count"] = sum(item["request_counts"].values())
            item["resolution_trust"] = (
                "simulation_truth"
                if item["verified_resolution_source"] == MOCK_SOURCE
                else "unverified"
            )
        else:
            item["state_evidence"] = (
                "simulation_truth"
                if item["state"] == "settled" and simulation
                else "sdk_observation"
            )
            item["control_blocked"] = payment_guard(conn, item)
            gate_summary = conn.execute(
                "SELECT COUNT(*),COALESCE(MAX(decision='deny'),0) FROM payment_gate_decisions "
                "WHERE payment_intent_id=?",
                (item[identity],),
            ).fetchone()
            item["gate_decision_count"], item["has_deny"] = gate_summary[0], bool(gate_summary[1])
            item["gate_decisions"] = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM payment_gate_decisions WHERE payment_intent_id=? "
                    "ORDER BY decided_at_ms DESC,gate_decision_id DESC LIMIT 100",
                    (item[identity],),
                )
            ]
            item["attempts"] = []
            for attempt in conn.execute(
                "SELECT * FROM payment_attempts WHERE payment_intent_id=? "
                "ORDER BY attempt_no DESC LIMIT 100",
                (item[identity],),
            ):
                entry = dict(attempt)
                entry["delivery_checks"] = [
                    dict(r)
                    for r in conn.execute(
                        "SELECT * FROM delivery_verifications WHERE payment_attempt_id=? "
                        "ORDER BY checked_at_ms DESC,delivery_verification_id DESC LIMIT 100",
                        (entry["payment_attempt_id"],),
                    )
                ]
                item["attempts"].append(entry)
            item["integration"] = (
                dict(context)
                if (
                    context := conn.execute(
                        "SELECT scope_fingerprint,integration_version "
                        "FROM payment_observation_context WHERE payment_intent_id=?",
                        (item[identity],),
                    ).fetchone()
                )
                else None
            )
            item["nested_limit"] = 100
            item["uncertainty"] = (
                "Host-observed decisions/delivery do not prove authorization, settlement, "
                "content truth or finality. Mock receipts attest only to simulation."
            )
        items.append(item)
    return {
        "items": items,
        "next_cursor": encode_cursor([rows[limit - 1][timestamp], rows[limit - 1][identity]])
        if len(rows) > limit
        else None,
    }
