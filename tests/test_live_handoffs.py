"""Provider responses are injected; no paid model calls occur in these tests."""

import asyncio
import json
import time
from threading import Event
from uuid import uuid4

import httpx
import pytest
from swarmcircuit_server.demo.agents import (
    LIMITATIONS,
    LiveFailure,
)
from swarmcircuit_server.demo.fixtures import analyze

from tests.test_guided_demo import Bridge, headers


def good_draft(**facts):
    return {
        "facts": {**analyze(), **facts},
        "limitations": list(LIMITATIONS),
        "rationale": "The structured quantities describe the supplied synthetic CSV only.",
    }


def review(verdict="accept", issues=None):
    return {"verdict": verdict, "issues": issues or [], "rationale": "Checked the supplied draft."}


def provider_response(value, usage=None, model="test-model"):
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": json.dumps(value)}}],
            "model": model,
            "usage": usage
            if usage is not None
            else {"prompt_tokens": 100, "completion_tokens": 50},
        },
    )


@pytest.fixture
def live(client, settings, monkeypatch):
    monkeypatch.setenv("SWARM_MODEL_BASE_URL", "https://provider.test/v1")
    monkeypatch.setenv("SWARM_MODEL_NAME", "test-model")
    monkeypatch.setenv("SWARM_MODEL_API_KEY", "private-model-test-key")
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: Bridge(client))
    manager = client.app.state.demo
    requests = []
    replies = [good_draft(), review()]

    def handler(request):
        requests.append(json.loads(request.content))
        return provider_response(replies.pop(0))

    manager.model_transport = httpx.MockTransport(handler)
    yield client, settings, manager, requests, replies
    manager.close()


def start(client, settings, key=None, mode="live"):
    response = client.post(
        f"/api/v1/projects/{settings.project_id}/demos",
        headers=headers(settings, key),
        json={"mode": mode},
    )
    assert response.status_code == 201, response.text
    return response.json()


def wait(client, did, predicate):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        value = client.get(f"/api/v1/demos/{did}").json()
        if predicate(value):
            return value
        time.sleep(0.04)
    pytest.fail(f"Expected live workflow state not observed: {value}")


def grant(client, settings, did):
    pending = wait(client, did, lambda d: bool(d["approval_id"]) and d["worker_connected"])
    response = client.post(
        f"/api/v1/demos/{did}/decision",
        headers=headers(settings),
        json={
            "decision": "approved",
            "reason": "operator-private-reason-do-not-send-to-provider",
        },
    )
    assert response.status_code == 200, response.text
    return pending


def test_live_writer_reviewer_uses_actual_output_and_independent_claim_checks(live):
    client, settings, manager, requests, _ = live
    demo = start(client, settings)
    did = demo["demo_id"]
    pending = grant(client, settings, did)
    assert pending["model_calls"] == 0
    done = wait(client, did, lambda d: d["state"] in {"completed", "failed"})
    assert done["state"] == "completed", done
    assert done["progress"]["completed"] == 6 and done["protected_effects"] == 4
    assert done["execution_mode"] == "live"
    assert done["model"]["calls"] == 2 and done["model"]["review_status"] == "accepted"
    assert done["model"]["input_tokens"] == 200 and done["model"]["output_tokens"] == 100
    writer_data = json.loads(requests[0]["messages"][1]["content"])
    reviewer_data = json.loads(requests[1]["messages"][1]["content"])
    assert writer_data["computed_csv_facts"] == analyze()
    assert reviewer_data["actual_writer_draft"] == good_draft()
    assert "operator-private-reason" not in json.dumps(requests)
    assert "private-model-test-key" not in json.dumps(requests)
    graph = client.get(f"/api/v1/runs/{done['run_id']}/graph?view=task").json()
    assert any(
        e["source"] == done["task_ids"]["validation"]
        and e["target"] == done["task_ids"]["analysis"]
        for e in graph["edges"]
    )
    final = client.get(f"/api/v1/demos/{did}/artifacts/final-brief")
    assert final.status_code == 200 and "39.15%" in final.text
    assert "no model-generated analysis" not in final.text
    assert {"agent-draft", "agent-review", "handoff-evidence"} <= {
        a["slug"] for a in done["artifacts"]
    }


