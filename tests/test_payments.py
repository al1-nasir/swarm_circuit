import sqlite3
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from swarmcircuit_server.app import create_app

from tests.conftest import append, event
from tests.test_control import ack, enter, poll, queue, register, state
from tests.test_detectors import Clock, approval, task

SCOPE = "sha256:" + "a" * 64
POLICY = "sha256:" + "b" * 64


@pytest.fixture
def payments(settings):
    config = replace(
        settings,
        detector_interval_seconds=0,
        mock_broker_enabled=True,
        mock_broker_token="broker-" + "c" * 32,
    )
    clock = Clock()
    with TestClient(
        create_app(config, detector_clock=clock, control_clock=clock),
        headers={"Authorization": f"Bearer {config.sdk_token}"},
    ) as client:
        rid = client.post(
            f"/api/v1/projects/{config.project_id}/runs",
            json={"name": "payment-test", "mode": "control", "simulation": True},
        ).json()["run_id"]
        yield client, rid, clock, config


def gate(client, rid, clock, aid, tid, *, decision="allow", pid=None, apid=None, **changes):
    pid = pid or str(uuid4())
    payload = {
        "payment_intent_id": pid,
        "intent_key": pid,
        "domain": "mock.example",
        "asset_code": "MOCK",
        "amount_decimal": "0.01",
        "chain_network": "mock",
        "decision": decision,
        "policy_revision": POLICY,
        "scope_fingerprint": SCOPE,
        "integration_version": "0.2.1",
    }
    payload.update(changes)
    envelope = event(
        "payment.gate_decided",
        aid=aid,
        tid=tid,
        timestamp=clock(),
        payload=payload,
        **({"approval_id": apid} if apid else {}),
    )
    response = append(client, rid, [envelope])
    return pid, envelope, response


def effect(client, rid, clock, aid, tid, pid, *, attempt_id=None, delivery=None):
    attempt_id = attempt_id or str(uuid4())
    payload = {
        "payment_intent_id": pid,
        "payment_attempt_id": attempt_id,
        "integration_version": "0.2.1",
    }
    if delivery is not None:
        payload.update(
            structural_ok=delivery,
            reason_code="structural_ok" if delivery else "structural_failure",
        )
    envelope = event(
        "payment.attempt_submitted" if delivery is None else "payment.delivery_checked",
        aid=aid,
        tid=tid,
        timestamp=clock(),
        payload=payload,
    )
    return attempt_id, append(client, rid, [envelope])


def resolve(
    client, config, rid, apid, *, key=None, fingerprint=SCOPE, decision="approved", token=None
):
    return client.post(
        f"/api/v1/mock/runs/{rid}/approvals/{apid}/resolution",
        json={"action_fingerprint": fingerprint, "decision": decision},
        headers={
            "Authorization": f"Bearer {token or config.mock_broker_token}",
            "Idempotency-Key": key or str(uuid4()),
        },
    )


def settle(
    client, config, rid, attempt_id, *, key=None, fingerprint=SCOPE, receipt=None, token=None
):
    return client.post(
        f"/api/v1/mock/runs/{rid}/payment-attempts/{attempt_id}/settlement",
        json={
            "scope_fingerprint": fingerprint,
            "receipt_reference": receipt or "mock:" + str(uuid4()),
        },
        headers={
            "Authorization": f"Bearer {token or config.mock_broker_token}",
            "Idempotency-Key": key or str(uuid4()),
        },
    )


def read_payment(client, rid, pid):
    return next(
        i
        for i in client.get(f"/api/v1/runs/{rid}/payments").json()["items"]
        if i["payment_intent_id"] == pid
    )


def pending_gate(client, rid, clock, fingerprint=SCOPE):
    aid, tid = task(client, rid, clock)
    apid = str(uuid4())
    approval(client, rid, clock, aid, tid, apid, key=fingerprint)
    pid, _, result = gate(
        client, rid, clock, aid, tid, decision="ask", apid=apid, scope_fingerprint=fingerprint
    )
    assert result.json()["accepted"] == 1, result.text
    return aid, tid, apid, pid


