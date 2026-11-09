import hashlib
import time
from threading import Event
from uuid import uuid4

import httpx
import pytest
from swarmcircuit_server.demo.fixtures import analyze
from swarmcircuit_server.demo.service import DemoManager
from swarmcircuit_server.errors import Problem


class Bridge:
    """Exercise the actual SDK against ASGI routes, never an external socket."""

    def __init__(self, client):
        self.client = client

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def request(self, method, url, **kwargs):
        return self.client.request(method, url, **kwargs)


@pytest.fixture
def guided(client, settings, monkeypatch):
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: Bridge(client))
    yield client, settings, client.app.state.demo
    client.app.state.demo.close()


def headers(settings, key=None):
    return {
        "Authorization": "Bearer " + settings.operator_token,
        **({"Idempotency-Key": key or str(uuid4())} if key is not False else {}),
    }


def start(client, settings, key=None):
    response = client.post(
        f"/api/v1/projects/{settings.project_id}/demos",
        json={},
        headers=headers(settings, key),
    )
    assert response.status_code == 201, response.text
    return response.json()


def wait_for(client, demo_id, predicate):
    deadline = time.monotonic() + 20
    value = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/demos/{demo_id}")
        assert response.status_code == 200, response.text
        value = response.json()
        if predicate(value):
            return value
        assert value["state"] != "failed", value
        time.sleep(0.05)
    pytest.fail(f"Guided workflow did not reach the expected state: {value}")


def test_guided_workflow_creates_useful_independent_output_then_real_sdk_completion(
    guided, monkeypatch
):
    client, settings, manager = guided
    reads = []

    def protected_read():
        reads.append(True)
        return analyze()

    monkeypatch.setattr("swarmcircuit_server.demo.worker.analyze", protected_read)
    key = str(uuid4())
    demo = start(client, settings, key)
    did = demo["demo_id"]
    pending = wait_for(client, did, lambda d: d["public_completed"])
    assert pending["permission"] == "pending"
    assert pending["progress"] == {"completed": 2, "total": 6, "waiting": 4}
    assert pending["protected_effects"] == 0
    assert reads == []
    assert pending["request_count"] == 1
    assert pending["worker_connected"]
    assert pending["model_calls"] == 0
    graph = client.get(f"/api/v1/runs/{pending['run_id']}/graph?view=task").json()
    assert sum(n["state"] == "waiting_for_human" for n in graph["nodes"]) == 1
    summary = client.get(f"/api/v1/runs/{pending['run_id']}/brief").json()
    assert summary["progress"]["waiting"] == 4
    assert summary["guided_demo"] == {"demo_id": did, "state": "waiting"}
    assert summary["next_action"]["href"] == f"/demo?demo={did}"
    assert client.get(f"/api/v1/runs/{pending['run_id']}/incidents").json()["items"] == []
    assert client.get(f"/api/v1/runs/{pending['run_id']}").json()["status"] == "waiting"
    public = client.get(f"/api/v1/demos/{did}/artifacts/public-findings")
    assert public.status_code == 200
    assert "These notes use no restricted data" in public.text
    assert public.headers["cache-control"] == "no-store"
    sha = next(a["sha256"] for a in pending["artifacts"] if a["slug"] == "public-findings")
    assert hashlib.sha256(public.content).hexdigest() == sha
    assert client.get(f"/api/v1/demos/{did}/artifacts/final-brief").status_code == 404
    assert start(client, settings, key)["demo_id"] == did
    assert (
        client.get(f"/api/v1/projects/{settings.project_id}/demos?key={key}").json()["items"][0][
            "demo_id"
        ]
        == did
    )
    response = client.post(
        f"/api/v1/demos/{did}/decision",
        headers=headers(settings, "approved-" + did),
        json={"decision": "approved", "reason": "Allow this synthetic dataset only"},
    )
    assert response.status_code == 200, response.text
    done = wait_for(client, did, lambda d: d["state"] == "completed")
    assert done["progress"]["completed"] == 6
    assert done["protected_effects"] == 4
    assert len(reads) == 4
    assert done["permission"] == "approved"
    deadline = time.monotonic() + 5
    while did in manager.workers and time.monotonic() < deadline:
        time.sleep(0.01)
    assert did not in manager.workers
    workspace = client.get(f"/api/v1/projects/{settings.project_id}/workspace").json()
    assert workspace["counts"]["connected_workers"] == 0
    summary = client.get(f"/api/v1/runs/{done['run_id']}/brief").json()
    assert summary["next_action"] == {"label": "Read sales brief", "href": f"/demo?demo={did}"}
    assert {a["slug"] for a in done["artifacts"]} == {
        "public-findings",
        "dataset-analysis",
        "final-brief",
    }
    brief = client.get(f"/api/v1/demos/{did}/artifacts/final-brief")
    assert "39.15%" in brief.text and "Local sample data" in brief.text
    with manager.db.read() as conn:
        assert (
            conn.execute(
                "SELECT status FROM workflow_runs WHERE run_id=?", (done["run_id"],)
            ).fetchone()[0]
            == "completed"
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM control_commands WHERE run_id=?", (done["run_id"],)
            ).fetchone()[0]
            == 0
        )
    # This proves guards alone quietly wait; no pause savings claim is fabricated.


