"""Official protobuf messages with the OTLP-specific JSON hex-ID mapping."""

import base64
import json
import re
import sqlite3
from typing import Any
from uuid import UUID, uuid5

from google.protobuf.descriptor import Descriptor, FieldDescriptor
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.message import Message
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.trace.v1.trace_pb2 import Span

from swarmcircuit_server.db.store import now_ms
from swarmcircuit_server.errors import InvalidRecord
from swarmcircuit_server.ingest.events import MAX_INT, dump, outbox, require_row

ALLOWED = {
    "service.name",
    "service.version",
    "deployment.environment.name",
    "swarmcircuit.project_id",
    "swarmcircuit.run_id",
    "swarmcircuit.task_id",
    "swarmcircuit.agent_id",
    "swarmcircuit.approval_id",
    "swarmcircuit.operation_kind",
    "gen_ai.operation.name",
    "gen_ai.request.model",
    "gen_ai.system",
}
HEX = re.compile(r"^[0-9a-fA-F]+$")


def _json_ids(value: Any, descriptor: Descriptor) -> Any:
    if not isinstance(value, dict):
        return value
    result = {}
    fields = {field.json_name: field for field in descriptor.fields}
    for key, item in value.items():
        field = fields.get(key)
        if field is None:
            # Unknown fields must be ignored, including arbitrary nested values.
            continue
        if key in {"traceId", "spanId", "parentSpanId"}:
            if not isinstance(item, str) or (item and (not HEX.fullmatch(item) or len(item) % 2)):
                raise ValueError("OTLP JSON IDs must be hex strings")
            item = base64.b64encode(bytes.fromhex(item)).decode("ascii")
        elif field.type == FieldDescriptor.TYPE_ENUM:
            if isinstance(item, str) and not item.isdecimal():
                raise ValueError("OTLP JSON enum values must be numeric")
        elif field.message_type is not None:
            if isinstance(item, list):
                item = [_json_ids(v, field.message_type) for v in item]
            else:
                item = _json_ids(item, field.message_type)
        result[key] = item
    return result


def decode(body: bytes, is_json: bool) -> ExportTraceServiceRequest:
    request = ExportTraceServiceRequest()
    if is_json:

        def invalid_constant(_: str) -> None:
            raise ValueError("Non-finite JSON number")

        obj = json.loads(body, parse_constant=invalid_constant)
        if not isinstance(obj, dict):
            raise ValueError("OTLP JSON requires an object")
        ParseDict(_json_ids(obj, request.DESCRIPTOR), request, ignore_unknown_fields=True)
    else:
        request.ParseFromString(body)
    return request


def encoded(message: Message, is_json: bool) -> bytes:
    if is_json:
        return json.dumps(MessageToDict(message)).encode()
    return message.SerializeToString()


