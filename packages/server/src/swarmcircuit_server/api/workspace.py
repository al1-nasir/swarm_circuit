"""Human-readable, source-bound workflow summaries and discoverable control history."""

import json
import sqlite3
from collections import Counter
from typing import Any
from uuid import UUID

from fastapi import Depends, FastAPI, Query, Request, Response

from swarmcircuit_server.config import Settings
from swarmcircuit_server.controller.service import command
from swarmcircuit_server.detectors.rules import reverse_closure
from swarmcircuit_server.errors import Problem
from swarmcircuit_server.repository import decode_cursor, encode_cursor, get_run
from swarmcircuit_server.workflow_kind import classify

TERMINAL = {"completed", "failed", "cancelled"}


def _sessions(
    conn: sqlite3.Connection, config: Settings, rid: str, at: int
) -> list[dict[str, Any]]:
    sessions = [
        dict(r)
        for r in conn.execute(
            "SELECT s.runtime_session_id,s.state,s.runtime_key,s.fencing_epoch,"
            "s.last_heartbeat_ms,k.expires_at_ms FROM runtime_sessions s JOIN "
            "runtime_credentials k ON k.runtime_session_id=s.runtime_session_id WHERE s.run_id=?",
            (rid,),
        )
    ]
    newest: dict[str, int] = {}
    for s in sessions:
        newest[s["runtime_key"]] = max(newest.get(s["runtime_key"], 0), s["fencing_epoch"])
    for s in sessions:
        s["connected"] = (
            s["state"] == "connected"
            and s["expires_at_ms"] > at
            and at - s["last_heartbeat_ms"] < config.runtime_heartbeat_timeout_ms
            and s["fencing_epoch"] == newest[s["runtime_key"]]
        )
    return sessions


