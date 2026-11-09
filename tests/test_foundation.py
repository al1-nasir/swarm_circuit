import hashlib
import sqlite3
from uuid import uuid4

import pytest
import yaml
from swarmcircuit_server.db.store import connect, migrate

from tests.conftest import ROOT, append, event, register_task


def test_original_contracts_are_frozen():
    for original, copy in (
        ("001_initial.sql", "migrations/001_initial.sql"),
        ("openapi.yaml", "contracts/openapi.yaml"),
    ):
        assert (ROOT / original).read_bytes() == (ROOT / copy).read_bytes()
    bundled = ROOT / "packages/server/src/swarmcircuit_server/db/migrations"
    assert (bundled / "001_initial.sql").read_bytes() == (ROOT / "001_initial.sql").read_bytes()
    assert (bundled / "002_runtime_control.sql").read_bytes() == (
        ROOT / "migrations/002_runtime_control.sql"
    ).read_bytes()
    assert (bundled / "003_payment_evidence.sql").read_bytes() == (
        ROOT / "migrations/003_payment_evidence.sql"
    ).read_bytes()
    assert (bundled / "004_studio_stream.sql").read_bytes() == (
        ROOT / "migrations/004_studio_stream.sql"
    ).read_bytes()
    assert (bundled / "005_research_evidence.sql").read_bytes() == (
        ROOT / "migrations/005_research_evidence.sql"
    ).read_bytes()
    assert (bundled / "006_guided_demo.sql").read_bytes() == (
        ROOT / "migrations/006_guided_demo.sql"
    ).read_bytes()
    assert (bundled / "007_live_handoffs.sql").read_bytes() == (
        ROOT / "migrations/007_live_handoffs.sql"
    ).read_bytes()
    assert (bundled / "manifest.json").read_bytes() == (
        ROOT / "migrations/manifest.json"
    ).read_bytes()


def test_control_contract_matches_implemented_routes():
    from scripts.export_control_contract import control_contract

    saved = yaml.safe_load((ROOT / "contracts/control-v1.openapi.yaml").read_text())
    assert saved == control_contract()
    assert (
        saved["paths"]["/api/v1/control-commands/{command_id}/ack"]["post"]["x-credential-role"]
        == "runtime session"
    )


def test_payment_contract_matches_implemented_routes():
    from scripts.export_payment_contract import payment_contract

    saved = yaml.safe_load((ROOT / "contracts/payments-v1.openapi.yaml").read_text())
    assert saved == payment_contract()


def test_additive_upgrade_preserves_existing_run(tmp_path):
    import json

    folder = tmp_path / "legacy"
    folder.mkdir()
    initial = (ROOT / "001_initial.sql").read_bytes()
    (folder / "001_initial.sql").write_bytes(initial)
    (folder / "manifest.json").write_text(
        json.dumps({"001_initial.sql": hashlib.sha256(initial).hexdigest()})
    )
    path = tmp_path / "upgrade.db"
    migrate(path, folder)
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO projects(project_id,name,slug,created_at_ms) "
            "VALUES ('p','prior','prior',1)"
        )
        conn.execute(
            "INSERT INTO workflow_runs(run_id,project_id,name,mode,created_at_ms,updated_at_ms) "
            "VALUES ('r','p','retained','observe',1,1)"
        )
    migrate(path)
    with connect(path) as conn:
        assert conn.execute("SELECT name FROM workflow_runs WHERE run_id='r'").fetchone()[0] == (
            "retained"
        )
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 7
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migration_idempotence_and_guards(tmp_path):
    path = tmp_path / "db.sqlite"
    migrate(path)
    migrate(path)
    conn = connect(path)
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 7
        assert (
            conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
            == 50
        )
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO workflow_runs(run_id,project_id,name,mode,created_at_ms,"
                "updated_at_ms) VALUES ('r','nonexistent','name','observe',1,1)"
            )
    finally:
        conn.close()