def test_false_writer_claim_cannot_be_published_by_an_accepting_reviewer(live):
    client, settings, _, requests, replies = live
    wrong = good_draft(revenue_growth_percent="900.00")
    replies[:] = [wrong, review(), good_draft()]
    did = start(client, settings)["demo_id"]
    grant(client, settings, did)
    done = wait(client, did, lambda d: d["state"] in {"completed", "failed"})
    assert done["state"] == "completed", done
    assert done["model"]["calls"] == 3 and done["model"]["repair_used"]
    assert done["model"]["review_status"] == "repaired"
    repair_input = json.loads(requests[2]["messages"][1]["content"])
    assert repair_input["actual_writer_draft"] == wrong
    assert repair_input["actual_reviewer_feedback"] == review()
    assert "900.00" in json.dumps(repair_input["independent_source_check_errors"])
    evidence = client.get(f"/api/v1/demos/{did}/artifacts/handoff-evidence").text
    assert "900.00" in evidence and "without a second model review" in evidence
    final = client.get(f"/api/v1/demos/{did}/artifacts/final-brief").text
    assert "39.15%" in final and "900.00" not in final


def test_bad_repair_is_retained_and_no_final_brief_is_published(live):
    client, settings, _, requests, replies = live
    replies[:] = [good_draft(customer_quarters=2000), review(), good_draft(customer_quarters=2000)]
    did = start(client, settings)["demo_id"]
    grant(client, settings, did)
    failed = wait(client, did, lambda d: d["state"] == "failed")
    assert failed["failure_code"] == "handoff_rejected"
    assert failed["model"]["calls"] == 3 and failed["model"]["review_status"] == "rejected"
    assert failed["protected_effects"] == 3 and len(requests) == 3
    assert client.get(f"/api/v1/demos/{did}/artifacts/final-brief").status_code == 404
    assert client.get(f"/api/v1/demos/{did}/artifacts/agent-repair").status_code == 200
    assert "2000" in client.get(f"/api/v1/demos/{did}/artifacts/handoff-evidence").text


def test_live_denial_makes_no_provider_request_and_mode_is_key_bound(live):
    client, settings, _, requests, _ = live
    key = str(uuid4())
    demo = start(client, settings, key)
    did = demo["demo_id"]
    assert start(client, settings, key)["demo_id"] == did
    conflict = client.post(
        f"/api/v1/projects/{settings.project_id}/demos", headers=headers(settings, key), json={}
    )
    assert conflict.status_code == 409
    wait(client, did, lambda d: bool(d["approval_id"]))
    response = client.post(
        f"/api/v1/demos/{did}/decision",
        headers=headers(settings),
        json={"decision": "denied", "reason": "Keep only public notes"},
    )
    assert response.status_code == 200
    denied = wait(client, did, lambda d: d["state"] == "denied")
    assert denied["model_calls"] == 0 and denied["protected_effects"] == 0 and not requests


@pytest.mark.parametrize("failure", ["unavailable", "timeout", "malformed"])
def test_failed_provider_attempt_is_recorded_without_fallback(live, failure):
    client, settings, manager, requests, _ = live

    def handler(request):
        requests.append(json.loads(request.content))
        if failure == "timeout":
            raise httpx.ReadTimeout("test deadline")
        if failure == "unavailable":
            return httpx.Response(503, text="untrusted provider error")
        return provider_response({"unsupported": "output"})

    manager.model_transport = httpx.MockTransport(handler)
    did = start(client, settings)["demo_id"]
    grant(client, settings, did)
    failed = wait(client, did, lambda d: d["state"] == "failed")
    assert failed["model_calls"] == 1 and len(requests) == 1
    assert failed["model"]["input_tokens"] is None and failed["model"]["output_tokens"] is None
    assert client.get(f"/api/v1/demos/{did}/artifacts/final-brief").status_code == 404
    with manager.db.read() as conn:
        receipt = conn.execute(
            "SELECT state,error_code FROM guided_demo_model_calls WHERE demo_id=?", (did,)
        ).fetchone()
    assert receipt["state"] == ("unknown" if failure == "timeout" else "failed")
    assert (
        receipt["error_code"]
        == {
            "timeout": "provider_timeout",
            "unavailable": "provider_unavailable",
            "malformed": "invalid_model_output",
        }[failure]
    )


def test_live_expiry_records_terminal_state_without_model_calls(live):
    client, settings, manager, requests, _ = live
    did = start(client, settings)["demo_id"]
    wait(client, did, lambda d: bool(d["approval_id"]))
    manager.db.write(
        lambda c: c.execute(
            "UPDATE guided_demo_sessions SET expires_at_ms=0 WHERE demo_id=?", (did,)
        )
    )
    expired = wait(client, did, lambda d: d["state"] == "expired")
    assert expired["model_calls"] == 0 and not requests
    manager.start()  # Expired terminal records cannot prevent restart recovery.
    assert manager.status(did)["state"] == "expired"