def brief(conn: sqlite3.Connection, config: Settings, rid: str, at: int) -> dict[str, Any]:
    run = get_run(conn, config.project_id, rid)
    # Metadata is supplied by hosts. Only the server-owned session relation can
    # provide a navigable walkthrough identity or an authoritative end reason.
    demo = conn.execute(
        "SELECT demo_id,state,permission FROM guided_demo_sessions WHERE run_id=? AND project_id=?",
        (rid, config.project_id),
    ).fetchone()
    demo_reason = {
        "denied": "Sample dataset permission was denied; protected work did not execute.",
        "expired": "The ten-minute local worker expired. Saved outputs are retained.",
        "interrupted": "The local worker was interrupted. Saved outputs are retained.",
        "failed": "The local worker failed before completing. Saved outputs are retained.",
    }.get(demo["state"] if demo else "")
    tasks = [
        dict(t)
        for t in conn.execute(
            "SELECT task_id,title,state FROM tasks WHERE run_id=? ORDER BY created_at_ms,task_id",
            (rid,),
        )
    ]
    state_counts = Counter(t["state"] for t in tasks)
    approvals = [
        dict(a)
        for a in conn.execute(
            "SELECT approval_id,related_task_id,requested_at_ms FROM approvals "
            "WHERE run_id=? AND state='pending' ORDER BY requested_at_ms,approval_id",
            (rid,),
        )
    ]
    dependencies = [
        dict(d)
        for d in conn.execute(
            "SELECT blocked_task_id,prerequisite_task_id FROM task_dependencies "
            "WHERE run_id=? AND is_explicit=1",
            (rid,),
        )
    ]
    unfinished = {t["task_id"] for t in tasks if t["state"] not in TERMINAL}
    root_ids = {a["related_task_id"] for a in approvals if a["related_task_id"]}
    affected = reverse_closure(root_ids, dependencies) & unfinished
    # "Unaffected" means outside this declared gate closure, never proof of readiness.
    unaffected = {t["task_id"] for t in tasks} - reverse_closure(root_ids, dependencies)
    sessions = _sessions(conn, config, rid, at)
    connected_ids = {s["runtime_session_id"] for s in sessions if s["connected"]}
    latest = conn.execute(
        "SELECT c.command_id,c.command_kind,c.task_id,c.runtime_session_id,"
        "c.session_fencing_epoch,a.received_at_ms FROM control_commands c "
        "JOIN control_acknowledgements a ON a.command_id=c.command_id AND a.result='applied' "
        "AND a.runtime_session_id=c.runtime_session_id "
        "AND a.session_fencing_epoch=c.session_fencing_epoch "
        "WHERE c.run_id=? AND c.state='applied' ORDER BY a.received_at_ms DESC,c.command_id DESC "
        "LIMIT 1",
        (rid,),
    ).fetchone()
    last_confirmation = None
    if latest:
        last_confirmation = {
            "command_id": latest["command_id"],
            "kind": latest["command_kind"],
            "task_id": latest["task_id"],
            "at_ms": latest["received_at_ms"],
            "host_connected": latest["runtime_session_id"] in connected_ids,
        }
    count, total = state_counts["completed"], len(tasks)
    if run["status"] in TERMINAL and run["open_incident_count"]:
        headline = "Workflow ended with findings to review"
        explanation = (
            (demo_reason + " " if demo_reason else "")
            + f"{run['open_incident_count']} open finding"
            + ("s remain" if run["open_incident_count"] != 1 else " remains")
            + "; review the recorded evidence."
        )
        action = {"label": "Review saved findings", "href": f"/runs/{rid}?tab=incidents"}
    elif run["status"] in {"cancelled", "failed"}:
        headline = (
            {
                "denied": "Sample access was denied",
                "expired": "This walkthrough expired",
                "interrupted": "This walkthrough was interrupted",
                "failed": "This walkthrough could not finish",
            }.get(demo["state"])
            if demo
            else None
        ) or (
            "This workflow failed" if run["status"] == "failed" else "This workflow was cancelled"
        )
        explanation = (
            demo_reason + " " if demo_reason else ""
        ) + f"{count} of {total} tasks completed."
        if approvals:
            explanation += " Pending requests are historical; this run is no longer active."
        action = (
            {"label": "Read saved outputs", "href": f"/demo?demo={demo['demo_id']}"}
            if demo
            else {"label": "Inspect saved workflow", "href": f"/runs/{rid}?tab=timeline"}
        )
    elif approvals:
        headline = f"{len(affected)} task{'s' if len(affected) != 1 else ''} waiting for permission"
        explanation = (
            f"{len(approvals)} permission request{'s are' if len(approvals) != 1 else ' is'} "
            f"pending. {count} of {total} tasks are complete."
        )
        action = (
            {"label": "Review sample access", "href": f"/demo?demo={demo['demo_id']}"}
            if demo
            else {"label": "Review permission wait", "href": f"/runs/{rid}?tab=approvals"}
        )
    elif state_counts["failed"]:
        headline = (
            f"{state_counts['failed']} task{'s' if state_counts['failed'] != 1 else ''} failed"
        )
        explanation = (
            f"{count} of {total} tasks are complete. Inspect the recorded failure evidence."
        )
        action = {"label": "Inspect recorded events", "href": f"/runs/{rid}?tab=timeline"}
    elif total and count == total:
        headline = "All recorded tasks completed"
        explanation = f"{count} of {total} tasks are complete according to host observations."
        action = (
            {"label": "Read sales brief", "href": f"/demo?demo={demo['demo_id']}"}
            if demo and demo["state"] == "completed"
            else {"label": "Inspect workflow results", "href": f"/runs/{rid}?tab=graph"}
        )
    elif state_counts["held"]:
        headline = (
            f"{state_counts['held']} "
            + ("task is" if state_counts["held"] == 1 else "tasks are")
            + " paused"
        )
        explanation = (
            "Permission and operator pauses are separate. Review the confirmed pauses "
            "and resume eligible tasks explicitly."
        )
        action = {"label": "Review paused tasks", "href": f"/runs/{rid}?tab=commands"}
    elif run["open_incident_count"]:
        headline = "A workflow finding needs review"
        explanation = "Inspect the source evidence before deciding whether to intervene."
        action = {"label": "Review findings", "href": f"/runs/{rid}?tab=incidents"}
    elif connected_ids:
        headline = "Workers are connected"
        explanation = f"{count} of {total} tasks are complete. Live host heartbeats are current."
        action = {"label": "Open live workflow", "href": f"/runs/{rid}?tab=graph"}
    else:
        headline = "Recorded workflow"
        explanation = (
            f"{count} of {total} tasks are complete. "
            "No currently connected control host is recorded; lifecycle status is historical."
        )
        action = {"label": "Inspect recorded workflow", "href": f"/runs/{rid}?tab=graph"}
    return {
        "run": run,
        "as_of_ms": at,
        "classification": classify(run["name"], run["metadata"]),
        "guided_demo": {"demo_id": demo["demo_id"], "state": demo["state"]} if demo else None,
        "progress": {
            "completed": count,
            "total": total,
            "waiting": len(
                affected | {t["task_id"] for t in tasks if t["state"] == "waiting_for_human"}
            ),
            "held": state_counts["held"],
            "failed": state_counts["failed"],
        },
        "connection": {
            "state": "connected" if connected_ids else "offline" if sessions else "not_integrated",
            "connected_workers": len(connected_ids),
            "last_heartbeat_ms": max((s["last_heartbeat_ms"] for s in sessions), default=None),
        },
        "headline": headline,
        "explanation": explanation,
        "next_action": action,
        "pending_approvals": len(approvals),
        "affected_task_ids": sorted(affected),
        "unaffected_task_ids": sorted(unaffected),
        "last_confirmation": last_confirmation,
        "tasks": tasks,
        "open_incident_count": run["open_incident_count"],
    }