def test_payment_observations_are_sanitized_deduplicated_and_scoped(payments):
    client, rid, clock, config = payments
    aid, tid = task(client, rid, clock)
    pid, envelope, result = gate(
        client, rid, clock, aid, tid, headers="SECRET", body="SECRET", wallet_key="SECRET"
    )
    assert result.json()["accepted"] == 1
    assert append(client, rid, [envelope]).json()["duplicates"] == 1
    _, _, conflict = gate(client, rid, clock, aid, tid, pid=pid, amount_decimal="9.00")
    assert conflict.json()["rejected"] == 1
    payment = read_payment(client, rid, pid)
    assert payment["state"] == "gated" and len(payment["gate_decisions"]) == 1
    assert payment["amount_decimal"] == "0.01" and payment["state_evidence"] == "sdk_observation"
    assert "SECRET" not in client.get(f"/api/v1/runs/{rid}/timeline?limit=500").text
    aid2, tid2 = task(client, rid, clock)
    assert effect(client, rid, clock, aid2, tid2, pid)[1].json()["rejected"] == 1


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-1", "0", "1e3", 0.01])
def test_payment_amounts_remain_exact_positive_decimal_strings(payments, amount):
    client, rid, clock, _ = payments
    aid, tid = task(client, rid, clock)
    assert gate(client, rid, clock, aid, tid, amount_decimal=amount)[2].json()["rejected"] == 1
    assert client.get(f"/api/v1/runs/{rid}/payments").json()["items"] == []


def test_mock_authority_separate_scoped_and_idempotent(payments):
    client, rid, clock, config = payments
    _, tid, apid, pid = pending_gate(client, rid, clock)
    for token in (config.sdk_token, config.operator_token):
        assert resolve(client, config, rid, apid, token=token).status_code == 401
    assert resolve(client, config, rid, apid, fingerprint=POLICY).status_code == 409
    key = str(uuid4())
    first = resolve(client, config, rid, apid, key=key)
    assert first.status_code == 200, first.text
    assert first.json()["trust_class"] == "simulation_truth"
    assert resolve(client, config, rid, apid, key=key).json() == first.json()
    assert resolve(client, config, rid, apid, key=key, decision="denied").status_code == 409
    assert resolve(client, config, rid, apid).status_code == 409
    assert read_payment(client, rid, pid)["state"] == "authorized"
    with client.app.state.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM mock_authority_callbacks").fetchone()[0] == 1
    assert (
        client.get(
            f"/api/v1/runs/{rid}", headers={"Authorization": f"Bearer {config.mock_broker_token}"}
        ).status_code
        == 401
    )


def test_mock_broker_disabled_and_cannot_touch_non_simulation_runs(payments):
    client, rid, clock, config = payments
    _, _, apid, _ = pending_gate(client, rid, clock)
    client.app.state.settings = replace(config, mock_broker_enabled=False)
    assert resolve(client, config, rid, apid).status_code == 404
    client.app.state.settings = config
    real = client.post(
        f"/api/v1/projects/{config.project_id}/runs", json={"name": "real", "mode": "control"}
    ).json()["run_id"]
    assert resolve(client, config, real, apid).status_code == 409
    assert resolve(client, config, str(uuid4()), apid).status_code == 404


def test_trusted_approval_only_makes_exact_checkpoint_eligible(payments):
    client, rid, clock, config = payments
    _, tid, apid, pid = pending_gate(client, rid, clock)
    session, _ = register(client, rid)
    enter(client, session, tid)
    held, _ = queue(client, config, rid, session, tid)
    poll(client, session)
    ack(client, session, held.json()["command_id"])
    assert queue(client, config, rid, session, tid, kind="resume_task")[0].status_code == 409
    assert resolve(client, config, rid, apid).status_code == 200
    assert state(client, rid, tid) == "held"
    resumed, _ = queue(client, config, rid, session, tid, kind="resume_task")
    assert resumed.status_code == 202
    poll(client, session)
    assert ack(client, session, resumed.json()["command_id"])[0].json()["state"] == "applied"


