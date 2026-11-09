import sqlite3
from dataclasses import replace
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from swarmcircuit import SwarmCircuit
from swarmcircuit_server.app import create_app
from swarmcircuit_server.detectors import service
from swarmcircuit_server.detectors.rules import DetectorPolicy, strongly_connected

from examples.stalled_dependency import BASE_MS, run_scenario
from tests.conftest import append, event
from tests.test_otlp import export_fixture, post_binary


class Clock:
    value = BASE_MS

    def __call__(self):
        return self.value


@pytest.fixture
def observation(settings):
    config = replace(settings, detector_interval_seconds=0)
    clock = Clock()
    with TestClient(
        create_app(config, detector_clock=clock),
        headers={"Authorization": f"Bearer {config.sdk_token}"},
    ) as client:
        rid = client.post(
            f"/api/v1/projects/{config.project_id}/runs",
            json={"name": "detection", "mode": "observe"},
        ).json()["run_id"]
        yield client, rid, clock


def task(client, rid, clock, *, deadline=None):
    aid, tid = str(uuid4()), str(uuid4())
    payload = {"external_task_key": tid, "title": "work"}
    if deadline is not None:
        payload["deadline_at_ms"] = deadline
    result = append(
        client,
        rid,
        [
            event(
                "agent.started",
                aid=aid,
                timestamp=clock(),
                payload={"external_agent_key": aid, "display_name": "agent"},
            ),
            event("task.created", aid=aid, tid=tid, timestamp=clock(), payload=payload),
            event("task.started", aid=aid, tid=tid, timestamp=clock()),
        ],
    )
    assert result.json()["accepted"] == 3, result.text
    return aid, tid


def retry(client, rid, clock, aid, tid, attempt, lineage="action"):
    e = event(
        "task.retry_requested",
        aid=aid,
        tid=tid,
        timestamp=clock(),
        payload={"attempt_no": attempt, "retry_of": lineage},
    )
    result = append(client, rid, [e])
    assert result.json()["accepted"] == 1, result.text
    return e


def approval(client, rid, clock, aid, tid, apid, key="same-scope"):
    e = event(
        "approval.requested",
        aid=aid,
        tid=tid,
        timestamp=clock(),
        approval_id=apid,
        payload={"canonical_approval_key": key, "action_fingerprint": key},
    )
    assert append(client, rid, [e]).json()["accepted"] == 1
    return e


def dependency(client, rid, clock, aid, blocked, prerequisite, relation="depends_on"):
    e = event(
        "task.dependency_added",
        aid=aid,
        tid=blocked,
        timestamp=clock(),
        payload={"prerequisite_task_id": prerequisite, "relation_kind": relation},
    )
    assert append(client, rid, [e]).json()["accepted"] == 1
    return e


def incidents(client, rid, kind=None, state=None):
    result = client.get(f"/api/v1/runs/{rid}/incidents")
    assert result.status_code == 200, result.text
    return [
        i
        for i in result.json()["items"]
        if (kind is None or i["kind"] == kind) and (state is None or i["state"] == state)
    ]


def test_approval_storm_threshold_evidence_and_dedup(observation):
    client, rid, clock = observation
    aid, tid = task(client, rid, clock)
    apid = str(uuid4())
    evidence = [approval(client, rid, clock, aid, tid, apid) for _ in range(3)]
    assert incidents(client, rid, "approval_storm") == []  # Two duplicates; threshold is three.
    evidence.append(approval(client, rid, clock, aid, tid, apid))
    item = incidents(client, rid, "approval_storm")[0]
    assert item["state"] == "open"
    assert item["metrics"]["duplicate_requests"] == 3
    assert item["metrics"]["denominator"] == 1
    assert set(item["evidence_event_ids"]) == {e["event_id"] for e in evidence}
    assert item["affected_task_ids"] == [tid]
    assert item["policy"]["approval_window_ms"] == 30000
    assert item["trust_class"] == "derived" and not item["can_control"]
    assert append(client, rid, evidence).json()["duplicates"] == 4
    client.app.state.detector.scan_run(rid)
    assert incidents(client, rid, "approval_storm")[0]["revision"] == item["revision"]
    with client.app.state.db.read() as conn:
        assert (
            conn.execute("SELECT state FROM approvals WHERE approval_id=?", (apid,)).fetchone()[0]
            == "pending"
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM incident_evidence WHERE incident_id=?", (item["incident_id"],)
            ).fetchone()[0]
            == 4
        )