def test_live_handoff_upgrade_preserves_fixture_and_retains_bounded_call_receipts(tmp_path):
    import json

    folder = tmp_path / "through006"
    folder.mkdir()
    manifest = json.loads((ROOT / "migrations/manifest.json").read_text())
    previous = {name: sha for name, sha in manifest.items() if name < "007"}
    for name in previous:
        (folder / name).write_bytes((ROOT / "migrations" / name).read_bytes())
    (folder / "manifest.json").write_text(json.dumps(previous))
    path = tmp_path / "existing-demo.db"
    migrate(path, folder)
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO projects(project_id,name,slug,created_at_ms) "
            "VALUES ('p','prior','prior',1)"
        )
        conn.execute(
            "INSERT INTO guided_demo_sessions(demo_id,project_id,idempotency_key,state,"
            "created_at_ms,updated_at_ms,expires_at_ms) VALUES ('d','p','start','completed',1,2,3)"
        )
        conn.execute(
            "INSERT INTO guided_demo_artifacts VALUES "
            "('d','public-findings','Retained output','text/markdown',"
            "'Prior fixture output','sha',2)"
        )
        legacy_artifact = dict(
            conn.execute("SELECT * FROM guided_demo_artifacts WHERE demo_id='d'").fetchone()
        )
    migrate(path)
    migrate(path)
    with connect(path) as conn:
        legacy = dict(
            conn.execute("SELECT * FROM guided_demo_sessions WHERE demo_id='d'").fetchone()
        )
        assert legacy["execution_mode"] == "fixture"
        assert (
            legacy["start_payload_sha256"] == legacy["model_name"] == legacy["provider_host"] == ""
        )
        assert legacy["state"] == "completed"
        assert (
            dict(
                conn.execute(
                    "SELECT * FROM guided_demo_artifacts "
                    "WHERE demo_id='d' AND slug='public-findings'"
                ).fetchone()
            )
            == legacy_artifact
        )
        slugs = {
            "public-findings",
            "dataset-analysis",
            "final-brief",
            "agent-draft",
            "agent-review",
            "agent-repair",
            "handoff-evidence",
        }
        for slug in sorted(slugs - {"public-findings"}):
            conn.execute(
                "INSERT INTO guided_demo_artifacts VALUES (?, ?, ?, 'text/markdown', ?, ?, 4)",
                ("d", slug, "Saved " + slug, "Output for " + slug, "hash-" + slug),
            )
        assert {
            row[0]
            for row in conn.execute("SELECT slug FROM guided_demo_artifacts WHERE demo_id='d'")
        } == slugs
        conn.execute(
            "INSERT INTO guided_demo_sessions(demo_id,project_id,idempotency_key,state,"
            "created_at_ms,updated_at_ms,expires_at_ms) "
            "VALUES ('artifact-guards','p','guard-test','completed',1,2,3)"
        )
        for slug, media_type, content in (
            ("unknown-output", "text/markdown", "data"),
            ("agent-draft", "application/json", "data"),
            ("agent-draft", "text/markdown", "x" * 50_001),
        ):
            with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
                conn.execute(
                    "INSERT INTO guided_demo_artifacts VALUES "
                    "(?, ?, 'Guard test', ?, ?, 'hash', 4)",
                    ("artifact-guards", slug, media_type, content),
                )
        conn.execute(
            "INSERT INTO guided_demo_artifacts VALUES "
            "('artifact-guards','agent-draft','Boundary','text/markdown',?,'hash',4)",
            ("x" * 50_000,),
        )
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
            conn.execute(
                "INSERT INTO guided_demo_artifacts VALUES "
                "('d','agent-draft','Duplicate','text/markdown','data','hash',4)"
            )
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
            conn.execute(
                "INSERT INTO guided_demo_artifacts VALUES "
                "('missing-demo','agent-review','Orphan','text/markdown','data','hash',4)"
            )
        conn.execute(
            "INSERT INTO guided_demo_model_calls(demo_id,call_index,phase,started_at_ms,state,"
            "request_sha256) VALUES ('d',1,'writer',4,'started',?)",
            ("a" * 64,),
        )
        conn.execute(
            "UPDATE guided_demo_model_calls SET state='succeeded',completed_at_ms=5,"
            "input_tokens=12,output_tokens=7,response_sha256=?,response_model='reported-model' "
            "WHERE demo_id='d' AND call_index=1",
            ("b" * 64,),
        )
        receipt = dict(
            conn.execute(
                "SELECT * FROM guided_demo_model_calls WHERE demo_id='d' AND call_index=1"
            ).fetchone()
        )
        assert receipt["started_at_ms"] == 4 and receipt["completed_at_ms"] == 5
        assert receipt["state"] == "succeeded" and receipt["input_tokens"] == 12
        assert receipt["response_model"] == "reported-model"
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO guided_demo_model_calls(demo_id,call_index,phase,started_at_ms,state,"
                "request_sha256) VALUES ('d',4,'repair',6,'started','hash')"
            )
        with pytest.raises(sqlite3.IntegrityError, match="retained model call attempt"):
            conn.execute("DELETE FROM guided_demo_model_calls WHERE demo_id='d'")
        conn.execute(
            "INSERT INTO guided_demo_handoffs VALUES "
            "('d','draft',1,'{\"claim\":\"original\"}',NULL,NULL,'{}',6)"
        )
        conn.execute(
            "UPDATE guided_demo_handoffs SET status='repaired',revision=2,"
            'review_json=\'{"feedback":"mismatch"}\',repair_json=\'{"claim":"corrected"}\','
            "validation_json='{\"valid\":true}',updated_at_ms=7 WHERE demo_id='d'"
        )
        handoff = conn.execute("SELECT * FROM guided_demo_handoffs WHERE demo_id='d'").fetchone()
        assert json.loads(handoff["writer_json"]) == {"claim": "original"}
        assert json.loads(handoff["repair_json"]) == {"claim": "corrected"}
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migration_checksum_and_atomic_rollback(tmp_path):
    folder = tmp_path / "migrations"
    folder.mkdir()
    (folder / "001_initial.sql").write_bytes((ROOT / "001_initial.sql").read_bytes() + b"broken;")
    (folder / "manifest.json").write_text('{"001_initial.sql":"bad"}')
    with pytest.raises(RuntimeError, match="checksum"):
        migrate(tmp_path / "bad.db", folder)
    import json

    digest = hashlib.sha256((folder / "001_initial.sql").read_bytes()).hexdigest()
    (folder / "manifest.json").write_text(json.dumps({"001_initial.sql": digest}))
    with pytest.raises(sqlite3.Error):
        migrate(tmp_path / "bad.db", folder)
    conn = connect(tmp_path / "bad.db")
    try:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchall()
    finally:
        conn.close()