def install(app: FastAPI, read_auth: Any, run_access: Any) -> None:
    @app.get(
        "/api/v1/runs/{run_id}/brief",
        dependencies=[Depends(read_auth)],
        operation_id="getWorkflowBrief",
    )
    def run_brief(request: Request, run_id: UUID, response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        rid = run_access(request, run_id)
        at = request.app.state.control.clock()
        with request.app.state.db.read() as conn:
            return brief(conn, request.app.state.settings, rid, at)

    @app.get(
        "/api/v1/projects/{project_id}/workspace",
        dependencies=[Depends(read_auth)],
        operation_id="getWorkspaceSummary",
    )
    def workspace(
        request: Request,
        project_id: UUID,
        response: Response,
        limit: int = Query(20, ge=1, le=50),
        include_diagnostics: bool = False,
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        config = request.app.state.settings
        if str(project_id) != config.project_id:
            raise Problem(404, "not_found", "Project not found")
        at = request.app.state.control.clock()
        with request.app.state.db.read() as conn:
            rows = [
                dict(r)
                for r in conn.execute(
                    "SELECT run_id,name,status,metadata_json FROM workflow_runs WHERE project_id=? "
                    "ORDER BY created_at_ms DESC,run_id DESC",
                    (config.project_id,),
                )
            ]
            workflow_rows = []
            counts = {
                k: 0
                for k in (
                    "recorded_workflows",
                    "diagnostic_workflows",
                    "research_trials",
                    "completed_workflows",
                    "recorded_running",
                    "recorded_waiting",
                    "connected_workflows",
                    "connected_workers",
                    "needs_attention",
                )
            }
            for row in rows:
                kind = classify(row["name"], json.loads(row["metadata_json"]))
                if kind == "research":
                    counts["research_trials"] += 1
                    continue
                if kind == "diagnostic":
                    counts["diagnostic_workflows"] += 1
                    if include_diagnostics:
                        workflow_rows.append(row)
                    continue
                counts["recorded_workflows"] += 1
                counts["completed_workflows"] += row["status"] == "completed"
                counts["recorded_running"] += row["status"] == "running"
                counts["recorded_waiting"] += row["status"] == "waiting"
                workflow_rows.append(row)
            # Counts are project-wide; displayed rows remain deliberately bounded.
            # Bulk reads avoid an N+1 query over potentially thousands of old runs.
            active_rows = [
                dict(r)
                for r in conn.execute(
                    "SELECT DISTINCT s.run_id,s.runtime_session_id FROM runtime_sessions s "
                    "JOIN runtime_credentials k ON k.runtime_session_id=s.runtime_session_id "
                    "JOIN workflow_runs r ON r.run_id=s.run_id WHERE r.project_id=? "
                    "AND s.state='connected' AND k.expires_at_ms>? AND s.last_heartbeat_ms>? "
                    "AND s.fencing_epoch=(SELECT MAX(s2.fencing_epoch) FROM runtime_sessions s2 "
                    "WHERE s2.run_id=s.run_id AND s2.runtime_key=s.runtime_key)",
                    (config.project_id, at, at - config.runtime_heartbeat_timeout_ms),
                )
            ]
            ordinary_ids = {
                r["run_id"]
                for r in workflow_rows
                if classify(r["name"], json.loads(r["metadata_json"])) == "workflow"
            }
            active_ids = {r["run_id"] for r in active_rows if r["run_id"] in ordinary_ids}
            counts["connected_workflows"] = len(active_ids)
            counts["connected_workers"] = sum(r["run_id"] in ordinary_ids for r in active_rows)
            attention_rows = conn.execute(
                "SELECT r.run_id FROM workflow_runs r WHERE r.project_id=? AND ("
                "(r.status NOT IN ('completed','failed','cancelled') AND "
                "EXISTS(SELECT 1 FROM approvals a WHERE a.run_id=r.run_id AND a.state='pending')) "
                "OR EXISTS(SELECT 1 FROM incidents i WHERE i.run_id=r.run_id "
                "AND i.state IN ('open','acknowledged')) OR "
                "EXISTS(SELECT 1 FROM tasks t WHERE t.run_id=r.run_id AND t.state='failed'))",
                (config.project_id,),
            ).fetchall()
            attention_ids = {r["run_id"] for r in attention_rows} & ordinary_ids
            counts["needs_attention"] = len(attention_ids)
            displayed = [brief(conn, config, r["run_id"], at) for r in workflow_rows[:limit]]
            attention_candidates = [r for r in workflow_rows if r["run_id"] in attention_ids][
                :limit
            ]
            attention = [brief(conn, config, r["run_id"], at) for r in attention_candidates]
            return {
                "project_id": config.project_id,
                "as_of_ms": at,
                "counts": counts,
                "items": displayed,
                "attention": attention,
            }

    @app.get(
        "/api/v1/runs/{run_id}/backpressure/history",
        dependencies=[Depends(read_auth)],
        operation_id="listBackpressureHistory",
    )
    def policy_history(
        request: Request,
        run_id: UUID,
        response: Response,
        limit: int = Query(25, ge=1, le=100),
        cursor: str | None = None,
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        rid = run_access(request, run_id)
        request.app.state.control.write(lambda conn, at: None)
        key = decode_cursor(cursor, 2)
        condition = " AND (created_at_ms,request_id)<(?,?)" if key else ""
        with request.app.state.db.read() as conn:
            rows = conn.execute(
                "SELECT request_id,idempotency_key,result_json,created_at_ms FROM "
                "control_policy_requests WHERE run_id=?"
                + condition
                + " ORDER BY created_at_ms DESC,request_id DESC LIMIT ?",
                (rid, *(key or []), limit + 1),
            ).fetchall()
            items = []
            for row in rows[:limit]:
                item = json.loads(row["result_json"])
                item.update(
                    policy_request_id=row["request_id"],
                    idempotency_key=row["idempotency_key"],
                    created_at_ms=row["created_at_ms"],
                )
                item["commands"] = [
                    command(conn, request.app.state.settings.project_id, cid)
                    for cid in item["command_ids"]
                ]
                items.append(item)
            unconfirmed_count = conn.execute(
                "SELECT COUNT(DISTINCT c.command_id) FROM control_policy_requests p "
                "JOIN json_each(p.result_json,'$.command_ids') j "
                "JOIN control_commands c ON c.command_id=j.value "
                "WHERE p.run_id=? AND c.state IN ('queued','dispatched','unknown')",
                (rid,),
            ).fetchone()[0]
            return {
                "items": items,
                "unconfirmed_count": unconfirmed_count,
                "next_cursor": encode_cursor(
                    [rows[limit - 1]["created_at_ms"], rows[limit - 1]["request_id"]]
                )
                if len(rows) > limit
                else None,
            }