def test_distinct_approval_scopes_are_never_grouped(observation):
    client, rid, clock = observation
    aid, tid = task(client, rid, clock)
    for index in range(5):
        approval(client, rid, clock, aid, tid, str(uuid4()), key=f"scope-{index}")
    assert incidents(client, rid, "approval_storm") == []


def test_retry_denominator_and_strict_ratio_boundary(observation):
    client, rid, clock = observation
    a1, t1 = task(client, rid, clock)
    a2, t2 = task(client, rid, clock)
    retry(client, rid, clock, a1, t1, 2)
    retry(client, rid, clock, a2, t2, 99)  # Ordinal 99 is one request, not 98 attempts.
    assert incidents(client, rid, "retry_amplification") == []
    retry(client, rid, clock, a1, t1, 3)
    metrics = incidents(client, rid, "retry_amplification")[0]["metrics"]
    assert metrics["retry_requests"] == 3
    assert metrics["distinct_logical_actions"] == metrics["denominator"] == 2
    assert metrics["amplification"] == 1.5


def test_window_resolution_reopen_and_retained_history(observation):
    client, rid, clock = observation
    aid, tid = task(client, rid, clock)
    first = [retry(client, rid, clock, aid, tid, n) for n in (2, 3)]
    opened = incidents(client, rid, "retry_amplification")[0]
    clock.value += 60000
    client.app.state.detector.scan_once()
    resolved = incidents(client, rid, "retry_amplification")[0]
    assert resolved["state"] == "resolved"
    assert resolved["resolution_reason"] == "condition_no_longer_observed"
    assert resolved["resolved_at_ms"] == clock()
    latest = [retry(client, rid, clock, aid, tid, n) for n in (4, 5)]
    reopened = incidents(client, rid, "retry_amplification")[0]
    assert reopened["incident_id"] == opened["incident_id"]
    assert reopened["state"] == "open" and reopened["resolved_at_ms"] is None
    assert reopened["revision"] == 3
    assert set(reopened["evidence_event_ids"]) == {e["event_id"] for e in first + latest}
    assert set(reopened["current_evidence_event_ids"]) == {e["event_id"] for e in latest}
    with client.app.state.db.read() as conn:
        audits = conn.execute(
            "SELECT event_kind,trust_class FROM run_events WHERE trust_class='derived' "
            "ORDER BY occurred_at_ms,event_kind"
        ).fetchall()
        assert {a[0] for a in audits} >= {
            "incident.opened",
            "incident.resolved",
            "incident.reopened",
        }


def test_active_stall_without_new_events_and_progress_recovery(observation):
    client, rid, clock = observation
    aid, tid = task(client, rid, clock)
    clock.value += 60000
    client.app.state.detector.scan_once()
    stalled = incidents(client, rid, "task_stall")[0]
    assert stalled["metrics"]["trigger_at_ms"] == clock()
    assert stalled["affected_task_ids"] == [tid]
    # A real host progress signal resolves; a retry or arbitrary event does not.
    retry(client, rid, clock, aid, tid, 2)
    assert incidents(client, rid, "task_stall")[0]["state"] == "open"
    assert (
        append(client, rid, [event("task.progress", aid=aid, tid=tid, timestamp=clock())]).json()[
            "accepted"
        ]
        == 1
    )
    assert incidents(client, rid, "task_stall")[0]["state"] == "resolved"
    clock.value += 59999
    client.app.state.detector.scan_once()
    assert incidents(client, rid, "task_stall")[0]["state"] == "resolved"
    clock.value += 1
    client.app.state.detector.scan_once()
    assert incidents(client, rid, "task_stall")[0]["state"] == "open"
    assert (
        append(client, rid, [event("task.completed", aid=aid, tid=tid, timestamp=clock())]).json()[
            "accepted"
        ]
        == 1
    )
    assert incidents(client, rid, "task_stall")[0]["state"] == "resolved"


def test_declared_deadline_and_stale_or_unknown_progress(observation):
    client, rid, clock = observation
    aid, tid = task(client, rid, clock, deadline=clock() + 120000)
    clock.value += 60000
    client.app.state.detector.scan_once()
    assert incidents(client, rid, "task_stall") == []
    clock.value += 60000
    append(client, rid, [event("agent.says_progress", aid=aid, tid=tid, timestamp=clock())])
    assert incidents(client, rid, "task_stall")[0]["state"] == "open"
    append(client, rid, [event("task.progress", aid=aid, tid=tid, timestamp=BASE_MS + 1000)])
    assert incidents(client, rid, "task_stall")[0]["state"] == "open"