def test_health_auth_and_run_contract(client, settings, run_id):
    health = client.get("/api/v1/health", headers={"Authorization": ""})
    assert health.json() == {"status": "ready", "schema_version": "007"}
    detail = client.get(f"/api/v1/runs/{run_id}").json()
    contract = yaml.safe_load((ROOT / "openapi.yaml").read_text())
    assert set(contract["components"]["schemas"]["Run"]["required"]) <= detail.keys()
    assert client.get(f"/api/v1/runs/{run_id}", headers={"Authorization": ""}).status_code == 401
    assert client.get(f"/api/v1/runs/{uuid4()}").status_code == 404
    assert client.get(f"/api/v1/projects/{uuid4()}/runs").status_code == 404
    result = client.post(
        f"/api/v1/projects/{settings.project_id}/runs",
        json={"name": "no-enforcement", "mode": "control"},
    )
    assert result.status_code == 201
    assert not client.get(f"/api/v1/runs/{result.json()['run_id']}/graph").json()[
        "control_available"
    ]
    result = client.post(
        f"/api/v1/projects/{settings.project_id}/runs",
        headers={"Authorization": f"Bearer {settings.operator_token}"},
        json={"name": "bad", "mode": "observe"},
    )
    assert result.status_code == 403


def test_event_replay_conflicts_redaction_and_outbox(client, run_id):
    aid, tid = register_task(client, run_id)
    e = event(
        "task.started", aid=aid, tid=tid, payload={"prompt": "SECRET", "nested": {"key": "SECRET"}}
    )
    assert append(client, run_id, [e]).json()["accepted"] == 1
    assert append(client, run_id, [e]).json()["duplicates"] == 1
    conflict = {**e, "event_kind": "task.failed"}
    assert append(client, run_id, [conflict]).json()["rejected"] == 1
    data = client.get(f"/api/v1/runs/{run_id}/timeline").text
    assert "SECRET" not in data
    with client.app.state.db.read() as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM run_events WHERE event_id=?", (e["event_id"],)
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ui_outbox WHERE entity_id=?", (e["event_id"],)
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute("SELECT state_version FROM tasks WHERE task_id=?", (tid,)).fetchone()[0]
            == 1
        )


