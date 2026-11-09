import sqlite3
from uuid import uuid4

import pytest
from starlette.websockets import WebSocketDisconnect
from swarmcircuit_server.db.store import WriterUnavailable
from swarmcircuit_server.ingest.events import outbox
from swarmcircuit_server.realtime import snapshot

from tests.conftest import append, event, register_task
from tests.test_control import controlled as controlled
from tests.test_control import enter, queue, register
from tests.test_detectors import task


def ticket(client, rid):
    response = client.post(f"/api/v1/runs/{rid}/stream-tickets")
    assert response.status_code == 200, response.text
    return ["swarmcircuit.v1", response.json()["ticket"]]


def test_websocket_requires_scoped_one_use_short_lived_ticket(controlled):
    client, rid, clock, config = controlled
    protocols = ticket(client, rid)
    with client.websocket_connect(f"/api/v1/ws/runs/{rid}", subprotocols=protocols) as ws:
        assert ws.receive_json()["type"] == "snapshot_required"
    for invalid in (
        protocols,
        ["swarmcircuit.v1", config.sdk_token],
        ["swarmcircuit.v1", "invalid"],
    ):
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect(f"/api/v1/ws/runs/{rid}", subprotocols=invalid),
        ):
            pass
    expired = ticket(client, rid)
    clock.value += 60_000
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(f"/api/v1/ws/runs/{rid}", subprotocols=expired),
    ):
        pass
    assert client.post(f"/api/v1/runs/{uuid4()}/stream-tickets").status_code == 404


def test_websocket_reconnect_delivers_durable_invalidations(client, run_id, settings):
    first = snapshot(client.app.state.db, settings.project_id, run_id, None)
    aid, tid = register_task(client, run_id)
    append(client, run_id, [event("task.started", aid=aid, tid=tid)])
    with client.websocket_connect(
        f"/api/v1/ws/runs/{run_id}?after={first['cursor']}", subprotocols=ticket(client, run_id)
    ) as ws:
        batch = ws.receive_json()
        assert batch["type"] == "notifications"
        assert [n["sequence"] for n in batch["notifications"]] == list(
            range(first["cursor"] + 1, batch["cursor"] + 1)
        )
        assert all(
            n["run_id"] == run_id and n["payload"] == {"snapshot_required": True}
            for n in batch["notifications"]
        )
        cursor = batch["cursor"]
    append(client, run_id, [event("task.progress", aid=aid, tid=tid)])
    with client.websocket_connect(
        f"/api/v1/ws/runs/{run_id}?after={cursor}", subprotocols=ticket(client, run_id)
    ) as ws:
        batch = ws.receive_json()
        assert batch["cursor"] > cursor


def test_notification_cursors_survive_retention_gaps_and_rollback(client, run_id, settings):
    db = client.app.state.db
    before = snapshot(db, settings.project_id, run_id, None)["cursor"]

    def failed(conn):
        outbox(conn, run_id, "test.updated", run_id)
        raise sqlite3.OperationalError("simulated full disk")

    with pytest.raises(WriterUnavailable):
        db.write(failed)
    assert snapshot(db, settings.project_id, run_id, None)["cursor"] == before
    db.write(lambda conn: outbox(conn, run_id, "test.updated", run_id))
    db.write(lambda conn: outbox(conn, run_id, "test.updated", run_id))
    db.write(
        lambda conn: conn.execute(
            "DELETE FROM ui_stream_notifications WHERE run_id=? AND sequence=?",
            (run_id, before + 1),
        )
    )
    gap = snapshot(db, settings.project_id, run_id, before)
    assert gap["type"] == "snapshot_required" and gap["cursor"] == before + 2
    assert (
        snapshot(db, settings.project_id, run_id, gap["cursor"] + 10)["type"] == "snapshot_required"
    )


def test_websocket_does_not_accept_mutations(client, run_id):
    with client.websocket_connect(
        f"/api/v1/ws/runs/{run_id}", subprotocols=ticket(client, run_id)
    ) as ws:
        ws.receive_json()
        ws.send_json({"command_kind": "hold_task"})
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    with client.app.state.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM control_commands").fetchone()[0] == 0


def test_command_history_and_evidence_are_scoped_and_paginated(controlled):
    client, rid, clock, config = controlled
    for _ in range(3):
        aid, tid = task(client, rid, clock)
        session, _ = register(client, rid, key=str(uuid4()))
        enter(client, session, tid)
        assert queue(client, config, rid, session, tid)[0].status_code == 202
    seen, cursor = [], None
    while True:
        response = client.get(
            f"/api/v1/runs/{rid}/control-commands",
            params={"limit": 1, **({"cursor": cursor} if cursor else {})},
        )
        assert response.status_code == 200
        page = response.json()
        seen.extend(c["command_id"] for c in page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == 3
    timeline = client.get(f"/api/v1/runs/{rid}/timeline").json()["items"]
    source = next(i for i in timeline if i["item_type"] == "event")
    item = client.get(f"/api/v1/runs/{rid}/evidence/{source['id']}")
    assert item.json()["payload"] == source["payload"]
    assert client.get(f"/api/v1/runs/{uuid4()}/evidence/{source['id']}").status_code == 404
    assert client.get(f"/api/v1/runs/{rid}/evidence/{uuid4()}").status_code == 404
    assert client.get(f"/api/v1/runs/{rid}/control-commands?cursor=bad").status_code == 422


def test_stream_read_is_consistent_during_concurrent_commit(client, run_id, settings, monkeypatch):
    from contextlib import contextmanager

    db = client.app.state.db
    original_read = db.read
    before = snapshot(db, settings.project_id, run_id, None)["cursor"]
    committed = False

    class Interleave:
        def __init__(self, conn):
            self.conn = conn

        def execute(self, sql, args=()):
            nonlocal committed
            if "SELECT sequence FROM ui_stream_heads" in sql and not committed:
                # Commit after the reader's first SELECT but before its head query.
                db.write(lambda writer: outbox(writer, run_id, "test.updated", run_id))
                committed = True
            return self.conn.execute(sql, args)

    @contextmanager
    def read():
        with original_read() as conn:
            yield Interleave(conn)

    monkeypatch.setattr(db, "read", read)
    during = snapshot(db, settings.project_id, run_id, before)
    assert committed
    assert during["cursor"] == before and not during["notifications"]
    after = snapshot(db, settings.project_id, run_id, before)
    assert after["cursor"] == before + 1
    assert len(after["notifications"]) == 1