def test_human_wait_and_transitive_dependents_are_not_stalls(observation):
    client, rid, clock = observation
    a1, t1 = task(client, rid, clock, deadline=clock())
    a2, t2 = task(client, rid, clock, deadline=clock())
    a3, t3 = task(client, rid, clock, deadline=clock())
    apid = str(uuid4())
    approval(client, rid, clock, a1, t1, apid)
    append(
        client,
        rid,
        [event("task.waiting_for_approval", aid=a1, tid=t1, approval_id=apid, timestamp=clock())],
    )
    dependency(client, rid, clock, a2, t2, t1)
    dependency(client, rid, clock, a3, t3, t2)
    clock.value += 120000
    client.app.state.detector.scan_once()
    assert incidents(client, rid) == []
    assert client.get(f"/api/v1/runs/{rid}").json()["status"] == "waiting"


def test_explicit_cycle_and_completion_resolution(observation):
    client, rid, clock = observation
    a1, t1 = task(client, rid, clock)
    a2, t2 = task(client, rid, clock)
    d1 = dependency(client, rid, clock, a1, t1, t2)
    assert incidents(client, rid, "dependency_cycle") == []
    d2 = dependency(client, rid, clock, a2, t2, t1, relation="waits_for")
    item = incidents(client, rid, "dependency_cycle")[0]
    assert set(item["evidence_event_ids"]) == {d1["event_id"], d2["event_id"]}
    assert set(item["affected_task_ids"]) == {t1, t2}
    assert "not verified runtime deadlock" in item["uncertainty"]
    append(client, rid, [event("task.completed", aid=a1, tid=t1, timestamp=clock())])
    assert incidents(client, rid, "dependency_cycle")[0]["state"] == "resolved"


def test_message_and_span_cycles_are_not_task_deadlocks(observation):
    client, rid, clock = observation
    a1, t1 = task(client, rid, clock)
    a2, t2 = task(client, rid, clock)
    append(
        client,
        rid,
        [
            event("agent.handoff", aid=a1, tid=t1, timestamp=clock(), payload={"to_agent_id": a2}),
            event("agent.handoff", aid=a2, tid=t2, timestamp=clock(), payload={"to_agent_id": a1}),
        ],
    )
    payload = export_fixture(rid)
    span = payload.resource_spans[0].scope_spans[0].spans[0]
    span.parent_span_id = span.span_id
    span.events[0].name = "task.retry_requested"
    post_binary(client, payload)
    assert incidents(client, rid) == []


def test_cascade_requires_explicit_paths_and_preserves_independent_branch(observation):
    client, rid, clock = observation
    root_a, root = task(client, rid, clock)
    a1, t1 = task(client, rid, clock)
    a2, t2 = task(client, rid, clock)
    _, independent = task(client, rid, clock)
    apid = str(uuid4())
    origin = approval(client, rid, clock, root_a, root, apid)
    for a, t in ((a1, t1), (a2, t2)):
        for n in (2, 3):
            retry(client, rid, clock, a, t, n)
    assert incidents(client, rid, "cascade") == []
    d1 = dependency(client, rid, clock, a1, t1, root)
    d2 = dependency(client, rid, clock, a2, t2, t1)
    item = incidents(client, rid, "cascade")[0]
    assert set(item["affected_task_ids"]) == {root, t1, t2}
    assert independent not in item["affected_task_ids"]
    assert {origin["event_id"], d1["event_id"], d2["event_id"]} <= set(item["evidence_event_ids"])
    with client.app.state.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM control_commands").fetchone()[0] == 0
        assert (
            conn.execute("SELECT state FROM approvals WHERE approval_id=?", (apid,)).fetchone()[0]
            == "pending"
        )