def test_guided_denial_never_executes_protected_work_and_keeps_public_output(guided):
    client, settings, manager = guided
    demo = start(client, settings)
    did = demo["demo_id"]
    wait_for(client, did, lambda d: d["approval_id"] is not None)
    key = str(uuid4())
    body = {"decision": "denied", "reason": "Decline the synthetic access request"}
    first = client.post(f"/api/v1/demos/{did}/decision", json=body, headers=headers(settings, key))
    assert first.status_code == 200, first.text
    denied = wait_for(client, did, lambda d: d["state"] == "denied")
    assert denied["public_completed"]
    assert denied["protected_effects"] == 0
    assert len(denied["artifacts"]) == 1
    assert (
        client.post(
            f"/api/v1/demos/{did}/decision", json=body, headers=headers(settings, key)
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/demos/{did}/decision",
            json={"decision": "approved", "reason": "Changed payload"},
            headers=headers(settings, key),
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/demos/{did}/decision",
            json={"decision": "approved", "reason": "New key cannot override denial"},
            headers=headers(settings),
        ).status_code
        == 409
    )
    with manager.db.read() as conn:
        assert (
            conn.execute(
                "SELECT state FROM approvals WHERE approval_id=?", (denied["approval_id"],)
            ).fetchone()[0]
            == "denied"
        )
        assert (
            conn.execute(
                "SELECT status FROM workflow_runs WHERE run_id=?", (denied["run_id"],)
            ).fetchone()[0]
            == "cancelled"
        )


def test_guided_scope_limits_active_bound_and_reconciliation(guided):
    client, settings, manager = guided
    did = start(client, settings)["demo_id"]
    wait_for(client, did, lambda d: d["approval_id"] is not None)
    response = client.post(
        f"/api/v1/projects/{settings.project_id}/demos", json={}, headers=headers(settings)
    )
    assert response.status_code == 409
    assert client.get(f"/api/v1/projects/{uuid4()}/demos").status_code == 404
    assert client.get(f"/api/v1/demos/{uuid4()}").status_code == 404
    assert client.get(f"/api/v1/demos/{did}/artifacts/unknown").status_code == 404
    assert client.get(f"/api/v1/projects/{settings.project_id}/demos?key=unknown-key").json() == {
        "items": []
    }
    assert (
        client.post(
            f"/api/v1/demos/{did}/decision",
            json={"decision": "approved", "reason": " ", "run_id": str(uuid4())},
            headers=headers(settings),
        ).status_code
        == 422
    )
    with pytest.raises(ValueError):
        DemoManager(manager.db, settings, "https://external.example")
    with pytest.raises(ValueError):
        DemoManager(manager.db, settings, "http://user:secret@127.0.0.1:8000")


def test_guided_restart_retains_artifacts_and_stops_old_work(guided):
    client, settings, manager = guided
    did = start(client, settings)["demo_id"]
    wait_for(client, did, lambda d: d["public_completed"])
    manager.close()
    recovered = DemoManager(manager.db, settings, "http://127.0.0.1:8000")
    recovered.start()
    result = recovered.status(did)
    assert result["state"] == "interrupted"
    assert not result["worker_connected"]
    assert result["protected_effects"] == 0
    assert recovered.get_artifact(did, "public-findings")["content"].startswith(
        "# Reading the sales brief"
    )
    with pytest.raises(Problem):
        recovered.decision(did, "approved", "A restart must not release old work", str(uuid4()))
    recovered.close()


