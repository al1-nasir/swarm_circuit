import sqlite3
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from swarmcircuit_server.app import create_app

from tests.conftest import append, event
from tests.test_detectors import Clock, approval, dependency, task


@pytest.fixture
def controlled(settings):
    config = replace(settings, detector_interval_seconds=0)
    clock = Clock()
    with TestClient(
        create_app(config, detector_clock=clock, control_clock=clock),
        headers={"Authorization": f"Bearer {config.sdk_token}"},
    ) as client:
        rid = client.post(
            f"/api/v1/projects/{config.project_id}/runs",
            json={"name": "control", "mode": "control"},
        ).json()["run_id"]
        yield client, rid, clock, config


def register(client, rid, *, key="host", nonce=None, capabilities=None):
    body = {
        "runtime_key": key,
        "client_nonce": nonce or str(uuid4()),
        "capabilities": capabilities if capabilities is not None else ["hold_task", "resume_task"],
    }
    result = client.post(f"/api/v1/runs/{rid}/runtime-sessions", json=body)
    assert result.status_code == 201, result.text
    return result.json(), body


def runtime_headers(session):
    return {"Authorization": f"Bearer {session['session_token']}"}


def enter(client, session, tid, key=None):
    result = client.post(
        f"/api/v1/runtime-sessions/{session['runtime_session_id']}/checkpoints",
        json={
            "task_id": tid,
            "checkpoint_key": key or str(uuid4()),
            "label": "before_read",
            "reversible": True,
        },
        headers=runtime_headers(session),
    )
    assert result.status_code == 201, result.text
    return result.json()


def version(client, rid, tid):
    return next(
        n["state_version"]
        for n in client.get(f"/api/v1/runs/{rid}/graph").json()["nodes"]
        if n["id"] == tid
    )


def queue(client, config, rid, session, tid, kind="hold_task", key=None, **updates):
    body = {
        "command_kind": kind,
        "runtime_session_id": session["runtime_session_id"],
        "task_id": tid,
        "expected_task_version": version(client, rid, tid),
        "reason": "test boundary",
    }
    body.update(updates)
    result = client.post(
        f"/api/v1/runs/{rid}/control-commands",
        json=body,
        headers={
            "Authorization": f"Bearer {config.operator_token}",
            "Idempotency-Key": key or str(uuid4()),
        },
    )
    return result, body


def poll(client, session):
    return client.get(
        f"/api/v1/runtime-sessions/{session['runtime_session_id']}/commands?wait_ms=0",
        headers=runtime_headers(session),
    )


def ack(client, session, cid, result="applied", key=None, **updates):
    body = {
        "runtime_session_id": session["runtime_session_id"],
        "fencing_epoch": session["fencing_epoch"],
        "ack_key": key or str(uuid4()),
        "result": result,
    }
    body.update(updates)
    response = client.post(
        f"/api/v1/control-commands/{cid}/ack", json=body, headers=runtime_headers(session)
    )
    return response, body


def state(client, rid, tid):
    return next(
        n["state"]
        for n in client.get(f"/api/v1/runs/{rid}/graph").json()["nodes"]
        if n["id"] == tid
    )


def test_hold_resume_requires_runtime_ack_and_boundary(controlled):
    client, rid, clock, config = controlled
    aid, tid = task(client, rid, clock)
    session, _ = register(client, rid)
    point = enter(client, session, tid)
    queued, _ = queue(client, config, rid, session, tid)
    assert queued.status_code == 202 and queued.json()["state"] == "queued"
    cid = queued.json()["command_id"]
    assert state(client, rid, tid) == "running"
    assert ack(client, session, cid)[0].status_code == 409
    assert poll(client, session).json()["commands"][0]["state"] == "dispatched"
    assert state(client, rid, tid) == "running"
    response, body = ack(client, session, cid)
    assert response.status_code == 200 and response.json()["state"] == "applied"
    assert state(client, rid, tid) == "held"
    duplicate = client.post(
        f"/api/v1/control-commands/{cid}/ack", json=body, headers=runtime_headers(session)
    )
    assert duplicate.json()["state"] == "applied"
    assert version(client, rid, tid) == 2
    resume, _ = queue(client, config, rid, session, tid, kind="resume_task")
    assert resume.status_code == 202
    poll(client, session)
    assert ack(client, session, resume.json()["command_id"])[0].json()["state"] == "applied"
    assert state(client, rid, tid) == "running"
    leave = client.post(
        f"/api/v1/runtime-sessions/{session['runtime_session_id']}/checkpoints/{point['checkpoint_id']}/leave",
        headers=runtime_headers(session),
    )
    assert leave.json()["state"] == "released"
    assert (
        append(client, rid, [event("task.completed", aid=aid, tid=tid, timestamp=clock())]).json()[
            "accepted"
        ]
        == 1
    )
    with client.app.state.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM control_acknowledgements").fetchone()[0] == 2


