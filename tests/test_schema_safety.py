import sqlite3
from uuid import uuid4

import pytest

from tests.conftest import register_task


def test_original_schema_rejects_applied_without_ack(client, run_id):
    _, tid = register_task(client, run_id)
    sid, cid = str(uuid4()), str(uuid4())

    def provision(conn):
        conn.execute(
            "INSERT INTO runtime_sessions(runtime_session_id,run_id,runtime_key,actor_subject,"
            "connected_at_ms,last_heartbeat_ms) VALUES (?,?,?,'test',1,1)",
            (sid, run_id, "schema-test"),
        )
        conn.execute(
            "INSERT INTO control_commands(command_id,run_id,runtime_session_id,task_id,"
            "command_kind,idempotency_key,required_capability,session_fencing_epoch,"
            "initiated_by,request_reason,created_at_ms) VALUES (?,?,?,?,'hold_task','test-key',"
            "'hold_task',1,'operator','schema test',1)",
            (cid, run_id, sid, tid),
        )

    client.app.state.db.write(provision)
    with pytest.raises(sqlite3.IntegrityError, match="matching runtime acknowledgement"):
        client.app.state.db.write(
            lambda conn: conn.execute(
                "UPDATE control_commands SET state='applied' WHERE command_id=?",
                (cid,),
            )
        )
    with client.app.state.db.read() as conn:
        assert (
            conn.execute(
                "SELECT state FROM control_commands WHERE command_id=?", (cid,)
            ).fetchone()[0]
            == "queued"
        )


def test_original_schema_rejects_unverified_settlement(client, run_id):
    _, tid = register_task(client, run_id)
    pid = str(uuid4())
    client.app.state.db.write(
        lambda conn: conn.execute(
            "INSERT INTO payment_intents(payment_intent_id,run_id,task_id,intent_key,domain,"
            "asset_code,amount_decimal,state,created_at_ms) VALUES (?,?,?,'intent','mock.example',"
            "'MOCK','1.00','proposed',1)",
            (pid, run_id, tid),
        )
    )
    with pytest.raises(sqlite3.IntegrityError, match="trusted receipt"):
        client.app.state.db.write(
            lambda conn: conn.execute(
                "UPDATE payment_intents SET state='settled' WHERE payment_intent_id=?",
                (pid,),
            )
        )
    with pytest.raises(sqlite3.IntegrityError):
        client.app.state.db.write(
            lambda conn: conn.execute(
                "INSERT INTO payment_attempts(payment_attempt_id,run_id,payment_intent_id,"
                "attempt_no,"
                "idempotency_key,phase,receipt_trust,confirmed_at_ms) VALUES (?,?,?,1,'attempt',"
                "'settled_confirmed','self_report',1)",
                (str(uuid4()), run_id, pid),
            )
        )