def test_six_agent_ingestion_opens_explainable_incidents(observation, settings):
    client, _, clock = observation
    clock.value = BASE_MS + 10000
    with SwarmCircuit(settings.project_id, settings.sdk_token, client=client) as sdk:
        summary = run_scenario(sdk)
    items = incidents(client, summary["run_id"], state="open")
    assert {i["kind"] for i in items} == {"approval_storm", "retry_amplification", "cascade"}
    detail = client.get(f"/api/v1/runs/{summary['run_id']}").json()
    assert detail["open_incident_count"] == 3
    graph = client.get(f"/api/v1/runs/{summary['run_id']}/graph").json()
    assert set(graph["incident_ids"]) == {i["incident_id"] for i in items}
    independent = next(n for n in graph["nodes"] if n["id"] == summary["independent_task_id"])
    assert independent["incident_ids"] == [] and independent["state"] == "completed"
    for item in items:
        assert item["evidence_event_ids"]
        with client.app.state.db.read() as conn:
            for eid in item["evidence_event_ids"]:
                row = conn.execute(
                    "SELECT run_id,trust_class FROM run_events WHERE event_id=?", (eid,)
                ).fetchone()
                assert tuple(row) == (summary["run_id"], "sdk_observation")


def test_detector_failure_never_rolls_back_accepted_source_evidence(observation, monkeypatch):
    client, rid, clock = observation
    aid, tid = task(client, rid, clock)
    retry(client, rid, clock, aid, tid, 2)
    original = service._audit

    def fail(*args):
        raise sqlite3.OperationalError("simulated incident persistence failure")

    monkeypatch.setattr(service, "_audit", fail)
    e = retry(client, rid, clock, aid, tid, 3)
    assert incidents(client, rid) == []
    assert client.get("/api/v1/health").json()["status"] == "degraded"
    with client.app.state.db.read() as conn:
        assert conn.execute(
            "SELECT 1 FROM run_events WHERE event_id=?", (e["event_id"],)
        ).fetchone()
        assert conn.execute("SELECT COUNT(*) FROM incident_evidence").fetchone()[0] == 0
    monkeypatch.setattr(service, "_audit", original)
    client.app.state.detector.scan_once()
    assert incidents(client, rid, "retry_amplification")[0]["state"] == "open"
    assert client.get("/api/v1/health").json()["status"] == "ready"


@pytest.mark.parametrize("state", ["acknowledged", "suppressed"])
def test_reconciliation_preserves_operator_states(observation, state):
    client, rid, clock = observation
    aid, tid = task(client, rid, clock)
    for n in (2, 3):
        retry(client, rid, clock, aid, tid, n)
    item = incidents(client, rid, "retry_amplification")[0]
    client.app.state.db.write(
        lambda conn: conn.execute(
            "UPDATE incidents SET state=? WHERE incident_id=?", (state, item["incident_id"])
        )
    )
    retry(client, rid, clock, aid, tid, 4)
    assert incidents(client, rid, "retry_amplification")[0]["state"] == state
    clock.value += 60000
    client.app.state.detector.scan_once()
    assert incidents(client, rid, "retry_amplification")[0]["state"] == (
        "suppressed" if state == "suppressed" else "resolved"
    )


def test_read_auth_isolation_and_no_incident_mutation_endpoint(observation, settings):
    client, rid, _ = observation
    assert (
        client.get(f"/api/v1/runs/{rid}/incidents", headers={"Authorization": ""}).status_code
        == 401
    )
    assert (
        client.get(
            f"/api/v1/runs/{rid}/incidents",
            headers={"Authorization": f"Bearer {settings.operator_token}"},
        ).status_code
        == 200
    )
    assert client.get(f"/api/v1/runs/{uuid4()}/incidents").status_code == 404
    assert (
        client.post(f"/api/v1/runs/{rid}/incidents", json={"state": "resolved"}).status_code == 405
    )


def test_timer_finds_stall_without_new_ingestion_and_stops_cleanly(settings):
    config = replace(settings, detector_interval_seconds=0.01)
    clock, scanned = Clock(), Event()
    with TestClient(
        create_app(config, detector_clock=clock),
        headers={"Authorization": f"Bearer {config.sdk_token}"},
    ) as client:
        rid = client.post(
            f"/api/v1/projects/{config.project_id}/runs", json={"name": "timer", "mode": "observe"}
        ).json()["run_id"]
        task(client, rid, clock)
        detector = client.app.state.detector
        original = detector.scan_run

        def watch(*args):
            result = original(*args)
            if len(args) > 1 and args[1] >= BASE_MS + 60000:
                scanned.set()
            return result

        detector.scan_run = watch
        clock.value += 60000
        assert scanned.wait(2)
        assert incidents(client, rid, "task_stall")[0]["state"] == "open"
    assert not detector.thread.is_alive()