def test_registration_nonce_fencing_and_no_secret_reads(controlled):
    client, rid, clock, _ = controlled
    session, body = register(client, rid)
    replay = client.post(f"/api/v1/runs/{rid}/runtime-sessions", json=body).json()
    assert replay == session
    info = client.get(f"/api/v1/runs/{rid}/runtime-sessions")
    assert session["session_token"] not in info.text
    assert body["client_nonce"] not in info.text
    assert "token_sha256" not in info.text and "nonce_sha256" not in info.text
    newer, _ = register(client, rid)
    assert newer["fencing_epoch"] == session["fencing_epoch"] + 1
    assert poll(client, session).status_code == 409
    assert client.post(f"/api/v1/runs/{rid}/runtime-sessions", json=body).status_code == 409
    conflict = {**body, "client_nonce": str(uuid4()), "capabilities": ["hold_task", "hold_task"]}
    assert client.post(f"/api/v1/runs/{rid}/runtime-sessions", json=conflict).status_code == 422


def test_operator_sdk_and_session_authorities_are_separate(controlled):
    client, rid, clock, config = controlled
    _, tid = task(client, rid, clock)
    session, _ = register(client, rid)
    enter(client, session, tid)
    result, body = queue(client, config, rid, session, tid)
    cid = result.json()["command_id"]
    for token in (config.sdk_token, config.operator_token):
        assert (
            client.post(
                f"/api/v1/runtime-sessions/{session['runtime_session_id']}/heartbeat",
                headers={"Authorization": f"Bearer {token}"},
            ).status_code
            == 401
        )
        assert (
            client.post(
                f"/api/v1/control-commands/{cid}/ack",
                json={
                    "runtime_session_id": session["runtime_session_id"],
                    "fencing_epoch": 1,
                    "ack_key": str(uuid4()),
                    "result": "applied",
                },
                headers={"Authorization": f"Bearer {token}"},
            ).status_code
            == 401
        )
    assert (
        client.post(
            f"/api/v1/runs/{rid}/control-commands",
            json=body,
            headers={"Idempotency-Key": str(uuid4())},
        ).status_code
        == 403
    )
    assert client.get(f"/api/v1/runs/{rid}", headers=runtime_headers(session)).status_code == 401
    forged = event("control.applied", timestamp=clock(), payload={"command_id": cid})
    assert append(client, rid, [forged]).json()["accepted"] == 1
    assert client.get(f"/api/v1/control-commands/{cid}").json()["state"] == "queued"


def test_command_key_conflicts_and_stale_version(controlled):
    client, rid, clock, config = controlled
    _, tid = task(client, rid, clock)
    session, _ = register(client, rid)
    assert queue(client, config, rid, session, tid)[0].status_code == 404
    enter(client, session, tid)
    assert queue(client, config, rid, session, tid, expected_task_version=999)[0].status_code == 409
    key = str(uuid4())
    first, body = queue(client, config, rid, session, tid, key=key)
    for _ in range(2):
        retry = client.post(
            f"/api/v1/runs/{rid}/control-commands",
            json=body,
            headers={"Authorization": f"Bearer {config.operator_token}", "Idempotency-Key": key},
        )
        assert retry.json()["command_id"] == first.json()["command_id"]
    assert queue(client, config, rid, session, tid, key=key, reason="changed")[0].status_code == 409
    assert queue(client, config, rid, session, tid)[0].status_code == 409


@pytest.mark.parametrize("dispatched,expected", [(False, "timed_out"), (True, "unknown")])
def test_heartbeat_loss_never_claims_success(controlled, dispatched, expected):
    client, rid, clock, config = controlled
    _, tid = task(client, rid, clock)
    session, _ = register(client, rid)
    enter(client, session, tid)
    queued, _ = queue(client, config, rid, session, tid)
    cid = queued.json()["command_id"]
    if dispatched:
        poll(client, session)
    clock.value += config.runtime_heartbeat_timeout_ms
    assert poll(client, session).status_code == 409
    assert client.get(f"/api/v1/control-commands/{cid}").json()["state"] == expected
    assert state(client, rid, tid) == "running"
    assert ack(client, session, cid)[0].status_code == 409


