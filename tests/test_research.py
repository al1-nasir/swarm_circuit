"""Outcome-level tests: equal inputs/guards, adversarial perturbations, seals and isolation."""

import csv
import io
import json
import sqlite3
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from swarmcircuit_server.research.metrics import aggregate, measurements, summarize
from swarmcircuit_server.research.protocol import Protocol, canonical
from swarmcircuit_server.research.provider import ModelClient, ProviderFailure, collect_workload
from swarmcircuit_server.research.simulator import simulate


def metric(p, scenario, arm, seed=0):
    return {
        k: v["value"] for k, v in measurements(p, simulate(p, scenario, arm, seed)["truth"]).items()
    }


def test_protocol_rejects_unknown_duplicate_or_unbounded_inputs():
    for args in (
        {"arms": ["fake"]},
        {"seeds": [1, 1]},
        {"horizon_ticks": 10000},
        {"scenarios": ["fake"]},
        {"work_weights": [0, 0, 0]},
    ):
        with pytest.raises(ValidationError):
            Protocol(**args)


@pytest.mark.parametrize("seed", [0, 1, 7])
def test_all_policies_share_world_inputs_and_cannot_bypass_guards(seed):
    p = Protocol(seeds=[seed])
    for scenario in p.scenarios:
        hashes = set()
        for arm in p.arms:
            trial = simulate(p, scenario, arm, seed)
            hashes.add(trial["input_sha256"])
            m = measurements(p, trial["truth"])
            assert m["unsafe_starts"]["value"] == 0
            assert m["duplicate_effects"]["value"] == 0
            assert 0 <= m["authorized_completion"]["value"] <= 1
            assert trial == simulate(p, scenario, arm, seed)
        assert len(hashes) == 1


def test_dedup_effects_are_distinct_from_coordination_traffic_and_ready_queue_is_retained():
    p = Protocol(seeds=[0])
    dedup, full, ready = (metric(p, "retry_cascade", a) for a in ("B3", "B4", "A_ready_queue"))
    assert full["guard_checks"] == dedup["guard_checks"]  # Do not manufacture extra tool savings.
    assert full["coordination_requests"] < dedup["coordination_requests"]
    assert ready["coordination_requests"] < full["coordination_requests"]
    assert full["authorized_completion"] == dedup["authorized_completion"] == 1


def test_legitimate_wait_does_not_trigger_extra_holds():
    p = Protocol(seeds=[0])
    m = metric(p, "legitimate_wait", "B4")
    assert m["control_intents"] == 0
    assert m["false_hold_task_ticks"] == 0
    assert m["authorized_completion"] == 1


def test_wrong_graph_and_lost_telemetry_produce_visible_counterexamples():
    p = Protocol(seeds=[0])
    broken = metric(p, "graph_error", "B4")
    assert broken["independent_completed"] == 0
    assert broken["false_hold_task_ticks"] > 0
    assert metric(p, "graph_error", "B4_no_graph")["independent_completed"] == 1
    assert (
        metric(p, "telemetry_loss", "B4")["authorized_completion"]
        < metric(p, "telemetry_loss", "B0")["authorized_completion"]
    )


def test_truth_reducer_detects_an_unsafe_effect_even_when_a_policy_claims_success():
    p = Protocol(seeds=[0])
    trial = simulate(p, "pending_gate", "B0", 0)
    truth = trial["truth"]
    truth.insert(
        2,
        {
            "sequence": 0,
            "tick": 0,
            "kind": "action.started",
            "task": "report",
            "policy_success": True,
        },
    )
    for i, e in enumerate(truth):
        e["sequence"] = i
    assert measurements(p, truth)["unsafe_starts"]["value"] == 1
    truth[-1]["sequence"] += 1
    with pytest.raises(ValueError, match="Nonmonotonic"):
        measurements(p, truth)


def test_uncertainty_uses_matched_seed_intersection_and_has_no_single_seed_interval():
    assert summarize([4], salt="x")["low"] is None
    rows = [
        {
            "scenario_key": "s",
            "policy_arm": arm,
            "metric_key": "m",
            "seed": seed,
            "metric_value": value,
        }
        for arm, seed, value in [("B3", 0, 5), ("B3", 1, 10), ("B4", 0, 3), ("B4", 2, 999)]
    ]
    contrast = aggregate(rows)["contrasts"][0]
    assert contrast["paired_seeds"] == [0] and contrast["n"] == 1
    assert contrast["mean"] == -2 and contrast["low"] is None
    assert summarize([1, 4, 9], salt="x") == summarize([1, 4, 9], salt="x")


