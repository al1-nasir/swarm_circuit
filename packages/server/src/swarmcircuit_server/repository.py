"""Project-scoped identity and stable, read-only workflow projections."""

import base64
import json
import sqlite3
from typing import Any
from uuid import uuid4

from swarmcircuit_server.config import Settings
from swarmcircuit_server.db.store import now_ms
from swarmcircuit_server.errors import Problem
from swarmcircuit_server.ingest.events import outbox
from swarmcircuit_server.workflow_kind import diagnostic_sql


def bootstrap(conn: sqlite3.Connection, settings: Settings) -> None:
    conn.execute(
        "INSERT INTO projects(project_id,name,slug,created_at_ms) VALUES (?,?,?,?) "
        "ON CONFLICT(project_id) DO NOTHING",
        (settings.project_id, "Local SwarmCircuit", "local", now_ms()),
    )
    for kind in ("sdk", "otlp"):
        conn.execute(
            "INSERT INTO telemetry_sources(source_id,project_id,source_key,source_kind,"
            "display_name,created_at_ms) VALUES (?,?,?,?,?,?) ON CONFLICT(project_id,source_key) "
            "DO NOTHING",
            (
                settings.source_id(kind),
                settings.project_id,
                f"local:{kind}",
                kind,
                f"Local {kind}",
                now_ms(),
            ),
        )


def get_run(conn: sqlite3.Connection, project_id: str, run_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM workflow_runs WHERE run_id=? AND project_id=?",
        (run_id, project_id),
    ).fetchone()
    if not row:
        raise Problem(404, "not_found", "Run not found in this project")
    result = dict(row)
    result["metadata"] = json.loads(result.pop("metadata_json"))
    result["state_evidence"] = "sdk_observation"
    result["open_incident_count"] = conn.execute(
        "SELECT COUNT(*) FROM incidents WHERE run_id=? AND state IN ('open','acknowledged')",
        (run_id,),
    ).fetchone()[0]
    return result


