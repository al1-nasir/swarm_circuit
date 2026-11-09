import gzip
import json
from uuid import uuid4

import pytest
from google.rpc.status_pb2 import Status
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)

from tests.conftest import register_task

NS = 1_793_491_200_123_456_789


def export_fixture(run_id, aid=None, tid=None):
    request = ExportTraceServiceRequest()
    resource = request.resource_spans.add()
    resource.resource.attributes.add(key="service.name").value.string_value = "test"
    span = resource.scope_spans.add().spans.add(
        trace_id=bytes.fromhex("1234567890abcdef1234567890abcdef"),
        span_id=bytes.fromhex("1234567890abcdef"),
        name="operation",
        start_time_unix_nano=NS,
        end_time_unix_nano=NS + 123_456,
    )
    span.attributes.add(key="swarmcircuit.run_id").value.string_value = run_id
    if aid:
        span.attributes.add(key="swarmcircuit.agent_id").value.string_value = aid
    if tid:
        span.attributes.add(key="swarmcircuit.task_id").value.string_value = tid
    span.attributes.add(key="gen_ai.input.messages").value.string_value = "SECRET"
    span.links.add(trace_id=b"x" * 16, span_id=b"y" * 8)
    span.events.add(name="tool.observed", time_unix_nano=NS + 42)
    return request


def post_binary(client, request):
    return client.post(
        "/v1/traces",
        content=request.SerializeToString(),
        headers={"Content-Type": "application/x-protobuf"},
    )


def test_binary_roundtrip_dedup_links_and_exact_ns(client, run_id):
    aid, tid = register_task(client, run_id)
    payload = export_fixture(run_id, aid, tid)
    for _ in range(2):
        response = post_binary(client, payload)
        assert response.status_code == 200, response.text
        result = ExportTraceServiceResponse.FromString(response.content)
        assert not result.HasField("partial_success")
    with client.app.state.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM trace_spans").fetchone()[0] == 1
        assert conn.execute("SELECT start_unix_ns FROM trace_spans").fetchone()[0] == NS
        assert conn.execute("SELECT COUNT(*) FROM span_links").fetchone()[0] == 1
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM run_events WHERE span_row_id IS NOT NULL"
            ).fetchone()[0]
            == 1
        )
    timeline = client.get(f"/api/v1/runs/{run_id}/timeline").json()
    span = next(i for i in timeline["items"] if i["item_type"] == "span")
    assert span["start_unix_ns"] == str(NS)
    assert span["trace_id"] == "1234567890abcdef1234567890abcdef"
    assert len(span["links"]) == 1
    assert "SECRET" not in json.dumps(timeline)


def test_otlp_json_hex_ids_numeric_enums_unknown_fields_and_gzip(client, run_id):
    payload = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "ABCDEF1234567890ABCDEF1234567890",
                                "spanId": "ABCDEF1234567890",
                                "name": "json-operation",
                                "kind": 1,
                                "status": {"code": 1},
                                "startTimeUnixNano": str(NS),
                                "endTimeUnixNano": str(NS + 1),
                                "attributes": [
                                    {"key": "swarmcircuit.run_id", "value": {"stringValue": run_id}}
                                ],
                                "newFutureField": {"ignored": True},
                            }
                        ]
                    }
                ]
            }
        ],
        "unknownTopLevel": True,
    }
    response = client.post(
        "/v1/traces",
        content=gzip.compress(json.dumps(payload).encode()),
        headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
    )
    assert response.status_code == 200
    assert response.json() == {}
    with client.app.state.db.read() as conn:
        assert (
            conn.execute("SELECT trace_id FROM trace_spans").fetchone()[0]
            == "abcdef1234567890abcdef1234567890"
        )


def test_partial_acceptance_and_conflicting_span_replay(client, run_id):
    payload = export_fixture(run_id)
    payload.resource_spans[0].scope_spans[0].spans.add().CopyFrom(
        payload.resource_spans[0].scope_spans[0].spans[0]
    )
    payload.resource_spans[0].scope_spans[0].spans[1].trace_id = b"bad"
    response = post_binary(client, payload)
    result = ExportTraceServiceResponse.FromString(response.content)
    assert result.partial_success.rejected_spans == 1
    assert response.status_code == 200
    original = export_fixture(run_id)
    original.resource_spans[0].scope_spans[0].spans[0].name = "changed"
    response = post_binary(client, original)
    assert (
        ExportTraceServiceResponse.FromString(response.content).partial_success.rejected_spans == 1
    )
    with client.app.state.db.read() as conn:
        assert conn.execute("SELECT name FROM trace_spans").fetchone()[0] == "operation"