def create_plan(client, settings, *, source="synthetic", seeds=None):
    eid = str(uuid4())
    p = Protocol(seeds=seeds or [0], scenarios=["retry_cascade"], arms=["B0", "B3", "B4"])
    body = {
        "experiment_id": eid,
        "title": "Research test",
        "protocol": p.model_dump(mode="json"),
        "implementation_sha": "b" * 64,
        "source_kind": source,
    }
    auth = {"Authorization": f"Bearer {settings.operator_token}"}
    response = client.post("/api/v1/experiments", json=body, headers=auth)
    assert response.status_code == 201, response.text
    return eid, p, body, auth


def test_research_requires_operator_for_recording_and_scopes_reads(client, settings):
    eid, _, body, auth = create_plan(client, settings)
    assert client.post("/api/v1/experiments", json=body).status_code == 403
    assert (
        client.get(f"/api/v1/experiments/{eid}/results", headers={"Authorization": ""}).status_code
        == 401
    )
    assert client.get(f"/api/v1/projects/{uuid4()}/experiments").status_code == 404
    assert client.get(f"/api/v1/experiments/{uuid4()}/results").status_code == 404
    assert (
        client.post(
            f"/api/v1/experiments/{eid}/trials",
            json={"scenario": "retry_cascade", "arm": "B0", "seed": 0},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/experiments", json={**body, "title": "changed"}, headers=auth
        ).status_code
        == 409
    )


def test_sealed_trials_replay_identically_export_denominators_and_persist_graph(client, settings):
    eid, p, _, auth = create_plan(client, settings)
    request = {"scenario": "retry_cascade", "arm": "B4", "seed": 0}
    response = client.post(f"/api/v1/experiments/{eid}/trials", json=request, headers=auth)
    assert response.status_code == 201, response.text
    saved = response.json()
    csv1 = client.get(f"/api/v1/experiments/{eid}/export.csv").content
    again = client.post(f"/api/v1/experiments/{eid}/trials", json=request, headers=auth)
    assert (
        again.json()["replayed"]
        and client.get(f"/api/v1/experiments/{eid}/export.csv").content == csv1
    )
    records = list(csv.DictReader(io.StringIO(csv1.decode())))
    completion = next(r for r in records if r["metric"] == "authorized_completion")
    assert float(completion["denominator"]) == 5 and float(completion["value"]) == 1
    graph = client.get(f"/api/v1/runs/{saved['run_id']}/graph").json()
    assert len(graph["nodes"]) == 6 and len(graph["edges"]) == 6
    raw = client.get(f"/api/v1/experiments/{eid}/trials/{saved['trial_id']}/truth.jsonl")
    assert raw.status_code == 200 and "no-store" in raw.headers["cache-control"]
    truth = [json.loads(s) for s in raw.text.splitlines()]
    assert truth == simulate(p, "retry_cascade", "B4", 0)["truth"]
    bad = client.post(
        f"/api/v1/experiments/{eid}/trials",
        json={**request, "provenance": {"model": "changed"}},
        headers=auth,
    )
    assert bad.status_code == 409
    with pytest.raises(sqlite3.IntegrityError, match="sealed"):
        client.app.state.db.write(
            lambda c: c.execute(
                "UPDATE research_trial_artifacts SET input_sha256='tamper' WHERE trial_id=?",
                (saved["trial_id"],),
            )
        )
    assert (
        client.get(
            f"/api/v1/experiments/{uuid4()}/trials/{saved['trial_id']}/truth.jsonl"
        ).status_code
        == 404
    )


def test_failure_and_missing_trials_are_not_zero_improvements(client, settings):
    eid, _, _, auth = create_plan(client, settings)
    response = client.post(
        f"/api/v1/experiments/{eid}/trials",
        json={
            "scenario": "retry_cascade",
            "arm": "B0",
            "seed": 0,
            "failure_code": "runner_failure",
        },
        headers=auth,
    )
    assert response.status_code == 201
    result = client.get(f"/api/v1/experiments/{eid}/results").json()
    assert result["failed"] == 1 and result["completed"] == 0 and result["missing"] == 2
    assert result["estimates"] == [] and result["failures"][0]["failure_code"] == "runner_failure"
    assert "runner_failure" in client.get(f"/api/v1/experiments/{eid}/export.csv").text


