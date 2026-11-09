"""Project authenticated host observations without granting independent authority."""

import hashlib
import json
import sqlite3
from typing import Any
from uuid import UUID, uuid4

from swarmcircuit_server.errors import InvalidRecord


def observe(
    conn: sqlite3.Connection,
    run_id: str,
    task_id: str | None,
    approval_id: str | None,
    kind: str,
    payload: dict[str, Any],
    event_id: str,
    at: int,
) -> None:
    if not task_id:
        raise InvalidRecord("Payment observation requires a task")
    pid = str(UUID(payload["payment_intent_id"]))
    intent = conn.execute(
        "SELECT * FROM payment_intents WHERE run_id=? AND payment_intent_id=?", (run_id, pid)
    ).fetchone()
    if kind == "payment.gate_decided":
        descriptor = {k: v for k, v in payload.items() if k not in {"decision", "trust_score"}}
        descriptor.update(task_id=task_id, approval_id=approval_id)
        digest = hashlib.sha256(json.dumps(descriptor, sort_keys=True).encode()).hexdigest()
        context = conn.execute(
            "SELECT * FROM payment_observation_context WHERE payment_intent_id=?", (pid,)
        ).fetchone()
        if intent:
            if not context or context["descriptor_sha256"] != digest:
                raise InvalidRecord("Payment intent scope changed")
        else:
            if payload["decision"] == "ask" and not approval_id:
                raise InvalidRecord("ASK must link its pending approval")
            if approval_id:
                approval = conn.execute(
                    "SELECT * FROM approvals WHERE run_id=? AND approval_id=?",
                    (run_id, approval_id),
                ).fetchone()
                if not approval or approval["action_fingerprint"] != payload["scope_fingerprint"]:
                    raise InvalidRecord("Payment and approval scope differ")
            conn.execute(
                "INSERT INTO payment_intents(payment_intent_id,run_id,task_id,approval_id,"
                "intent_key,domain,chain_network,asset_code,amount_decimal,state,created_at_ms) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    pid,
                    run_id,
                    task_id,
                    approval_id,
                    payload["intent_key"],
                    payload["domain"],
                    payload["chain_network"],
                    payload["asset_code"],
                    payload["amount_decimal"],
                    "denied" if payload["decision"] == "deny" else "gated",
                    at,
                ),
            )
            conn.execute(
                "INSERT INTO payment_observation_context VALUES (?,?,?,?,?)",
                (pid, run_id, payload["scope_fingerprint"], digest, payload["integration_version"]),
            )
        conn.execute(
            "INSERT INTO payment_gate_decisions(gate_decision_id,run_id,payment_intent_id,"
            "decision,policy_revision,evidence_event_id,decided_at_ms,trust_score) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                event_id,
                run_id,
                pid,
                payload["decision"],
                payload["policy_revision"],
                event_id,
                at,
                payload.get("trust_score"),
            ),
        )
        if payload["decision"] == "deny":
            if intent and intent["state"] in {"submitted", "unknown", "settled"}:
                # A later denial cannot erase an irreversible/uncertain past outcome.
                return
            conn.execute(
                "UPDATE payment_intents SET state='denied' WHERE payment_intent_id=?", (pid,)
            )
        return
    if not intent or intent["task_id"] != task_id:
        raise InvalidRecord("Payment intent is not registered for this task")
    attempt_id = str(UUID(payload["payment_attempt_id"]))
    attempt = conn.execute(
        "SELECT * FROM payment_attempts WHERE payment_attempt_id=?", (attempt_id,)
    ).fetchone()
    if attempt and (attempt["run_id"] != run_id or attempt["payment_intent_id"] != pid):
        raise InvalidRecord("Payment attempt is outside this intent")
    if not attempt:
        # No automatic retry of an uncertain or previously submitted effect.
        if conn.execute(
            "SELECT 1 FROM payment_attempts WHERE payment_intent_id=?", (pid,)
        ).fetchone():
            raise InvalidRecord("Existing payment effect requires reconciliation, not replay")
        conn.execute(
            "INSERT INTO payment_attempts(payment_attempt_id,run_id,payment_intent_id,attempt_no,"
            "idempotency_key,phase,receipt_trust,submitted_at_ms) "
            "VALUES (?,?,?,1,?,'settlement_unknown','self_report',?)",
            (attempt_id, run_id, pid, f"observation:{attempt_id}", at),
        )
    if intent["state"] not in {"settled", "denied"}:
        conn.execute("UPDATE payment_intents SET state='unknown' WHERE payment_intent_id=?", (pid,))
    if kind == "payment.delivery_checked":
        conn.execute(
            "INSERT INTO delivery_verifications VALUES (?,?,?,?,?,?,?)",
            (
                str(uuid4()),
                run_id,
                attempt_id,
                int(payload["structural_ok"]),
                payload["reason_code"],
                at,
                event_id,
            ),
        )
