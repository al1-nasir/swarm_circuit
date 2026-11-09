"""Readable summaries preserve authority and discover canonical history in a fresh client."""

import json
from uuid import uuid4

import pytest

from tests.conftest import append, event
from tests.test_control import ack, enter, poll, register
from tests.test_control import controlled as control_fixture
from tests.test_detectors import approval, dependency, task


@pytest.fixture
def insight_controlled(settings):
    yield from control_fixture.__wrapped__(settings)


def test_workspace_counts_are_project_wide_and_diagnostics_are_separate(client, settings):
    project = settings.project_id
    names = ["First real workflow", "Second real workflow", "Studio gateway verification"]
    ids = [
        client.post(
            f"/api/v1/projects/{project}/runs",
            json={
                "name": name,
                "mode": "observe",
            },
        ).json()["run_id"]
        for name in names
    ]
    response = client.get(f"/api/v1/projects/{project}/workspace?limit=1")
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    data = response.json()
    assert data["counts"]["recorded_workflows"] == 2
    assert data["counts"]["diagnostic_workflows"] == 1
    assert data["counts"]["connected_workers"] == 0
    assert data["counts"]["recorded_running"] == 0
    assert len(data["items"]) == 1 and data["items"][0]["run"]["run_id"] in ids[:2]
    assert data["items"][0]["connection"]["state"] == "not_integrated"
    assert data["items"][0]["headline"] == "Recorded workflow"
    everything = client.get(f"/api/v1/projects/{project}/workspace?include_diagnostics=true").json()
    assert len(everything["items"]) == 3
    assert everything["counts"] == data["counts"]
    ordinary = client.get(
        f"/api/v1/projects/{project}/runs?include_diagnostics=false&limit=1"
    ).json()
    assert ordinary["items"][0]["run_id"] in ids[:2]
    older = client.get(
        f"/api/v1/projects/{project}/runs?include_diagnostics=false&limit=1"
        f"&cursor={ordinary['next_cursor']}"
    ).json()
    assert older["items"][0]["run_id"] in ids[:2]
    assert older["items"][0]["run_id"] != ordinary["items"][0]["run_id"]
    assert not older["next_cursor"]
    assert client.get(f"/api/v1/projects/{uuid4()}/workspace").status_code == 404
    assert (
        client.get(
            f"/api/v1/projects/{project}/workspace", headers={"Authorization": ""}
        ).status_code
        == 401
    )


def test_brief_counts_total_progress_and_separates_offline_history_from_liveness(
    insight_controlled,
):
    client, rid, clock, config = insight_controlled
    aid, root = task(client, rid, clock)
    dependent_aid, dependent = task(client, rid, clock)
    public_aid, public = task(client, rid, clock)
    dependency(client, rid, clock, dependent_aid, dependent, root)
    gate = str(uuid4())
    approval(client, rid, clock, aid, root, gate)
    append(client, rid, [event("task.completed", aid=public_aid, tid=public, timestamp=clock())])
    session, registration = register(client, rid)
    enter(client, session, root)
    enter(client, session, dependent)
    body = {"approval_id": gate, "reason": "Review the declared permission branch", "apply": True}
    saved = client.post(
        f"/api/v1/runs/{rid}/backpressure",
        json=body,
        headers={
            "Authorization": f"Bearer {config.operator_token}",
            "Idempotency-Key": str(uuid4()),
        },
    )
    assert saved.status_code == 200, saved.text
    poll(client, session)
    for cmd in saved.json()["commands"]:
        assert ack(client, session, cmd["command_id"])[0].status_code == 200
    summary = client.get(f"/api/v1/runs/{rid}/brief")
    assert summary.status_code == 200, summary.text
    brief = summary.json()
    assert brief["progress"]["completed"] == 1 and brief["progress"]["total"] == 3
    assert set(brief["affected_task_ids"]) == {root, dependent}
    assert brief["unaffected_task_ids"] == [public]
    assert brief["pending_approvals"] == 1
    assert brief["connection"]["connected_workers"] == 1
    assert brief["last_confirmation"]["host_connected"]
    assert "permission" in brief["headline"]
    clock.value += config.runtime_heartbeat_timeout_ms + 1
    offline = client.get(f"/api/v1/runs/{rid}/brief").json()
    assert offline["connection"]["state"] == "offline"
    assert offline["connection"]["connected_workers"] == 0
    assert not offline["last_confirmation"]["host_connected"]
    assert offline["last_confirmation"]["at_ms"] == brief["last_confirmation"]["at_ms"]
    assert offline["run"]["status"] == brief["run"]["status"]
    workspace = client.get(f"/api/v1/projects/{config.project_id}/workspace").json()
    assert workspace["counts"]["connected_workers"] == 0
    assert workspace["counts"]["needs_attention"] == 1
    for text in (summary.text, json.dumps(offline)):
        assert session["session_token"] not in text
        assert registration["client_nonce"] not in text
    assert client.get(f"/api/v1/runs/{uuid4()}/brief").status_code == 404
    assert client.get(f"/api/v1/runs/{rid}/brief", headers={"Authorization": ""}).status_code == 401