def test_failed_ack_is_unknown_and_conflicting_replay_rejects(controlled):
    client, rid, clock, config = controlled
    _, tid = task(client, rid, clock)
    session, _ = register(client, rid)
    enter(client, session, tid)
    queued, _ = queue(client, config, rid, session, tid)
    cid = queued.json()["command_id"]
    poll(client, session)
    key = str(uuid4())
    result, _ = ack(client, session, cid, result="failed", key=key, result_detail="SECRET")
    assert result.json()["state"] == "unknown"
    assert ack(client, session, cid, result="applied", key=key)[0].status_code == 409
    assert "SECRET" not in client.get(f"/api/v1/runs/{rid}/timeline?limit=500").text


def test_pending_approval_and_dependencies_block_resume(controlled):
    client, rid, clock, config = controlled
    a1, root = task(client, rid, clock)
    a2, child = task(client, rid, clock)
    gate = str(uuid4())
    approval(client, rid, clock, a1, root, gate)
    dependency(client, rid, clock, a2, child, root)
    session, _ = register(client, rid)
    enter(client, session, child)
    queued, _ = queue(client, config, rid, session, child)
    poll(client, session)
    assert ack(client, session, queued.json()["command_id"])[0].status_code == 200
    assert queue(client, config, rid, session, child, kind="resume_task")[0].status_code == 409
    append(client, rid, [event("task.completed", aid=a1, tid=root, timestamp=clock())])
    assert queue(client, config, rid, session, child, kind="resume_task")[0].status_code == 409
    # Explicit test-only independent authority fixture; no public force-approval API exists.
    client.app.state.db.write(
        lambda conn: conn.execute(
            "UPDATE approvals SET state='approved',resolved_at_ms=?,"
            "verified_resolution_source='test-service-fixture',resolution_actor='"
            "human-fixture' WHERE approval_id=?",
            (clock(), gate),
        )
    )
    assert queue(client, config, rid, session, child, kind="resume_task")[0].status_code == 202


def test_observation_cannot_overwrite_active_boundary(controlled):
    client, rid, clock, config = controlled
    aid, tid = task(client, rid, clock)
    session, _ = register(client, rid)
    enter(client, session, tid)
    for kind in ("task.started", "task.completed", "task.failed"):
        assert (
            append(client, rid, [event(kind, aid=aid, tid=tid, timestamp=clock())]).json()[
                "rejected"
            ]
            == 1
        )
    assert state(client, rid, tid) == "running"


def test_backpressure_is_bounded_explicit_and_idempotent(controlled):
    client, rid, clock, config = controlled
    ar, root = task(client, rid, clock)
    ac, child = task(client, rid, clock)
    _, independent = task(client, rid, clock)
    gate = str(uuid4())
    approval(client, rid, clock, ar, root, gate)
    dependency(client, rid, clock, ac, child, root)
    session, _ = register(client, rid)
    enter(client, session, root)
    enter(client, session, child)
    headers = {"Authorization": f"Bearer {config.operator_token}", "Idempotency-Key": str(uuid4())}
    preview = client.post(
        f"/api/v1/runs/{rid}/backpressure",
        json={"approval_id": gate, "reason": "shared gate"},
        headers=headers,
    )
    assert preview.status_code == 200
    assert set(preview.json()["dependent_task_ids"]) == {root, child}
    assert independent not in preview.json()["dependent_task_ids"]
    assert preview.json()["commands"] == []
    body = {"approval_id": gate, "reason": "shared gate", "apply": True}
    applied = client.post(f"/api/v1/runs/{rid}/backpressure", json=body, headers=headers)
    assert len(applied.json()["commands"]) == 2 and not applied.json()["applied"]
    replay = client.post(f"/api/v1/runs/{rid}/backpressure", json=body, headers=headers)
    assert replay.json()["command_ids"] == applied.json()["command_ids"]
    for cmd in poll(client, session).json()["commands"]:
        assert ack(client, session, cmd["command_id"])[0].status_code == 200
    assert state(client, rid, independent) == "running"
    assert state(client, rid, child) == "held"