def test_fixture_math_has_a_concrete_checked_outcome():
    assert analyze() == {
        "first_quarter_revenue": "120000",
        "last_quarter_revenue": "166980",
        "revenue_growth_percent": "39.15",
        "customer_quarters": 1800,
        "quarters": 4,
    }


def test_guided_actions_require_operator_and_exact_project(guided):
    client, settings, _ = guided
    project = settings.project_id
    assert client.post(f"/api/v1/projects/{project}/demos", json={}).status_code == 403
    assert (
        client.get(f"/api/v1/projects/{project}/demos", headers={"Authorization": ""}).status_code
        == 401
    )
    assert (
        client.post(
            f"/api/v1/projects/{uuid4()}/demos", json={}, headers=headers(settings)
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/projects/{project}/demos", json={}, headers=headers(settings, False)
        ).status_code
        == 422
    )


def test_demo_permission_does_not_resume_operator_pauses(guided):
    client, settings, manager = guided
    demo = start(client, settings)
    did = demo["demo_id"]
    pending = wait_for(client, did, lambda d: d["public_completed"])
    request = {
        "approval_id": pending["approval_id"],
        "reason": "Keep the sample branch paused during review",
    }
    preview = client.post(
        f"/api/v1/runs/{pending['run_id']}/backpressure", json=request, headers=headers(settings)
    )
    assert preview.status_code == 200, preview.text
    assert len(preview.json()["targets"]) == 4
    applied = client.post(
        f"/api/v1/runs/{pending['run_id']}/backpressure",
        json={
            **request,
            "apply": True,
            "expected_preview_sha256": preview.json()["preview_sha256"],
        },
        headers=headers(settings),
    )
    assert applied.status_code == 200, applied.text
    held = wait_for(client, did, lambda d: d["active_holds"] == 4)
    assert held["protected_effects"] == 0
    granted = client.post(
        f"/api/v1/demos/{did}/decision",
        json={
            "decision": "approved",
            "reason": "Grant sample permission separately from operator pauses",
        },
        headers=headers(settings),
    )
    assert granted.status_code == 200, granted.text
    time.sleep(0.3)
    still_held = client.get(f"/api/v1/demos/{did}").json()
    assert still_held["permission"] == "approved"
    assert still_held["active_holds"] == 4
    assert still_held["protected_effects"] == 0
    assert still_held["progress"]["completed"] == 2
    with manager.db.read() as conn:
        commands = conn.execute(
            "SELECT state FROM control_commands WHERE run_id=?", (pending["run_id"],)
        ).fetchall()
        assert len(commands) == 4 and all(r[0] == "applied" for r in commands)

    summary = client.get(f"/api/v1/runs/{pending['run_id']}/brief").json()
    assert summary["next_action"]["href"] == f"/runs/{pending['run_id']}?tab=commands"

    def resume(role, *, expected_status=202, key=None):
        node = next(
            n
            for n in client.get(f"/api/v1/runs/{pending['run_id']}/graph").json()["nodes"]
            if n["id"] == pending["task_ids"][role]
        )
        response = client.post(
            f"/api/v1/runs/{pending['run_id']}/control-commands",
            headers=headers(settings, key),
            json={
                "command_kind": "resume_task",
                "runtime_session_id": node["control"]["runtime_session_id"],
                "task_id": node["id"],
                "expected_task_version": node["state_version"],
                "reason": "Resume this eligible sample task explicitly",
            },
        )
        assert response.status_code == expected_status, response.text
        return response

    # Permission alone cannot skip the access dependency or the operator's hold.
    blocked = resume("analysis", expected_status=409)
    assert blocked.json()["code"] == "unresolved_dependency"
    assert client.get(f"/api/v1/demos/{did}").json()["protected_effects"] == 0
    for index, role in enumerate(("access", "analysis", "validation", "brief"), start=3):
        response = resume(role)
        assert response.json()["state"] == "queued"
        progress = wait_for(
            client, did, lambda d, target=index: d["progress"]["completed"] >= target
        )
        assert progress["protected_effects"] == index - 2
    done = wait_for(client, did, lambda d: d["state"] == "completed")
    assert done["progress"]["completed"] == 6 and done["protected_effects"] == 4
    history = client.get(f"/api/v1/runs/{pending['run_id']}/backpressure/history").json()
    assert history["unconfirmed_count"] == 0
    assert len(history["items"]) == 1
    assert all(c["state"] == "applied" for c in history["items"][0]["commands"])
    with manager.db.read() as conn:
        commands = conn.execute(
            "SELECT c.command_kind,c.state,a.result FROM control_commands c "
            "JOIN control_acknowledgements a ON a.command_id=c.command_id WHERE c.run_id=?",
            (pending["run_id"],),
        ).fetchall()
        assert len(commands) == 8
        assert all(c["state"] == "applied" and c["result"] == "applied" for c in commands)