def test_out_of_order_events_never_regress_completed_task(client, run_id):
    aid, tid = register_task(client, run_id)
    finished = event("task.completed", aid=aid, tid=tid, timestamp=1000)
    late_start = event("task.started", aid=aid, tid=tid, timestamp=500)
    assert append(client, run_id, [finished, late_start]).json()["accepted"] == 2
    nodes = client.get(f"/api/v1/runs/{run_id}/graph").json()["nodes"]
    assert nodes[0]["state"] == "completed"
    assert nodes[0]["state_version"] == 1


def test_explicit_dependencies_handoff_and_same_run_isolation(client, settings, run_id):
    a1, t1 = register_task(client, run_id)
    a2, t2 = register_task(client, run_id)
    dependency = event(
        "task.dependency_added", aid=a2, tid=t2, payload={"prerequisite_task_id": t1}
    )
    handoff = event(
        "agent.handoff", aid=a1, tid=t1, payload={"to_agent_id": a2, "message": "SECRET"}
    )
    assert append(client, run_id, [dependency, handoff]).json()["accepted"] == 2
    graph = client.get(f"/api/v1/runs/{run_id}/graph").json()
    assert graph["edges"][0]["evidence_event_id"] == dependency["event_id"]
    assert graph["edges"][0]["evidence_kind"] == "explicit"
    agent_graph = client.get(f"/api/v1/runs/{run_id}/graph?view=agent").json()
    assert agent_graph["edges"][0]["source"] == a1
    other = client.post(
        f"/api/v1/projects/{settings.project_id}/runs", json={"name": "other", "mode": "observe"}
    ).json()["run_id"]
    _, ot = register_task(client, other)
    bad = event("task.dependency_added", aid=a2, tid=t2, payload={"prerequisite_task_id": ot})
    bad_handoff = event("agent.handoff", aid=a1, payload={"to_agent_id": str(uuid4())})
    assert append(client, run_id, [bad, bad_handoff]).json()["rejected"] == 2
    assert append(client, other, [dependency]).json()["rejected"] == 1


def test_individual_record_rollback(client, run_id):
    aid, tid = register_task(client, run_id)
    before = client.get(f"/api/v1/runs/{run_id}/graph").json()["projection_version"]
    invalid = event(
        "task.dependency_added", aid=aid, tid=tid, payload={"prerequisite_task_id": tid}
    )
    valid = event("task.started", aid=aid, tid=tid)
    result = append(client, run_id, [invalid, valid]).json()
    assert result == {
        "accepted": 1,
        "duplicates": 0,
        "rejected": 1,
        "rejected_keys": [invalid["source_event_key"]],
    }
    assert client.get(f"/api/v1/runs/{run_id}/graph").json()["projection_version"] == before + 1


def test_trust_cannot_be_claimed_and_unsupported_effects_are_metadata_only(client, run_id):
    aid, tid = register_task(client, run_id)
    forged = event("task.completed", aid=aid, tid=tid, trust_class="simulation_truth")
    assert append(client, run_id, [forged]).status_code == 422
    claim = event("control.applied", aid=aid, tid=tid, payload={"state": "held", "token": "SECRET"})
    assert append(client, run_id, [claim]).json()["accepted"] == 1
    assert client.get(f"/api/v1/runs/{run_id}/graph").json()["nodes"][0]["state"] == "created"
    with client.app.state.db.read() as conn:
        row = conn.execute(
            "SELECT * FROM run_events WHERE event_id=?", (claim["event_id"],)
        ).fetchone()
        assert row["trust_class"] == "sdk_observation"
        assert row["payload_json"] == "{}"