def test_deny_is_absorbing_even_after_allow_report_and_mock_callback(payments):
    client, rid, clock, config = payments
    aid, tid, apid, pid = pending_gate(client, rid, clock)
    assert (
        gate(client, rid, clock, aid, tid, pid=pid, apid=apid, decision="deny")[2].json()[
            "accepted"
        ]
        == 1
    )
    assert (
        gate(client, rid, clock, aid, tid, pid=pid, apid=apid, decision="allow")[2].json()[
            "accepted"
        ]
        == 1
    )
    assert resolve(client, config, rid, apid).status_code == 409
    attempt, _ = effect(client, rid, clock, aid, tid, pid)
    assert settle(client, config, rid, attempt).status_code == 409
    assert read_payment(client, rid, pid)["state"] == "denied"


def test_delivery_success_and_forged_events_do_not_establish_settlement(payments):
    client, rid, clock, config = payments
    aid, tid = task(client, rid, clock)
    pid, _, _ = gate(client, rid, clock, aid, tid)
    attempt, result = effect(client, rid, clock, aid, tid, pid, delivery=True)
    assert result.json()["accepted"] == 1
    forged = [
        event(
            kind,
            aid=aid,
            tid=tid,
            timestamp=clock(),
            payload={
                "payment_intent_id": pid,
                "state": "settled",
                "receipt_trust": "service_verified",
            },
        )
        for kind in ("payment.settled", "payment.mock_settled", "approval.resolved")
    ]
    assert append(client, rid, forged).json()["accepted"] == 3
    item = read_payment(client, rid, pid)
    assert item["state"] == "unknown" and item["attempts"][0]["receipt_trust"] == "self_report"
    assert item["control_blocked"]
    assert effect(client, rid, clock, aid, tid, pid)[1].json()["rejected"] == 1
    for token in (config.sdk_token, config.operator_token):
        assert settle(client, config, rid, attempt, token=token).status_code == 401
    assert settle(client, config, rid, attempt, fingerprint=POLICY).status_code == 409
    key, receipt = str(uuid4()), "mock:" + str(uuid4())
    settled = settle(client, config, rid, attempt, key=key, receipt=receipt)
    assert settled.status_code == 200, settled.text
    assert settle(client, config, rid, attempt, key=key, receipt=receipt).json() == settled.json()
    item = read_payment(client, rid, pid)
    assert item["state"] == "settled" and item["state_evidence"] == "simulation_truth"
    assert not item["control_blocked"]


def test_confirmed_receipt_does_not_erase_delivery_failure_or_reuse_receipt(payments):
    client, rid, clock, config = payments
    aid, tid = task(client, rid, clock)
    pid, _, _ = gate(client, rid, clock, aid, tid)
    attempt, _ = effect(client, rid, clock, aid, tid, pid, delivery=False)
    warnings = client.get(f"/api/v1/runs/{rid}/incidents").json()["items"]
    assert {i["metrics"]["warning"] for i in warnings if i["kind"] == "policy_warning"} == {
        "settlement_unknown",
        "structural_delivery_failure",
    }
    receipt = "mock:" + str(uuid4())
    assert settle(client, config, rid, attempt, receipt=receipt).status_code == 200
    item = read_payment(client, rid, pid)
    assert (
        item["state"] == "settled"
        and item["attempts"][0]["delivery_checks"][0]["structural_ok"] == 0
    )
    warnings = client.get(f"/api/v1/runs/{rid}/incidents").json()["items"]
    active = [i for i in warnings if i["state"] == "open" and i["kind"] == "policy_warning"]
    assert len(active) == 1 and active[0]["metrics"]["warning"] == "structural_delivery_failure"
    pid2, _, _ = gate(client, rid, clock, aid, tid)
    attempt2, _ = effect(client, rid, clock, aid, tid, pid2)
    assert settle(client, config, rid, attempt2, receipt=receipt).status_code == 409