def test_single_permission_wait_has_no_storm_or_stall_after_deadline(guided):
    client, settings, manager = guided
    pending = wait_for(client, start(client, settings)["demo_id"], lambda d: d["public_completed"])
    assert pending["request_count"] == 1
    client.app.state.detector.scan_run(pending["run_id"], pending["updated_at_ms"] + 65_000)
    assert client.get(f"/api/v1/runs/{pending['run_id']}/incidents").json()["items"] == []
    assert pending["protected_effects"] == 0
    manager.close()
    assert not manager.workers


def test_unavailable_sdk_checkpoint_fails_promptly_without_protected_effects(guided, monkeypatch):
    from swarmcircuit import ControlError

    client, settings, _ = guided

    def unavailable(*args, **kwargs):
        raise ControlError("runtime_disconnected")

    monkeypatch.setattr("swarmcircuit.runtime.RuntimeController.checkpoint", unavailable)
    demo = start(client, settings)
    failed = wait_for(client, demo["demo_id"], lambda d: d["state"] == "failed")
    assert failed["failure_code"] == "worker_unavailable"
    assert failed["protected_effects"] == 0
    assert not failed["worker_connected"]
    assert client.get(f"/api/v1/runs/{failed['run_id']}").json()["status"] == "failed"


def test_closing_fences_new_workers_before_waiting_for_old_ones(client, settings):
    from types import SimpleNamespace

    manager = DemoManager(client.app.state.db, settings, "http://127.0.0.1:8000")
    attempted = []

    def join(timeout):
        with pytest.raises(Problem) as caught:
            manager.create(settings.project_id, str(uuid4()))
        attempted.append(caught.value.code)

    manager.workers["stopping-worker"] = (SimpleNamespace(join=join), Event())
    manager.close()
    assert attempted == ["demo_unavailable"]


def test_demo_liveness_rejects_expired_credentials(guided):
    client, settings, manager = guided
    pending = wait_for(client, start(client, settings)["demo_id"], lambda d: d["public_completed"])
    assert pending["worker_connected"]
    manager.db.write(
        lambda conn: conn.execute(
            "UPDATE runtime_credentials SET expires_at_ms=0 WHERE run_id=?", (pending["run_id"],)
        )
    )
    assert not manager.status(pending["demo_id"])["worker_connected"]


def test_final_lifecycle_rejection_does_not_publish_a_successful_walkthrough(guided, monkeypatch):
    client, settings, _ = guided
    request = Bridge.request

    def reject_completion(self, method, url, **kwargs):
        events = kwargs.get("json", {}).get("events", [])
        if any(e["event_kind"] == "workflow.completed" for e in events):
            return httpx.Response(200, json={"accepted": 0, "rejected": 1, "duplicates": 0})
        return request(self, method, url, **kwargs)

    monkeypatch.setattr(Bridge, "request", reject_completion)
    pending = wait_for(client, start(client, settings)["demo_id"], lambda d: d["public_completed"])
    response = client.post(
        f"/api/v1/demos/{pending['demo_id']}/decision",
        headers=headers(settings),
        json={"decision": "approved", "reason": "Allow this fixture for acknowledgement testing"},
    )
    assert response.status_code == 200, response.text
    failed = wait_for(client, pending["demo_id"], lambda d: d["state"] == "failed")
    assert failed["failure_code"] == "worker_unavailable"
    assert failed["protected_effects"] == 4
    assert failed["progress"]["completed"] == 6
    assert client.get(f"/api/v1/runs/{failed['run_id']}").json()["status"] == "failed"