def test_cancel_inflight_provider_request_retains_unknown_attempt_without_publication(live):
    client, settings, manager, requests, _ = live
    started = Event()

    async def handler(request):
        requests.append(json.loads(request.content))
        started.set()
        await asyncio.sleep(60)
        return provider_response(good_draft())

    manager.model_transport = httpx.MockTransport(handler)
    did = start(client, settings)["demo_id"]
    grant(client, settings, did)
    assert started.wait(5)
    before = time.monotonic()
    manager.close()
    assert time.monotonic() - before < 5
    stopped = manager.status(did)
    assert stopped["state"] == "interrupted" and stopped["model_calls"] == 1
    assert client.get(f"/api/v1/demos/{did}/artifacts/agent-draft").status_code == 404
    assert client.get(f"/api/v1/demos/{did}/artifacts/final-brief").status_code == 404
    with manager.db.read() as conn:
        receipt = conn.execute(
            "SELECT state FROM guided_demo_model_calls WHERE demo_id=?", (did,)
        ).fetchone()
    assert receipt[0] == "unknown"


def test_expiry_cancels_inflight_request_and_retains_no_draft(live):
    client, settings, manager, _, _ = live
    started = Event()

    async def handler(_):
        started.set()
        await asyncio.sleep(60)
        return provider_response(good_draft())

    manager.model_transport = httpx.MockTransport(handler)
    did = start(client, settings)["demo_id"]
    grant(client, settings, did)
    assert started.wait(5)
    manager.db.write(
        lambda c: c.execute(
            "UPDATE guided_demo_sessions SET expires_at_ms=0 WHERE demo_id=?",
            (did,),
        )
    )
    expired = wait(client, did, lambda d: d["state"] == "expired")
    assert expired["model_calls"] == 1
    assert client.get(f"/api/v1/demos/{did}/artifacts/agent-draft").status_code == 404
    assert client.get(f"/api/v1/demos/{did}/artifacts/final-brief").status_code == 404
    deadline = time.monotonic() + 5
    while did in manager.workers and time.monotonic() < deadline:
        time.sleep(0.03)
    assert did not in manager.workers
    with manager.db.read() as conn:
        assert (
            conn.execute(
                "SELECT state FROM guided_demo_model_calls WHERE demo_id=?", (did,)
            ).fetchone()[0]
            == "unknown"
        )


def test_reply_after_control_credentials_expire_is_not_published(live):
    client, settings, manager, requests, _ = live
    did = start(client, settings)["demo_id"]
    run = wait(client, did, lambda d: bool(d["approval_id"]))["run_id"]

    def handler(request):
        requests.append(json.loads(request.content))
        # The writer can operate during provider I/O; this independently changes
        # host authority before its reply reaches the publication boundary.
        manager.db.write(
            lambda c: c.execute(
                "UPDATE runtime_credentials SET expires_at_ms=0 WHERE runtime_session_id IN "
                "(SELECT runtime_session_id FROM runtime_sessions WHERE run_id=?)",
                (run,),
            )
        )
        return provider_response(good_draft())

    manager.model_transport = httpx.MockTransport(handler)
    grant(client, settings, did)
    failed = wait(client, did, lambda d: d["state"] == "failed")
    assert failed["model_calls"] == 1 and failed["model"]["input_tokens"] == 100
    assert client.get(f"/api/v1/demos/{did}/artifacts/agent-draft").status_code == 404
    assert client.get(f"/api/v1/demos/{did}/artifacts/final-brief").status_code == 404


def test_durable_three_attempt_budget_stops_a_new_transport(live, monkeypatch):
    client, settings, manager, requests, _ = live
    did = start(client, settings)["demo_id"]
    wait(client, did, lambda d: bool(d["approval_id"]))

    def spent(conn):
        for index, phase in enumerate(("writer", "reviewer", "repair"), 1):
            conn.execute(
                "INSERT INTO guided_demo_model_calls(demo_id,call_index,phase,started_at_ms,"
                "state,request_sha256) VALUES (?,?,?,?,?,?)",
                (did, index, phase, 1, "unknown", "test"),
            )

    manager.db.write(spent)
    monkeypatch.setattr(manager, "check_live_authority", lambda *_: None)
    with pytest.raises(LiveFailure, match="model_budget_exhausted"):
        manager.model_call(did, str(uuid4()), "repair", {}, Event())
    assert not requests


def test_capabilities_and_start_do_not_accept_unconfigured_or_cross_project_live(live, monkeypatch):
    client, settings, _, requests, _ = live
    monkeypatch.delenv("SWARM_MODEL_API_KEY")
    caps = client.get(f"/api/v1/projects/{settings.project_id}/demo-capabilities").json()
    assert not caps["live"]["available"] and caps["live"]["configured_model"] is None
    response = client.post(
        f"/api/v1/projects/{settings.project_id}/demos",
        headers=headers(settings),
        json={"mode": "live"},
    )
    assert response.status_code == 409 and response.json()["code"] == "live_unconfigured"
    assert client.get(f"/api/v1/projects/{uuid4()}/demo-capabilities").status_code == 404
    assert not requests