def test_callback_disk_failure_rolls_back_receipt_and_settlement(payments, monkeypatch):
    from swarmcircuit_server.payments import service

    client, rid, clock, config = payments
    aid, tid = task(client, rid, clock)
    pid, _, _ = gate(client, rid, clock, aid, tid)
    attempt, _ = effect(client, rid, clock, aid, tid, pid)
    real_outbox = service.outbox

    def fail(conn, run, topic, entity):
        if topic == "payment.updated":
            raise sqlite3.OperationalError("simulated disk fault")
        return real_outbox(conn, run, topic, entity)

    monkeypatch.setattr(service, "outbox", fail)
    assert settle(client, config, rid, attempt).status_code == 503
    assert read_payment(client, rid, pid)["state"] == "unknown"
    with client.app.state.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM mock_authority_callbacks").fetchone()[0] == 0
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM run_events WHERE event_kind='payment.mock_settled' "
                "AND trust_class='simulation_truth'"
            ).fetchone()[0]
            == 0
        )


def test_payment_and_approval_read_pagination_and_scope(payments):
    client, rid, clock, config = payments
    for _ in range(3):
        pending_gate(client, rid, clock, fingerprint="sha256:" + uuid4().hex + uuid4().hex)
    for route in ("payments", "approvals"):
        seen, cursor = [], None
        while True:
            page = client.get(
                f"/api/v1/runs/{rid}/{route}",
                params={"limit": 1, **({"cursor": cursor} if cursor else {})},
            ).json()
            seen.extend(
                i["payment_intent_id" if route == "payments" else "approval_id"]
                for i in page["items"]
            )
            cursor = page["next_cursor"]
            if not cursor:
                break
        assert len(seen) == len(set(seen)) == 3
        assert client.get(f"/api/v1/runs/{uuid4()}/{route}").status_code == 404
        assert (
            client.get(f"/api/v1/runs/{rid}/{route}", params={"cursor": "bad"}).status_code == 422
        )


def test_late_deny_rejects_already_dispatched_resume(payments):
    client, rid, clock, config = payments
    aid, tid, apid, pid = pending_gate(client, rid, clock)
    session, _ = register(client, rid)
    enter(client, session, tid)
    held, _ = queue(client, config, rid, session, tid)
    poll(client, session)
    ack(client, session, held.json()["command_id"])
    assert resolve(client, config, rid, apid).status_code == 200
    resumed, _ = queue(client, config, rid, session, tid, kind="resume_task")
    assert resumed.status_code == 202
    poll(client, session)
    assert (
        gate(client, rid, clock, aid, tid, pid=pid, apid=apid, decision="deny")[2].json()[
            "accepted"
        ]
        == 1
    )
    assert ack(client, session, resumed.json()["command_id"])[0].status_code == 409
    assert state(client, rid, tid) == "held"


def test_mock_approval_cannot_retroactively_authorize_an_unapproved_effect(payments):
    client, rid, clock, config = payments
    aid, tid, apid, pid = pending_gate(client, rid, clock)
    attempt, result = effect(client, rid, clock, aid, tid, pid)
    assert result.json()["accepted"] == 1
    assert resolve(client, config, rid, apid).status_code == 409
    assert settle(client, config, rid, attempt).status_code == 409
    assert read_payment(client, rid, pid)["state"] == "unknown"


def test_same_millisecond_delivery_updates_use_ingestion_order(payments, monkeypatch):
    from swarmcircuit_server.ingest import events

    client, rid, clock, _ = payments
    aid, tid = task(client, rid, clock)
    pid, _, _ = gate(client, rid, clock, aid, tid)
    attempt = str(uuid4())
    monkeypatch.setattr(events, "now_ms", clock)
    envelopes = []
    for result, eid in [
        (False, "ffffffff-ffff-4fff-8fff-ffffffffffff"),
        (True, "00000000-0000-4000-8000-000000000001"),
    ]:
        envelope = event(
            "payment.delivery_checked",
            aid=aid,
            tid=tid,
            timestamp=clock(),
            payload={
                "payment_intent_id": pid,
                "payment_attempt_id": attempt,
                "integration_version": "0.2.1",
                "structural_ok": result,
                "reason_code": "structural_ok" if result else "structural_failure",
            },
        )
        envelope["event_id"] = eid
        envelopes.append(envelope)
    assert append(client, rid, envelopes).json()["accepted"] == 2
    warnings = client.get(f"/api/v1/runs/{rid}/incidents").json()["items"]
    assert all(i["metrics"].get("warning") != "structural_delivery_failure" for i in warnings)
    assert len(read_payment(client, rid, pid)["attempts"][0]["delivery_checks"]) == 2