@pytest.mark.parametrize(
    "mutate", ["zero_id", "bad_time", "cross_run_task", "spoof_project", "bad_link"]
)
def test_invalid_span_is_rejected_atomically(client, settings, run_id, mutate):
    payload = export_fixture(run_id)
    span = payload.resource_spans[0].scope_spans[0].spans[0]
    if mutate == "zero_id":
        span.trace_id = b"\0" * 16
    elif mutate == "bad_time":
        span.end_time_unix_nano = NS - 1
    elif mutate == "cross_run_task":
        other = client.post(
            f"/api/v1/projects/{settings.project_id}/runs",
            json={"name": "other", "mode": "observe"},
        ).json()["run_id"]
        _, tid = register_task(client, other)
        span.attributes.add(key="swarmcircuit.task_id").value.string_value = tid
    elif mutate == "spoof_project":
        span.attributes.add(key="swarmcircuit.project_id").value.string_value = str(uuid4())
    else:
        span.links[0].span_id = b"short"
    result = ExportTraceServiceResponse.FromString(post_binary(client, payload).content)
    assert result.partial_success.rejected_spans == 1
    with client.app.state.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM trace_spans").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM span_links").fetchone()[0] == 0


def test_parent_spans_and_reported_completion_do_not_create_dependencies_or_effects(client, run_id):
    aid, tid = register_task(client, run_id)
    payload = export_fixture(run_id, aid, tid)
    span = payload.resource_spans[0].scope_spans[0].spans[0]
    span.parent_span_id = b"p" * 8
    span.events[0].name = "task.completed"
    assert post_binary(client, payload).status_code == 200
    graph = client.get(f"/api/v1/runs/{run_id}/graph").json()
    assert graph["edges"] == []
    assert graph["nodes"][0]["state"] == "created"
    with client.app.state.db.read() as conn:
        assert (
            conn.execute(
                "SELECT trust_class FROM run_events WHERE span_row_id IS NOT NULL"
            ).fetchone()[0]
            == "self_report"
        )


def test_protocol_errors_are_status_messages(client):
    response = client.post(
        "/v1/traces", content=b"\xff\xff", headers={"Content-Type": "application/x-protobuf"}
    )
    assert response.status_code == 400
    assert Status.FromString(response.content).message
    response = client.post(
        "/v1/traces", content=b"bad-json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400
    assert response.json()["message"]
    assert (
        client.post("/v1/traces", content=b"", headers={"Content-Type": "text/plain"}).status_code
        == 415
    )
    assert (
        client.post(
            "/v1/traces",
            content=b"bad",
            headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
        ).status_code
        == 400
    )
    response = client.post(
        "/v1/traces",
        content=b"",
        headers={"Content-Type": "application/x-protobuf", "Authorization": ""},
    )
    assert response.status_code == 401
    assert Status.FromString(response.content).message


def test_gzip_bomb_and_streamed_body_limits(tmp_path):
    from fastapi.testclient import TestClient
    from swarmcircuit_server.app import create_app
    from swarmcircuit_server.config import Settings

    config = Settings(tmp_path / "small.db", "sdk-" + "a" * 32, "op-" + "b" * 32, max_bytes=512)
    with TestClient(
        create_app(config), headers={"Authorization": f"Bearer {config.sdk_token}"}
    ) as client:
        headers = {"Content-Type": "application/json", "Content-Encoding": "gzip"}
        response = client.post("/v1/traces", content=gzip.compress(b" " * 5000), headers=headers)
        assert response.status_code == 413
        assert response.json()["message"]
        response = client.post(
            "/v1/traces",
            content=iter([b"x" * 300, b"y" * 300]),
            headers={"Content-Type": "application/x-protobuf"},
        )
        assert response.status_code == 413


def test_empty_export_is_full_success(client):
    assert client.post("/v1/traces", json={"resourceSpans": []}).json() == {}
    assert post_binary(client, ExportTraceServiceRequest()).content == b""


def test_unknown_json_fields_are_ignored_without_interpreting_their_contents(client):
    response = client.post(
        "/v1/traces", json={"unknown": {"traceId": "not-hex", "code": "UNKNOWN"}}
    )
    assert response.status_code == 200
    assert response.json() == {}