def test_runtime_and_task_scope_cannot_be_crossed(controlled):
    client, rid, clock, config = controlled
    _, tid = task(client, rid, clock)
    session, _ = register(client, rid)
    other, _ = register(client, rid, key="other-host")
    point = enter(client, session, tid)
    response = client.post(
        f"/api/v1/runtime-sessions/{other['runtime_session_id']}/checkpoints",
        json={"task_id": tid, "checkpoint_key": str(uuid4()), "label": "x", "reversible": True},
        headers=runtime_headers(other),
    )
    assert response.status_code == 409
    assert (
        client.get(
            f"/api/v1/runtime-sessions/{other['runtime_session_id']}/commands?wait_ms=0",
            headers=runtime_headers(session),
        ).status_code
        == 403
    )
    assert (
        client.get(
            f"/api/v1/runtime-sessions/{other['runtime_session_id']}/checkpoints/{point['checkpoint_id']}",
            headers=runtime_headers(other),
        ).status_code
        == 404
    )


@pytest.mark.parametrize("stage", ["dispatch", "ack"])
def test_task_version_change_rejects_stale_effect(controlled, stage):
    client, rid, clock, config = controlled
    _, tid = task(client, rid, clock)
    session, _ = register(client, rid)
    enter(client, session, tid)
    queued, _ = queue(client, config, rid, session, tid)
    cid = queued.json()["command_id"]
    if stage == "ack":
        poll(client, session)
    # Simulate a concurrent trusted state/version change after submission.
    client.app.state.db.write(
        lambda conn: conn.execute(
            "UPDATE tasks SET state_version=state_version+1 WHERE task_id=?", (tid,)
        )
    )
    if stage == "dispatch":
        assert poll(client, session).json()["commands"] == []
        assert client.get(f"/api/v1/control-commands/{cid}").json()["state"] == "rejected"
    else:
        assert ack(client, session, cid)[0].status_code == 409
    assert state(client, rid, tid) == "running"
    with client.app.state.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM control_acknowledgements").fetchone()[0] == 0


def test_ack_wrong_session_and_epoch_cannot_mutate_task(controlled):
    client, rid, clock, config = controlled
    _, tid = task(client, rid, clock)
    session, _ = register(client, rid)
    other, _ = register(client, rid, key="other")
    enter(client, session, tid)
    queued, _ = queue(client, config, rid, session, tid)
    cid = queued.json()["command_id"]
    poll(client, session)
    assert ack(client, other, cid)[0].status_code == 409
    assert (
        ack(client, session, cid, fencing_epoch=session["fencing_epoch"] + 1)[0].status_code == 409
    )
    assert state(client, rid, tid) == "running"
    assert ack(client, session, cid)[0].json()["state"] == "applied"


def test_ack_persistence_failure_rolls_back_effect_and_evidence(controlled, monkeypatch):
    from swarmcircuit_server.controller import service

    client, rid, clock, config = controlled
    _, tid = task(client, rid, clock)
    session, _ = register(client, rid)
    point = enter(client, session, tid)
    queued, _ = queue(client, config, rid, session, tid)
    cid = queued.json()["command_id"]
    poll(client, session)
    real_audit = service.audit

    def fail_after_state_update(conn, run_id, topic, *args, **kwargs):
        if topic == "runtime.command_ack":
            raise sqlite3.OperationalError("simulated disk failure")
        return real_audit(conn, run_id, topic, *args, **kwargs)

    monkeypatch.setattr(service, "audit", fail_after_state_update)
    response, body = ack(client, session, cid)
    assert response.status_code == 503
    assert state(client, rid, tid) == "running"
    assert client.get(f"/api/v1/control-commands/{cid}").json()["state"] == "dispatched"
    with client.app.state.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM control_acknowledgements").fetchone()[0] == 0
        assert (
            conn.execute(
                "SELECT state FROM runtime_checkpoints WHERE checkpoint_id=?",
                (point["checkpoint_id"],),
            ).fetchone()[0]
            == "available"
        )
    monkeypatch.setattr(service, "audit", real_audit)
    replay = client.post(
        f"/api/v1/control-commands/{cid}/ack", json=body, headers=runtime_headers(session)
    )
    assert replay.json()["state"] == "applied"