def test_mismatched_workload_tape_and_runner_digest_are_rejected(client, settings):
    eid, p, _, auth = create_plan(client, settings, source="llm_workload_replay")
    tape = [{"tick": 0, "task": "public", "action": "attempt"}]
    body = {
        "scenario": "retry_cascade",
        "arm": "B0",
        "seed": 0,
        "proposals": tape,
        "provenance": {
            "model": "fixture-model",
            "provider_host": "provider.example",
            "calls": 1,
            "transcript_sha256": "c" * 64,
        },
    }
    assert (
        client.post(
            f"/api/v1/experiments/{eid}/trials",
            json={**body, "expected_artifact_sha256": "0" * 64},
            headers=auth,
        ).status_code
        == 409
    )
    expected = simulate(p, "retry_cascade", "B0", 0, tape)["artifact_sha256"]
    assert (
        client.post(
            f"/api/v1/experiments/{eid}/trials",
            json={**body, "expected_artifact_sha256": expected},
            headers=auth,
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"/api/v1/experiments/{eid}/trials",
            json={**body, "arm": "B3", "proposals": []},
            headers=auth,
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/experiments/{eid}/trials", json={**body, "seed": 99}, headers=auth
        ).status_code
        == 422
    )


def test_trial_pagination_has_no_duplicates(client, settings):
    eid, _, _, auth = create_plan(client, settings, seeds=[0, 1])
    for seed in (0, 1):
        for arm in ("B0", "B3", "B4"):
            assert (
                client.post(
                    f"/api/v1/experiments/{eid}/trials",
                    json={"scenario": "retry_cascade", "arm": arm, "seed": seed},
                    headers=auth,
                ).status_code
                == 201
            )
    ids, cursor = [], None
    while True:
        page = client.get(
            f"/api/v1/experiments/{eid}/trials",
            params={"limit": 2, **({"cursor": cursor} if cursor else {})},
        ).json()
        ids.extend(r["trial_id"] for r in page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(ids) == len(set(ids)) == 6
    assert client.get(f"/api/v1/experiments/{eid}/trials?cursor=bad").status_code == 422


def test_provider_budget_and_no_redirect_retry_or_secret_in_evidence():
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"action":"attempt"}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            },
        )

    c = ModelClient(
        "https://provider.example/v1", "model", "fake-private-key", 1, httpx.MockTransport(respond)
    )
    assert c.decide({"actor": "public"}) == "attempt"
    with pytest.raises(ProviderFailure, match="budget_exhausted"):
        c.decide({"actor": "public"})
    assert len(seen) == c.calls == 1 and c.input_tokens == 12
    assert "fake-private-key" not in canonical(c.entries)
    c.close()
    c = ModelClient(
        "https://provider.example/v1",
        "model",
        "fake-private-key",
        2,
        httpx.MockTransport(
            lambda r: httpx.Response(307, headers={"location": "https://other.example"})
        ),
    )
    with pytest.raises(ProviderFailure, match="provider_unavailable"):
        c.decide({})
    assert c.calls == 1 and not c.usage_available
    c.close()


def test_live_workload_connector_is_bounded_and_replay_does_not_call_model():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"action":"attempt"}'}}]}
        )

    c = ModelClient("https://provider.example/v1", "model", "fake", 3, httpx.MockTransport(respond))
    p = Protocol(seeds=[0], scenarios=["retry_cascade"])
    tape = collect_workload(c, p, "retry_cascade", 0)
    assert len(tape) == len(calls) == 3
    for arm in p.arms:
        simulate(p, "retry_cascade", arm, 0, tape)
    assert len(calls) == 3
    c.close()


def test_research_runs_do_not_flood_the_default_studio_workflow_scope(client, settings, run_id):
    eid, _, _, auth = create_plan(client, settings)
    recorded = client.post(
        f"/api/v1/experiments/{eid}/trials",
        json={"scenario": "retry_cascade", "arm": "B0", "seed": 0},
        headers=auth,
    ).json()
    project = f"/api/v1/projects/{settings.project_id}/runs"
    normal = client.get(project, params={"kind": "workflow"}).json()["items"]
    research = client.get(project, params={"kind": "research"}).json()["items"]
    assert [r["run_id"] for r in normal] == [run_id]
    assert [r["run_id"] for r in research] == [recorded["run_id"]]
    assert len(client.get(project).json()["items"]) == 2
