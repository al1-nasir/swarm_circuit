import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from google.rpc.status_pb2 import Status
from swarmcircuit_server.db.store import Database, WriterUnavailable, migrate
from swarmcircuit_server.ingest import events, otlp

from tests.conftest import append, event, register_task
from tests.test_otlp import export_fixture, post_binary


def test_event_writer_failure_rolls_back_and_returns_retryable(client, run_id, monkeypatch):
    aid, tid = register_task(client, run_id)

    def failed_outbox(*args):
        raise sqlite3.OperationalError("simulated disk write failure")

    monkeypatch.setattr(events, "outbox", failed_outbox)
    item = event("task.started", aid=aid, tid=tid)
    response = append(client, run_id, [item])
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"
    with client.app.state.db.read() as conn:
        assert (
            conn.execute(
                "SELECT 1 FROM run_events WHERE event_id=?", (item["event_id"],)
            ).fetchone()
            is None
        )
        assert (
            conn.execute("SELECT state FROM tasks WHERE task_id=?", (tid,)).fetchone()[0]
            == "created"
        )


def test_otlp_writer_failure_is_protocol_error_without_false_success(client, run_id, monkeypatch):
    def failed_outbox(*args):
        raise sqlite3.OperationalError("simulated write failure")

    monkeypatch.setattr(otlp, "outbox", failed_outbox)
    response = post_binary(client, export_fixture(run_id))
    assert response.status_code == 503
    assert Status.FromString(response.content).message
    with client.app.state.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM trace_spans").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM span_links").fetchone()[0] == 0


def test_bounded_writer_queue_and_commit_order(tmp_path):
    path = tmp_path / "queue.db"
    migrate(path)
    db = Database(path, queue_size=1, timeout=2)
    entered, release = Event(), Event()

    def slow(conn):
        entered.set()
        assert release.wait(2)
        conn.execute(
            "INSERT INTO projects(project_id,name,slug,created_at_ms) VALUES ('x','x','x',1)"
        )
        return 42

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            active = executor.submit(db.write, slow)
            assert entered.wait(2)
            # Populate the one queue slot directly with a valid pending write job.
            from concurrent.futures import Future

            queued = Future()
            db.queue.put_nowait((lambda conn: 99, queued))
            with pytest.raises(WriterUnavailable, match="full"):
                db.write(lambda conn: 0)
            with db.read() as conn:
                assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0
            release.set()
            assert active.result() == 42
            assert queued.result(timeout=2) == 99
            with db.read() as conn:
                assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1
    finally:
        release.set()
        db.close()


def test_concurrent_duplicate_event_requests_have_one_effect(client, run_id):
    aid, tid = register_task(client, run_id)
    item = event("task.started", aid=aid, tid=tid)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: append(client, run_id, [item]).json(), range(8)))
    assert sum(r["accepted"] for r in results) == 1
    assert sum(r["duplicates"] for r in results) == 7
    with client.app.state.db.read() as conn:
        assert (
            conn.execute("SELECT state_version FROM tasks WHERE task_id=?", (tid,)).fetchone()[0]
            == 1
        )