def test_policy_history_is_discoverable_without_a_local_intent_and_returns_current_commands(
    insight_controlled,
):
    client, rid, clock, config = insight_controlled
    session, registration = register(client, rid)
    saved = []
    for _ in range(2):
        aid, tid = task(client, rid, clock)
        gate = str(uuid4())
        approval(client, rid, clock, aid, tid, gate, key=str(uuid4()))
        enter(client, session, tid)
        key = str(uuid4())
        request = client.post(
            f"/api/v1/runs/{rid}/backpressure",
            json={"approval_id": gate, "reason": "Reviewed local branch", "apply": True},
            headers={"Authorization": f"Bearer {config.operator_token}", "Idempotency-Key": key},
        )
        assert request.status_code == 200, request.text
        saved.append((key, request.json()))
        clock.value += 1
    poll(client, session)
    latest_cid = saved[-1][1]["command_ids"][0]
    assert ack(client, session, latest_cid)[0].status_code == 200
    page = client.get(f"/api/v1/runs/{rid}/backpressure/history?limit=1")
    assert page.status_code == 200, page.text
    assert page.json()["unconfirmed_count"] == 1
    item = page.json()["items"][0]
    assert item["idempotency_key"] == saved[-1][0]
    assert item["policy_request_id"] == saved[-1][1]["policy_request_id"]
    assert item["commands"][0]["state"] == "applied"
    assert item["commands"][0]["acknowledgements"][0]["result"] == "applied"
    older = client.get(
        f"/api/v1/runs/{rid}/backpressure/history?limit=1&cursor={page.json()['next_cursor']}"
    ).json()
    assert older["items"][0]["idempotency_key"] == saved[0][0]
    assert older["next_cursor"] is None
    assert session["session_token"] not in page.text
    assert registration["client_nonce"] not in page.text
    assert "token_sha256" not in page.text
    assert client.get(f"/api/v1/runs/{uuid4()}/backpressure/history").status_code == 404
    assert (
        client.get(
            f"/api/v1/runs/{rid}/backpressure/history", headers={"Authorization": ""}
        ).status_code
        == 401
    )
    assert client.get(f"/api/v1/runs/{rid}/backpressure/history?cursor=broken").status_code == 422


def test_classification_handles_explicit_metadata_without_guessing_every_test_word(
    client, settings
):
    project = settings.project_id
    rid = client.post(
        f"/api/v1/projects/{project}/runs",
        json={"name": "Test a real customer workflow", "mode": "observe"},
    ).json()["run_id"]
    assert client.get(f"/api/v1/runs/{rid}/brief").json()["classification"] == "workflow"
    # Arbitrary caller metadata is not a classification authority or a reason to fail a read.
    client.app.state.db.write(
        lambda conn: conn.execute(
            "UPDATE workflow_runs SET metadata_json=? WHERE run_id=?",
            (json.dumps({"kind": {"unrecognized": "metadata"}}), rid),
        )
    )
    assert client.get(f"/api/v1/runs/{rid}/brief").json()["classification"] == "workflow"

    client.app.state.db.write(
        lambda conn: conn.execute(
            "UPDATE workflow_runs SET metadata_json=? WHERE run_id=?",
            (json.dumps({"diagnostic": True}), rid),
        )
    )
    assert client.get(f"/api/v1/runs/{rid}/brief").json()["classification"] == "diagnostic"


def test_cancelled_pending_approvals_are_historical_but_open_findings_still_need_review(
    insight_controlled,
):
    client, rid, clock, config = insight_controlled
    aid, tid = task(client, rid, clock)
    gate = str(uuid4())
    approval(client, rid, clock, aid, tid, gate)
    client.app.state.db.write(
        lambda conn: conn.execute(
            "UPDATE workflow_runs SET status='cancelled',ended_at_ms=? WHERE run_id=?",
            (clock(), rid),
        )
    )
    summary = client.get(f"/api/v1/runs/{rid}/brief").json()
    assert summary["pending_approvals"] == 1
    assert summary["headline"] == "This workflow was cancelled"
    assert "historical" in summary["explanation"]
    assert "Review permission" not in summary["next_action"]["label"]
    workspace = client.get(f"/api/v1/projects/{config.project_id}/workspace").json()
    assert workspace["counts"]["needs_attention"] == 0
    for _ in range(3):
        approval(client, rid, clock, aid, tid, gate)
    summary = client.get(f"/api/v1/runs/{rid}/brief").json()
    assert summary["headline"] == "Workflow ended with findings to review"
    assert summary["run"]["status"] == "cancelled"
    assert summary["run"]["ended_at_ms"] == clock()
    assert "1 open finding remains" in summary["explanation"]
    assert summary["next_action"]["href"] == f"/runs/{rid}?tab=incidents"
    workspace = client.get(f"/api/v1/projects/{config.project_id}/workspace").json()
    assert workspace["counts"]["needs_attention"] == 1
    assert workspace["attention"][0]["next_action"]["href"].endswith("?tab=incidents")


def test_walkthrough_destination_requires_an_owned_session_not_host_metadata(insight_controlled):
    client, rid, clock, config = insight_controlled
    forged_id, owned_id = str(uuid4()), str(uuid4())
    client.app.state.db.write(
        lambda conn: conn.execute(
            "UPDATE workflow_runs SET metadata_json=?,status='cancelled' WHERE run_id=?",
            (json.dumps({"guided_demo_id": forged_id, "guided_demo": True}), rid),
        )
    )
    summary = client.get(f"/api/v1/runs/{rid}/brief").json()
    assert summary["guided_demo"] is None
    assert summary["next_action"]["href"].startswith(f"/runs/{rid}")
    client.app.state.db.write(
        lambda conn: conn.execute(
            "INSERT INTO guided_demo_sessions(demo_id,project_id,run_id,idempotency_key,state,"
            "created_at_ms,updated_at_ms,expires_at_ms) VALUES (?,?,?,?,'interrupted',?,?,?)",
            (owned_id, config.project_id, rid, str(uuid4()), clock(), clock(), clock() + 600_000),
        )
    )
    summary = client.get(f"/api/v1/runs/{rid}/brief").json()
    assert summary["guided_demo"] == {"demo_id": owned_id, "state": "interrupted"}
    assert summary["headline"] == "This walkthrough was interrupted"
    assert summary["next_action"]["href"] == f"/demo?demo={owned_id}"
    assert forged_id not in summary["next_action"]["href"]