def attributes(values: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for kv in values:
        if kv.key not in ALLOWED:
            continue
        kind = kv.value.WhichOneof("value")
        if kind in {"string_value", "int_value", "bool_value"}:
            item = getattr(kv.value, kind)
            if not isinstance(item, str) or len(item) <= 250:
                result[kv.key] = item
    return result


def valid_id(value: bytes, length: int) -> str:
    if len(value) != length or not any(value):
        raise InvalidRecord("Invalid trace/span identifier")
    return value.hex()


def store_span(
    conn: sqlite3.Connection,
    project_id: str,
    source_id: str,
    span: Span,
    resource: dict[str, Any],
) -> None:
    attrs = {**resource, **attributes(span.attributes)}
    if attrs.get("swarmcircuit.project_id", project_id) != project_id:
        raise InvalidRecord("Project correlation mismatch")
    run_id = str(UUID(attrs["swarmcircuit.run_id"]))
    require_row(
        conn, "SELECT 1 FROM workflow_runs WHERE run_id=? AND project_id=?", (run_id, project_id)
    )
    aid = attrs.get("swarmcircuit.agent_id")
    tid = attrs.get("swarmcircuit.task_id")
    if aid:
        require_row(conn, "SELECT 1 FROM run_agents WHERE run_id=? AND agent_id=?", (run_id, aid))
    if tid:
        task = require_row(conn, "SELECT * FROM tasks WHERE run_id=? AND task_id=?", (run_id, tid))
        if aid and task["assigned_agent_id"] != aid:
            raise InvalidRecord("Task/agent correlation mismatch")
    if attrs.get("swarmcircuit.approval_id"):
        require_row(
            conn,
            "SELECT 1 FROM approvals WHERE run_id=? AND approval_id=?",
            (run_id, attrs["swarmcircuit.approval_id"]),
        )
    trace_id = valid_id(span.trace_id, 16)
    span_id = valid_id(span.span_id, 8)
    parent = valid_id(span.parent_span_id, 8) if span.parent_span_id else None
    if not 0 < span.start_time_unix_nano <= MAX_INT:
        raise InvalidRecord("Timestamp outside SQLite nanosecond range")
    end = span.end_time_unix_nano or None
    if end is not None and not span.start_time_unix_nano <= end <= MAX_INT:
        raise InvalidRecord("Invalid end timestamp")
    if not span.name or len(span.name) > 250:
        raise InvalidRecord("Invalid span name")
    links = [
        (valid_id(link.trace_id, 16), valid_id(link.span_id, 8), dump(attributes(link.attributes)))
        for link in span.links
    ]
    row_id = str(uuid5(UUID(run_id), f"span:{trace_id}:{span_id}"))
    # These normalized semantic fields define an immutable span replay.
    record = (
        run_id,
        project_id,
        source_id,
        trace_id,
        span_id,
        parent,
        span.name,
        str(span.kind),
        str(span.status.code),
        span.start_time_unix_nano,
        end,
        aid,
        tid,
        dump(attrs),
    )
    old = conn.execute("SELECT * FROM trace_spans WHERE span_row_id=?", (row_id,)).fetchone()
    if old:
        stored = tuple(
            old[k]
            for k in (
                "run_id",
                "project_id",
                "source_id",
                "trace_id",
                "span_id",
                "parent_span_id",
                "name",
                "span_kind",
                "status_code",
                "start_unix_ns",
                "end_unix_ns",
                "agent_id",
                "task_id",
                "attributes_json",
            )
        )
        old_links = [
            tuple(r)
            for r in conn.execute(
                "SELECT target_trace_id,target_span_id,attributes_json FROM span_links "
                "WHERE source_span_row_id=? ORDER BY link_id",
                (row_id,),
            )
        ]
        # The deterministic IDs preserve source link ordering.
        if stored != record or sorted(old_links) != sorted(links):
            raise InvalidRecord("Conflicting span replay")
        expected_events = [
            (e.name, e.time_unix_nano // 1_000_000, dump(attributes(e.attributes)))
            for e in span.events
        ]
        actual_events = [
            tuple(r)
            for r in conn.execute(
                "SELECT event_kind,occurred_at_ms,payload_json FROM run_events "
                "WHERE span_row_id=? ORDER BY source_event_key",
                (row_id,),
            )
        ]
        if sorted(actual_events) != sorted(expected_events):
            raise InvalidRecord("Conflicting span event replay")
        return
    conn.execute(
        "INSERT INTO trace_spans(span_row_id,run_id,project_id,source_id,trace_id,span_id,"
        "parent_span_id,name,span_kind,status_code,start_unix_ns,end_unix_ns,agent_id,task_id,"
        "attributes_json,received_at_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (row_id, *record, now_ms()),
    )
    for index, (trace, sid, data) in enumerate(links):
        conn.execute(
            "INSERT INTO span_links VALUES (?,?,?,?,?,?)",
            (str(uuid5(UUID(row_id), f"link:{index}")), run_id, row_id, trace, sid, data),
        )
    for index, event in enumerate(span.events):
        if not 0 < event.time_unix_nano <= MAX_INT or not event.name or len(event.name) > 100:
            raise InvalidRecord("Invalid span event")
        eid = str(uuid5(UUID(row_id), f"event:{index}"))
        conn.execute(
            "INSERT INTO run_events(event_id,run_id,project_id,source_id,source_event_key,"
            "event_kind,"
            "trust_class,agent_id,task_id,span_row_id,occurred_at_ms,ingested_at_ms,payload_json) "
            "VALUES (?,?,?,?,?,?,'self_report',?,?,?,?,?,?)",
            (
                eid,
                run_id,
                project_id,
                source_id,
                f"{row_id}:{index}",
                event.name,
                aid,
                tid,
                row_id,
                event.time_unix_nano // 1_000_000,
                now_ms(),
                dump(attributes(event.attributes)),
            ),
        )
    conn.execute(
        "UPDATE workflow_runs SET root_trace_id=COALESCE(root_trace_id,?),"
        "updated_at_ms=MAX(updated_at_ms,?) WHERE run_id=?",
        (trace_id, now_ms(), run_id),
    )
    outbox(conn, run_id, "span.appended", row_id)


def ingest_traces(
    conn: sqlite3.Connection, project_id: str, source_id: str, request: ExportTraceServiceRequest
) -> int:
    rejected = 0
    for resource_spans in request.resource_spans:
        resource = attributes(resource_spans.resource.attributes)
        for scope in resource_spans.scope_spans:
            for span in scope.spans:
                conn.execute("SAVEPOINT span_record")
                try:
                    store_span(conn, project_id, source_id, span, resource)
                except (InvalidRecord, ValueError, KeyError, TypeError, sqlite3.IntegrityError):
                    conn.execute("ROLLBACK TO span_record")
                    rejected += 1
                finally:
                    conn.execute("RELEASE span_record")
    return rejected