def test_scc_handles_deep_graph_without_recursion():
    nodes = {str(i) for i in range(2000)}
    edges = [(str(i), str(i + 1)) for i in range(1999)] + [("1999", "0")]
    assert strongly_connected(nodes, edges) == [nodes]


@pytest.mark.parametrize(
    "kwargs",
    [{"stall_timeout_ms": 0}, {"retry_ratio_threshold": float("nan")}, {"approval_window_ms": -1}],
)
def test_policy_rejects_invalid_thresholds(kwargs):
    with pytest.raises(ValueError):
        DetectorPolicy(**kwargs)


def test_policy_change_is_versioned_and_resolves_superseded_findings(observation):
    client, rid, clock = observation
    aid, tid = task(client, rid, clock)
    for n in (2, 3):
        retry(client, rid, clock, aid, tid, n)
    previous = incidents(client, rid, "retry_amplification")[0]
    detector = client.app.state.detector
    detector.policy = replace(detector.policy, retry_ratio_threshold=100)
    detector.scan_once()
    resolved = incidents(client, rid, "retry_amplification")[0]
    assert resolved["state"] == "resolved"
    assert resolved["resolution_reason"] == "policy_replaced"
    assert resolved["policy_sha256"] == previous["policy_sha256"]
    with client.app.state.db.read() as conn:
        policies = conn.execute(
            "SELECT revision,auto_apply FROM control_policies ORDER BY revision"
        ).fetchall()
        assert [tuple(r) for r in policies] == [(1, 0), (2, 0)]


def test_incident_recovery_after_restart_and_clock_regression(settings):
    config, clock = replace(settings, detector_interval_seconds=0), Clock()
    headers = {"Authorization": f"Bearer {config.sdk_token}"}
    with TestClient(create_app(config, detector_clock=clock), headers=headers) as first:
        rid = first.post(
            f"/api/v1/projects/{config.project_id}/runs",
            json={"name": "restart", "mode": "observe"},
        ).json()["run_id"]
        aid, tid = task(first, rid, clock)
        for n in (2, 3):
            retry(first, rid, clock, aid, tid, n)
        before = incidents(first, rid, "retry_amplification")[0]
    clock.value += 60000
    with TestClient(create_app(config, detector_clock=clock), headers=headers) as second:
        second.app.state.detector.scan_once()
        after = incidents(second, rid, "retry_amplification")[0]
        assert after["state"] == "resolved"
        assert after["incident_id"] == before["incident_id"]
        assert after["evidence_event_ids"] == before["evidence_event_ids"]
        clock.value -= 60000
        second.app.state.detector.scan_once()
        assert incidents(second, rid, "retry_amplification")[0]["revision"] == after["revision"]


def test_unknown_incident_events_cannot_mutate_findings(observation):
    client, rid, clock = observation
    aid, tid = task(client, rid, clock)
    for n in (2, 3):
        retry(client, rid, clock, aid, tid, n)
    before = incidents(client, rid, "retry_amplification")[0]
    append(
        client,
        rid,
        [
            event(
                "incident.resolved",
                timestamp=clock(),
                payload={"incident_id": before["incident_id"], "state": "resolved"},
            )
        ],
    )
    after = incidents(client, rid, "retry_amplification")[0]
    assert after["state"] == "open" and after["revision"] == before["revision"]


def test_inferred_or_cross_run_evidence_never_establishes_a_cycle(observation, settings):
    client, rid, clock = observation
    a1, t1 = task(client, rid, clock)
    a2, t2 = task(client, rid, clock)
    dependency(client, rid, clock, a1, t1, t2)
    other = client.post(
        f"/api/v1/projects/{settings.project_id}/runs", json={"name": "other", "mode": "observe"}
    ).json()["run_id"]
    oa, ot = task(client, other, clock)
    foreign = event("task.progress", aid=oa, tid=ot, timestamp=clock())
    assert append(client, other, [foreign]).json()["accepted"] == 1
    client.app.state.db.write(
        lambda conn: conn.execute(
            "INSERT INTO task_dependencies VALUES (?,?,?,?,'depends_on',1,?,?)",
            (str(uuid4()), rid, t2, t1, foreign["event_id"], clock()),
        )
    )
    client.app.state.detector.scan_once()
    assert incidents(client, rid, "dependency_cycle") == []