def test_invalid_requests_do_not_echo_secrets(client, run_id):
    response = append(client, run_id, [{"token": "secret-do-not-echo"}])
    assert response.status_code == 422
    assert "secret-do-not-echo" not in response.text
    assert set(response.json()) >= {"code", "message", "correlation_id"}


def test_stable_pagination(client, settings, run_id):
    register_task(client, run_id)
    seen, cursor = [], None
    while True:
        response = client.get(
            f"/api/v1/runs/{run_id}/timeline",
            params={"limit": 1, **({"cursor": cursor} if cursor else {})},
        )
        page = response.json()
        seen.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == 2
    for index in range(3):
        client.post(
            f"/api/v1/projects/{settings.project_id}/runs",
            json={"name": str(index), "mode": "observe"},
        )
    page = client.get(f"/api/v1/projects/{settings.project_id}/runs?limit=2").json()
    following = client.get(
        f"/api/v1/projects/{settings.project_id}/runs",
        params={"limit": 2, "cursor": page["next_cursor"]},
    ).json()
    assert len({r["run_id"] for r in page["items"] + following["items"]}) == 4
    assert client.get(f"/api/v1/runs/{run_id}/timeline?cursor=malformed").status_code == 422


def test_schema_append_only_trigger(client, run_id):
    register_task(client, run_id)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        client.app.state.db.write(
            lambda conn: conn.execute("UPDATE run_events SET trust_class='derived'")
        )


def test_completion_requires_explicit_workflow_end_and_does_not_regress(client, run_id):
    aid, tid = register_task(client, run_id)
    assert (
        append(client, run_id, [event("task.completed", aid=aid, tid=tid, timestamp=1000)]).json()[
            "accepted"
        ]
        == 1
    )
    assert client.get(f"/api/v1/runs/{run_id}").json()["status"] == "running"
    assert (
        append(client, run_id, [event("workflow.completed", timestamp=2000)]).json()["accepted"]
        == 1
    )
    assert client.get(f"/api/v1/runs/{run_id}").json()["status"] == "completed"
    append(client, run_id, [event("task.started", aid=aid, tid=tid, timestamp=500)])
    assert client.get(f"/api/v1/runs/{run_id}").json()["ended_at_ms"] == 2000


def test_source_can_be_disabled(client, settings, run_id):
    client.app.state.db.write(
        lambda conn: conn.execute(
            "UPDATE telemetry_sources SET enabled=0 WHERE source_id=?",
            (settings.source_id("sdk"),),
        )
    )
    assert append(client, run_id, [event("workflow.started")]).status_code == 403


def test_same_timestamp_completion_outranks_random_uuid_order(client, run_id):
    aid, tid = register_task(client, run_id)
    started = event("task.started", aid=aid, tid=tid, timestamp=1000)
    started["event_id"] = "ffffffff-ffff-4fff-bfff-ffffffffffff"
    completed = event("task.completed", aid=aid, tid=tid, timestamp=1000)
    completed["event_id"] = "00000000-0000-4000-8000-000000000001"
    assert append(client, run_id, [started, completed]).json()["accepted"] == 2
    assert client.get(f"/api/v1/runs/{run_id}/graph").json()["nodes"][0]["state"] == "completed"


def test_cross_project_run_cannot_be_accessed(client):
    other_project, other_run = str(uuid4()), str(uuid4())

    def provision(conn):
        conn.execute(
            "INSERT INTO projects(project_id,name,slug,created_at_ms) VALUES (?,?,?,1)",
            (other_project, "Other", "other"),
        )
        conn.execute(
            "INSERT INTO workflow_runs(run_id,project_id,name,mode,created_at_ms,updated_at_ms) "
            "VALUES (?,?,?,'observe',1,1)",
            (other_run, other_project, "Other run"),
        )

    client.app.state.db.write(provision)
    for suffix in ("", "/graph", "/timeline"):
        assert client.get(f"/api/v1/runs/{other_run}{suffix}").status_code == 404
    assert append(client, other_run, [event("workflow.started")]).status_code == 404