@pytest.mark.parametrize("dispatched,expected", [(False, "timed_out"), (True, "unknown")])
def test_command_deadline_with_healthy_heartbeats(controlled, dispatched, expected):
    client, rid, clock, config = controlled
    _, tid = task(client, rid, clock)
    session, _ = register(client, rid)
    enter(client, session, tid)
    queued, _ = queue(client, config, rid, session, tid)
    cid = queued.json()["command_id"]
    if dispatched:
        poll(client, session)
    end = clock() + config.command_timeout_ms
    while clock() < end:
        clock.value = min(end, clock() + config.runtime_heartbeat_timeout_ms // 2)
        assert (
            client.post(
                f"/api/v1/runtime-sessions/{session['runtime_session_id']}/heartbeat",
                headers=runtime_headers(session),
            ).status_code
            == 200
        )
    assert client.get(f"/api/v1/control-commands/{cid}").json()["state"] == expected
    assert ack(client, session, cid)[0].status_code == 409
    assert state(client, rid, tid) == "running"


def test_absolute_token_expiry_cannot_be_extended_or_replayed(controlled):
    client, rid, clock, config = controlled
    client.app.state.control.config = replace(
        config, runtime_token_ttl_ms=config.runtime_heartbeat_timeout_ms * 2
    )
    session, body = register(client, rid)
    while clock() < session["expires_at_ms"]:
        clock.value = min(
            session["expires_at_ms"], clock() + config.runtime_heartbeat_timeout_ms // 2
        )
        response = client.post(
            f"/api/v1/runtime-sessions/{session['runtime_session_id']}/heartbeat",
            headers=runtime_headers(session),
        )
        assert response.status_code == (409 if clock() == session["expires_at_ms"] else 200)
    assert client.post(f"/api/v1/runs/{rid}/runtime-sessions", json=body).status_code == 409


@pytest.mark.parametrize("gate_decision", ["ask", "deny", None])
def test_payment_guard_prevents_resume_and_leave(controlled, gate_decision):
    client, rid, clock, config = controlled
    _, tid = task(client, rid, clock)
    session, _ = register(client, rid)
    point = enter(client, session, tid)
    queued, _ = queue(client, config, rid, session, tid)
    poll(client, session)
    ack(client, session, queued.json()["command_id"])
    pid = str(uuid4())

    def payment_fixture(conn):
        conn.execute(
            "INSERT INTO payment_intents(payment_intent_id,run_id,task_id,intent_key,domain,"
            "asset_code,amount_decimal,state,created_at_ms) VALUES (?,?,?,?,'mock.example',"
            "'MOCK','1.00',?,?)",
            (pid, rid, tid, pid, "gated" if gate_decision else "unknown", clock()),
        )
        if gate_decision:
            conn.execute(
                "INSERT INTO payment_gate_decisions(gate_decision_id,run_id,payment_intent_id,"
                "decision,decided_at_ms) VALUES (?,?,?,?,?)",
                (str(uuid4()), rid, pid, gate_decision, clock()),
            )

    client.app.state.db.write(payment_fixture)
    response, _ = queue(client, config, rid, session, tid, kind="resume_task")
    assert response.status_code == 409 and response.json()["code"] == "payment_boundary"
    assert (
        client.post(
            f"/api/v1/runtime-sessions/{session['runtime_session_id']}/checkpoints/{point['checkpoint_id']}/leave",
            headers=runtime_headers(session),
        ).status_code
        == 409
    )
    assert state(client, rid, tid) == "held"


def test_backpressure_bound_exhaustion_is_atomic(controlled):
    client, rid, clock, config = controlled
    ar, root = task(client, rid, clock)
    ac, child = task(client, rid, clock)
    gate = str(uuid4())
    approval(client, rid, clock, ar, root, gate)
    dependency(client, rid, clock, ac, child, root)
    session, _ = register(client, rid)
    enter(client, session, root)
    enter(client, session, child)
    client.app.state.control.config = replace(config, backpressure_limit=1)
    response = client.post(
        f"/api/v1/runs/{rid}/backpressure",
        json={"approval_id": gate, "reason": "bounded gate", "apply": True},
        headers={
            "Authorization": f"Bearer {config.operator_token}",
            "Idempotency-Key": str(uuid4()),
        },
    )
    assert response.status_code == 409 and response.json()["code"] == "policy_bound_exceeded"
    with client.app.state.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM control_commands").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM control_policy_requests").fetchone()[0] == 0


