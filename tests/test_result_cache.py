"""Presentation caching preserves frozen numeric outcomes and invalidates on sealed append."""

import random
from uuid import uuid4

from swarmcircuit_server.api import result_cache
from swarmcircuit_server.research.metrics import summarize as frozen_summarize

from tests.test_research import create_plan


def test_optimized_bootstrap_matches_frozen_binary_float_and_seed_semantics():
    rng = random.Random(42)
    populations = [
        [],
        [0.2],
        [1.0] * 30,
        [0.2, 0.4, 0.8, 1.0, 0.6],
        [rng.uniform(-100, 100) for _ in range(30)],
        [float(rng.randrange(100)) for _ in range(30)],
    ]
    for salt in ("count", "fraction", "paired:delta"):
        for values in populations:
            assert result_cache.summarize(values, salt=salt) == frozen_summarize(values, salt=salt)


def test_aggregate_cache_persists_and_appending_a_trial_cannot_return_stale_counts(
    client, settings, monkeypatch
):
    eid, _, _, auth = create_plan(client, settings)
    calls = []
    original = result_cache.aggregate

    def counted(rows):
        calls.append(len(rows))
        return original(rows)

    monkeypatch.setattr(result_cache, "aggregate", counted)
    request = {"scenario": "retry_cascade", "arm": "B0", "seed": 0}
    assert (
        client.post(f"/api/v1/experiments/{eid}/trials", json=request, headers=auth).status_code
        == 201
    )
    first = client.get(f"/api/v1/experiments/{eid}/results")
    assert first.status_code == 200, first.text
    assert first.json()["completed"] == 1
    assert len(calls) == 1
    cache = result_cache.ResultCache()
    assert cache.get(client.app.state.db, settings.project_id, eid) == first.json()
    assert len(calls) == 1  # New service/cache instance reads persistent prepared result.
    assert (
        client.post(
            f"/api/v1/experiments/{eid}/trials", json={**request, "arm": "B3"}, headers=auth
        ).status_code
        == 201
    )
    updated = client.get(f"/api/v1/experiments/{eid}/results")
    assert updated.json()["completed"] == 2
    assert len(calls) == 2
    assert first.json()["missing"] == updated.json()["missing"] + 1
    with client.app.state.db.read() as conn:
        saved_count = conn.execute(
            "SELECT trial_count FROM research_result_cache WHERE experiment_id=?", (eid,)
        ).fetchone()[0]
    assert saved_count == 2
    assert client.get(f"/api/v1/experiments/{uuid4()}/results").status_code == 404
    assert (
        client.get(f"/api/v1/experiments/{eid}/results", headers={"Authorization": ""}).status_code
        == 401
    )


def test_optional_background_cache_failure_does_not_change_sealed_trial_success(
    client, settings, monkeypatch
):
    eid, _, _, auth = create_plan(client, settings)
    for arm in ("B0", "B3"):
        response = client.post(
            f"/api/v1/experiments/{eid}/trials",
            json={"scenario": "retry_cascade", "arm": arm, "seed": 0},
            headers=auth,
        )
        assert response.status_code == 201

    def unavailable(*args, **kwargs):
        raise RuntimeError("presentation cache temporarily unavailable")

    monkeypatch.setattr(result_cache.ResultCache, "get", unavailable)
    final = client.post(
        f"/api/v1/experiments/{eid}/trials",
        json={"scenario": "retry_cascade", "arm": "B4", "seed": 0},
        headers=auth,
    )
    assert final.status_code == 201, final.text
    assert final.json()["state"] == "completed"
    assert len(client.get(f"/api/v1/experiments/{eid}/trials").json()["items"]) == 3