def create_run(
    conn: sqlite3.Connection,
    project_id: str,
    name: str,
    mode: str,
    external_key: str | None,
    simulation: bool = False,
) -> dict[str, Any]:
    rid, timestamp = str(uuid4()), now_ms()
    try:
        conn.execute(
            "INSERT INTO workflow_runs(run_id,project_id,name,mode,external_run_key,created_at_ms,"
            "updated_at_ms,metadata_json) VALUES (?,?,?,?,?,?,?,?)",
            (
                rid,
                project_id,
                name,
                mode,
                external_key,
                timestamp,
                timestamp,
                json.dumps({"simulation": simulation}),
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise Problem(409, "run_conflict", "External run key is already registered") from exc
    outbox(conn, rid, "run.created", rid)
    return get_run(conn, project_id, rid)


def encode_cursor(values: list[Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(values).encode()).decode()


def decode_cursor(cursor: str | None, length: int) -> list[Any] | None:
    if not cursor:
        return None
    try:
        data = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        if (
            not isinstance(data, list)
            or len(data) != length
            or type(data[0]) is not int
            or any(not isinstance(v, str) for v in data[1:])
        ):
            raise ValueError("Invalid cursor shape")
        return data
    except (ValueError, TypeError) as exc:
        raise Problem(422, "invalid_cursor", "Malformed pagination cursor") from exc


def list_runs(
    conn: sqlite3.Connection,
    project_id: str,
    limit: int,
    cursor: str | None,
    kind: str = "all",
    include_diagnostics: bool = True,
) -> dict[str, Any]:
    key = decode_cursor(cursor, 2)
    where, args = "project_id=?", [project_id]
    if kind == "workflow":
        where += " AND COALESCE(json_extract(metadata_json,'$.research'),0)=0"
    elif kind == "research":
        where += " AND json_extract(metadata_json,'$.research')=1"
    if not include_diagnostics:
        where += " AND NOT " + diagnostic_sql()
    if key:
        where += " AND (created_at_ms,run_id)<(?,?)"
        args.extend(key)
    rows = conn.execute(
        f"SELECT run_id,created_at_ms FROM workflow_runs WHERE {where} "
        "ORDER BY created_at_ms DESC,run_id DESC LIMIT ?",
        (*args, limit + 1),
    ).fetchall()
    items = []
    for row in rows[:limit]:
        item = get_run(conn, project_id, row["run_id"])
        item["agent_count"] = conn.execute(
            "SELECT COUNT(*) FROM run_agents WHERE run_id=?",
            (row["run_id"],),
        ).fetchone()[0]
        items.append(item)
    next_cursor = (
        encode_cursor([rows[limit - 1]["created_at_ms"], rows[limit - 1]["run_id"]])
        if len(rows) > limit
        else None
    )
    return {"items": items, "next_cursor": next_cursor}


def graph(conn: sqlite3.Connection, run_id: str, view: str) -> dict[str, Any]:
    tasks = conn.execute(
        "SELECT * FROM tasks WHERE run_id=? ORDER BY task_id", (run_id,)
    ).fetchall()
    dependencies = conn.execute(
        "SELECT * FROM task_dependencies WHERE run_id=? AND is_explicit=1 ORDER BY dependency_id",
        (run_id,),
    ).fetchall()
    nodes, edges = [], []
    if view == "task":
        nodes = [
            {
                "id": t["task_id"],
                "node_kind": "task",
                "label": t["title"],
                "state": t["state"],
                "state_version": t["state_version"],
                "agent_id": t["assigned_agent_id"],
                "deadline_at_ms": t["deadline_at_ms"],
                "evidence_kind": "explicit",
                "trust_class": "sdk_observation",
                "control_available": False,
            }
            for t in tasks
        ]
        edges = [
            {
                "id": d["dependency_id"],
                "source": d["blocked_task_id"],
                "target": d["prerequisite_task_id"],
                "relation_kind": d["relation_kind"],
                "evidence_kind": "explicit",
                "evidence_event_id": d["evidence_event_id"],
            }
            for d in dependencies
        ]
    else:
        agents = conn.execute(
            "SELECT a.* FROM agents a JOIN run_agents r ON a.agent_id=r.agent_id "
            "WHERE r.run_id=? ORDER BY a.agent_id",
            (run_id,),
        ).fetchall()
        nodes = [
            {
                "id": a["agent_id"],
                "node_kind": "agent",
                "label": a["display_name"],
                "role": a["role"],
                "evidence_kind": "explicit",
                "control_available": False,
            }
            for a in agents
        ]
        messages = conn.execute(
            "SELECT * FROM agent_messages WHERE run_id=? ORDER BY message_id",
            (run_id,),
        ).fetchall()
        edges = [
            {
                "id": m["message_id"],
                "source": m["from_agent_id"],
                "target": m["to_agent_id"],
                "relation_kind": "delegates_to",
                "evidence_kind": "explicit",
                "evidence_event_id": m["evidence_event_id"],
            }
            for m in messages
        ]
    version = conn.execute(
        "SELECT (SELECT COUNT(*) FROM run_events WHERE run_id=?) + "
        "(SELECT COUNT(*) FROM trace_spans WHERE run_id=?)",
        (run_id, run_id),
    ).fetchone()[0]
    overlays: dict[str, list[str]] = {}
    active_incidents = conn.execute(
        "SELECT incident_id,evidence_summary FROM incidents WHERE run_id=? "
        "AND state IN ('open','acknowledged')",
        (run_id,),
    ).fetchall()
    for incident in active_incidents:
        summary = json.loads(incident["evidence_summary"])
        for task_id in summary.get("affected_task_ids", []):
            overlays.setdefault(task_id, []).append(incident["incident_id"])
    for node in nodes:
        if view == "task":
            node["incident_ids"] = sorted(overlays.get(node["id"], []))
    return {
        "run_id": run_id,
        "projection_version": version,
        "view": view,
        "nodes": nodes,
        "edges": edges,
        "incident_ids": sorted(r["incident_id"] for r in active_incidents),
        "control_available": False,
        "coverage": "Explicit SDK declarations only; span ancestry is not a dependency",
    }


def timeline(
    conn: sqlite3.Connection, run_id: str, cursor: str | None, limit: int
) -> dict[str, Any]:
    key = decode_cursor(cursor, 3)
    condition = "WHERE (occurred_at_ms,id,item_type)<(?,?,?)" if key else ""
    rows = conn.execute(
        "SELECT * FROM (SELECT event_id AS id,'event' AS item_type,occurred_at_ms "
        "FROM run_events WHERE run_id=? UNION ALL SELECT span_row_id AS id,'span' AS item_type,"
        "start_unix_ns/1000000 AS occurred_at_ms FROM trace_spans WHERE run_id=?) "
        f"{condition} ORDER BY occurred_at_ms DESC,id DESC,item_type DESC LIMIT ?",
        (run_id, run_id, *(key or []), limit + 1),
    ).fetchall()
    items = []
    for item in rows[:limit]:
        entry = dict(item)
        if item["item_type"] == "event":
            row = conn.execute(
                "SELECT * FROM run_events WHERE event_id=?", (item["id"],)
            ).fetchone()
            entry.update(dict(row))
            entry["payload"] = json.loads(entry.pop("payload_json"))
            entry["label"] = entry["event_kind"]
        else:
            row = conn.execute(
                "SELECT * FROM trace_spans WHERE span_row_id=?", (item["id"],)
            ).fetchone()
            entry.update(dict(row))
            entry["attributes"] = json.loads(entry.pop("attributes_json"))
            entry["label"] = entry["name"]
            entry["trust_class"] = "self_report"
            # JSON numbers lose precision in JavaScript. Preserve exact ns as decimal strings.
            entry["start_unix_ns"] = str(entry["start_unix_ns"])
            if entry["end_unix_ns"] is not None:
                entry["end_unix_ns"] = str(entry["end_unix_ns"])
            entry["links"] = [
                dict(r)
                for r in conn.execute(
                    "SELECT target_trace_id,target_span_id,attributes_json FROM span_links "
                    "WHERE source_span_row_id=? ORDER BY link_id",
                    (item["id"],),
                )
            ]
        items.append(entry)
    next_cursor = (
        encode_cursor(
            [rows[limit - 1]["occurred_at_ms"], rows[limit - 1]["id"], rows[limit - 1]["item_type"]]
        )
        if len(rows) > limit
        else None
    )
    return {"items": items, "next_cursor": next_cursor}