def test_restart_invalidates_dispatched_work_without_adopting_boundary(settings):
    config = replace(settings, detector_interval_seconds=0)
    clock = Clock()
    auth = {"Authorization": f"Bearer {config.sdk_token}"}
    with TestClient(create_app(config, control_clock=clock), headers=auth) as client:
        rid = client.post(
            f"/api/v1/projects/{config.project_id}/runs",
            json={"name": "restart", "mode": "control"},
        ).json()["run_id"]
        _, tid = task(client, rid, clock)
        session, _ = register(client, rid)
        point = enter(client, session, tid)
        queued, _ = queue(client, config, rid, session, tid)
        cid = queued.json()["command_id"]
        poll(client, session)
    with TestClient(create_app(config, control_clock=clock), headers=auth) as client:
        assert poll(client, session).status_code == 409
        assert client.get(f"/api/v1/control-commands/{cid}").json()["state"] == "unknown"
        details = client.get(f"/api/v1/runs/{rid}/runtime-sessions").json()["items"][0]
        assert details["checkpoints"][0]["checkpoint_id"] == point["checkpoint_id"]
        assert details["checkpoints"][0]["state"] == "unknown"
        new, _ = register(client, rid)
        response = client.post(
            f"/api/v1/runtime-sessions/{new['runtime_session_id']}/checkpoints",
            json={
                "task_id": tid,
                "checkpoint_key": str(uuid4()),
                "label": "new",
                "reversible": True,
            },
            headers=runtime_headers(new),
        )
        assert response.status_code == 409
        assert state(client, rid, tid) == "running"


def test_policy_review_binds_scope_checkpoint_and_reconciles_canonical_acks(controlled):
    client, rid, clock, config = controlled
    ar, root = task(client, rid, clock)
    ac, child = task(client, rid, clock)
    gate = str(uuid4())
    approval(client, rid, clock, ar, root, gate)
    dependency(client, rid, clock, ac, child, root)
    session, _ = register(client, rid)
    enter(client, session, root)
    enter(client, session, child)
    key = str(uuid4())
    headers = {"Authorization": f"Bearer {config.operator_token}", "Idempotency-Key": key}
    preview = client.post(
        f"/api/v1/runs/{rid}/backpressure",
        json={"approval_id": gate, "reason": "Review scope"},
        headers=headers,
    ).json()
    assert len(preview["targets"]) == 2
    assert all(t["checkpoint_id"] and t["fencing_epoch"] == 1 for t in preview["targets"])
    body = {
        "approval_id": gate,
        "reason": "Review scope",
        "apply": True,
        "expected_preview_sha256": "0" * 64,
    }
    rejected = client.post(f"/api/v1/runs/{rid}/backpressure", json=body, headers=headers)
    assert rejected.status_code == 409 and rejected.json()["code"] == "stale_policy_preview"
    with client.app.state.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM control_commands").fetchone()[0] == 0
    body["expected_preview_sha256"] = preview["preview_sha256"]
    accepted = client.post(f"/api/v1/runs/{rid}/backpressure", json=body, headers=headers)
    assert accepted.status_code == 200 and len(accepted.json()["commands"]) == 2
    assert all(c["state"] == "queued" for c in accepted.json()["commands"])
    for c in poll(client, session).json()["commands"]:
        assert ack(client, session, c["command_id"])[0].status_code == 200
    readback = client.get(f"/api/v1/runs/{rid}/backpressure", params={"key": key})
    assert readback.status_code == 200
    assert all(
        c["state"] == "applied" and len(c["acknowledgements"]) == 1
        for c in readback.json()["commands"]
    )
    assert (
        client.get(f"/api/v1/runs/{rid}/backpressure", params={"key": str(uuid4())}).status_code
        == 404
    )
    replay = client.post(f"/api/v1/runs/{rid}/backpressure", json=body, headers=headers)
    assert replay.json()["command_ids"] == accepted.json()["command_ids"]


def test_policy_review_rejects_a_changed_dependency_closure(controlled):
    client, rid, clock, config = controlled
    ar, root = task(client, rid, clock)
    ac, child = task(client, rid, clock)
    gate = str(uuid4())
    approval(client, rid, clock, ar, root, gate)
    session, _ = register(client, rid)
    enter(client, session, root)
    enter(client, session, child)
    headers = {"Authorization": f"Bearer {config.operator_token}", "Idempotency-Key": str(uuid4())}
    preview = client.post(
        f"/api/v1/runs/{rid}/backpressure",
        json={"approval_id": gate, "reason": "Preview"},
        headers=headers,
    ).json()
    dependency(client, rid, clock, ac, child, root)
    response = client.post(
        f"/api/v1/runs/{rid}/backpressure",
        json={
            "approval_id": gate,
            "reason": "Preview",
            "apply": True,
            "expected_preview_sha256": preview["preview_sha256"],
        },
        headers=headers,
    )
    assert response.status_code == 409 and response.json()["code"] == "stale_policy_preview"
    with client.app.state.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM control_policy_requests").fetchone()[0] == 0
