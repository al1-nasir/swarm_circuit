import httpx
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from swarmcircuit import SwarmCircuit

from examples.stalled_dependency import run_scenario


class HTTPTestExporter(SpanExporter):
    def __init__(self, client):
        self.client = client
        self.responses = []

    def export(self, spans):
        result = self.client.post(
            "/v1/traces",
            content=encode_spans(spans).SerializeToString(),
            headers={"Content-Type": "application/x-protobuf"},
        )
        self.responses.append(result)
        return SpanExportResult.SUCCESS


def test_six_agent_sdk_to_otlp_to_graph(client, settings):
    original_provider = trace.get_tracer_provider()
    provider = TracerProvider()
    exporter = HTTPTestExporter(client)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    try:
        with SwarmCircuit(
            settings.project_id,
            settings.sdk_token,
            client=client,
            tracer=provider.get_tracer("integration"),
        ) as sdk:
            summary = run_scenario(sdk, seed=7)
            assert sdk.flush()
        rid = summary["run_id"]
        assert len(exporter.responses) == 7  # six task spans plus workflow
        assert all(r.status_code == 200 and r.content == b"" for r in exporter.responses)
        graph = client.get(f"/api/v1/runs/{rid}/graph").json()
        assert len(graph["nodes"]) == 6
        assert len(graph["edges"]) == 5
        independent = next(n for n in graph["nodes"] if n["id"] == summary["independent_task_id"])
        assert independent["state"] == "completed"
        blocked = [n for n in graph["nodes"] if n["id"] in summary["blocked_task_ids"]]
        assert len(blocked) == 4
        assert all(n["state"] == "waiting_for_human" for n in blocked)
        assert all(n["deadline_at_ms"] < summary["logical_horizon_ms"] for n in blocked)
        assert client.get(f"/api/v1/runs/{rid}").json()["status"] == "waiting"
        assert len(client.get(f"/api/v1/runs/{rid}/graph?view=agent").json()["nodes"]) == 6
        with client.app.state.db.read() as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM approvals WHERE run_id=?", (rid,)).fetchone()[0]
                == 1
            )
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM approval_requests WHERE run_id=?", (rid,)
                ).fetchone()[0]
                == 4
            )
            assert (
                conn.execute("SELECT state FROM approvals WHERE run_id=?", (rid,)).fetchone()[0]
                == "pending"
            )
            assert (
                conn.execute("SELECT COUNT(*) FROM trace_spans WHERE run_id=?", (rid,)).fetchone()[
                    0
                ]
                == 7
            )
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert trace.get_tracer_provider() is original_provider
    finally:
        provider.shutdown()


class LostResponseClient:
    def __init__(self, client, path_suffix):
        self.client, self.path_suffix = client, path_suffix
        self.dropped = False

    def request(self, method, path, **kwargs):
        response = self.client.request(method, path, **kwargs)
        if path.endswith(self.path_suffix) and not self.dropped:
            self.dropped = True
            raise httpx.ReadError("Simulated lost response after durable commit")
        return response


def test_sdk_retries_stable_event_after_lost_response(client, settings):
    sdk = SwarmCircuit(
        settings.project_id,
        settings.sdk_token,
        client=LostResponseClient(client, "/events"),
        sleep=lambda _: None,
    )
    with sdk.run("lost-event-response") as run:
        with run.task("hello", agent="worker"):
            pass
    assert not sdk.telemetry_degraded
    with client.app.state.db.read() as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM run_events WHERE event_kind='workflow.started'"
            ).fetchone()[0]
            == 1
        )
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
    sdk.close()


def test_sdk_reconciles_lost_run_creation_response(client, settings):
    sdk = SwarmCircuit(
        settings.project_id,
        settings.sdk_token,
        client=LostResponseClient(client, "/runs"),
        sleep=lambda _: None,
    )
    first = sdk.run("lost-run-response", external_run_key="stable-run-key")
    second = sdk.run("lost-run-response", external_run_key="stable-run-key")
    assert first.run_id == second.run_id
    with client.app.state.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0] == 1


def test_sdk_bounded_outage_queue_and_recovery(client, settings):
    class Offline:
        def request(self, *args, **kwargs):
            raise httpx.ConnectError("offline")

    sdk = SwarmCircuit(
        settings.project_id,
        settings.sdk_token,
        client=client,
        pending_limit=2,
        attempts=1,
        sleep=lambda _: None,
    )
    run = sdk.run("offline-test")
    sdk.client = Offline()
    for _ in range(3):
        sdk.emit(run.run_id, "workflow.observed")
    assert sdk.telemetry_degraded
    assert len(sdk.pending) == 2
    assert sdk.dropped_events == 1
    sdk.client = client
    assert not sdk.flush()  # The dropped event remains a disclosed coverage gap.
    assert len(sdk.pending) == 0
    with client.app.state.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM run_events").fetchone()[0] == 2


def test_approval_scope_fingerprint_preserves_separate_authority(client, settings):
    sdk = SwarmCircuit(settings.project_id, settings.sdk_token, client=client)
    with sdk.run("approval-scopes") as run:
        t1 = run.task("one", agent="a")
        t2 = run.task("two", agent="b")
        scope = {
            "principal": "p",
            "purpose": "read",
            "resource": "r",
            "counterparty": "v",
            "permission_scope": "read",
            "policy_revision": "1",
            "amount": "1",
            "asset": "MOCK",
        }
        a1 = t1.wait_for_approval(scope)
        a2 = t2.wait_for_approval({**scope, "principal": "someone-else"})
        assert a1 != a2
    with client.app.state.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 2


def test_sdk_context_propagation_and_sequential_tasks(client, settings):
    provider = TracerProvider()
    sdk = SwarmCircuit(
        settings.project_id,
        settings.sdk_token,
        client=client,
        tracer=provider.get_tracer("context"),
    )
    try:
        with sdk.run("sequential") as run:
            headers = run.trace_headers()
            assert len(headers["traceparent"].split("-")[1]) == 32
            with run.task("first", agent="a"):
                pass
            assert client.get(f"/api/v1/runs/{run.run_id}").json()["status"] == "running"
            with run.task("second", agent="b"):
                pass
        assert client.get(f"/api/v1/runs/{run.run_id}").json()["status"] == "completed"
    finally:
        provider.shutdown()
