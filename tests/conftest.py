from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from swarmcircuit_server.app import create_app
from swarmcircuit_server.config import Settings
from swarmcircuit_server.db.store import now_ms

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / "test.db", "sdk-" + "a" * 32, "operator-" + "b" * 32)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        client.headers["Authorization"] = f"Bearer {settings.sdk_token}"
        yield client


@pytest.fixture
def run_id(client, settings):
    response = client.post(
        f"/api/v1/projects/{settings.project_id}/runs", json={"name": "test-run", "mode": "observe"}
    )
    assert response.status_code == 201, response.text
    return response.json()["run_id"]


def event(kind, *, aid=None, tid=None, payload=None, timestamp=None, **extra):
    result = {
        "event_id": str(uuid4()),
        "source_event_key": str(uuid4()),
        "event_kind": kind,
        "occurred_at_ms": now_ms() if timestamp is None else timestamp,
        "payload": payload or {},
    }
    if aid:
        result["agent_id"] = aid
    if tid:
        result["task_id"] = tid
    return {**result, **extra}


def append(client, rid, events):
    return client.post(f"/api/v1/runs/{rid}/events", json={"events": events})


def register_task(client, rid):
    aid, tid = str(uuid4()), str(uuid4())
    response = append(
        client,
        rid,
        [
            event(
                "agent.started",
                aid=aid,
                payload={"external_agent_key": aid, "display_name": "Agent"},
            ),
            event(
                "task.created",
                aid=aid,
                tid=tid,
                payload={"external_task_key": tid, "title": "Task"},
            ),
        ],
    )
    assert response.json()["accepted"] == 2, response.text
    return aid, tid
