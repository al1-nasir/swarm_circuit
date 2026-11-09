"""Read-only Studio amendments; commands still use the existing validated operator path."""

import json
from typing import Any
from uuid import UUID

from fastapi import Depends, FastAPI, Query, Request, WebSocket

from swarmcircuit_server.controller.service import command
from swarmcircuit_server.errors import Problem
from swarmcircuit_server.realtime import stream
from swarmcircuit_server.repository import decode_cursor, encode_cursor


def install(app: FastAPI, read_auth: Any, run_access: Any) -> None:
    @app.post(
        "/api/v1/runs/{run_id}/stream-tickets",
        dependencies=[Depends(read_auth)],
        operation_id="createStreamTicket",
    )
    def ticket(request: Request, run_id: UUID) -> dict[str, Any]:
        return request.app.state.stream_tickets.mint(run_access(request, run_id))

    @app.websocket("/api/v1/ws/runs/{run_id}")
    async def websocket(websocket: WebSocket, run_id: UUID) -> None:
        await stream(websocket, str(run_id))

    @app.get(
        "/api/v1/runs/{run_id}/control-commands",
        dependencies=[Depends(read_auth)],
        operation_id="listControlCommands",
    )
    def commands(
        request: Request,
        run_id: UUID,
        limit: int = Query(50, ge=1, le=200),
        cursor: str | None = None,
    ) -> dict[str, Any]:
        rid = run_access(request, run_id)
        request.app.state.control.write(lambda conn, at: None)
        key = decode_cursor(cursor, 2)
        condition = " AND (created_at_ms,command_id)<(?,?)" if key else ""
        with request.app.state.db.read() as conn:
            rows = conn.execute(
                "SELECT command_id,created_at_ms FROM control_commands WHERE run_id=?"
                + condition
                + " ORDER BY created_at_ms DESC,command_id DESC LIMIT ?",
                (rid, *(key or []), limit + 1),
            ).fetchall()
            return {
                "items": [
                    command(conn, request.app.state.settings.project_id, r["command_id"])
                    for r in rows[:limit]
                ],
                "next_cursor": encode_cursor(
                    [rows[limit - 1]["created_at_ms"], rows[limit - 1]["command_id"]]
                )
                if len(rows) > limit
                else None,
            }

    @app.get(
        "/api/v1/runs/{run_id}/evidence/{entity_id}",
        dependencies=[Depends(read_auth)],
        operation_id="getRunEvidence",
    )
    def evidence(request: Request, run_id: UUID, entity_id: UUID) -> dict[str, Any]:
        rid = run_access(request, run_id)
        with request.app.state.db.read() as conn:
            found = conn.execute(
                "SELECT * FROM run_events WHERE run_id=? AND event_id=?", (rid, str(entity_id))
            ).fetchone()
            if found:
                item = dict(found)
                item.update(id=item["event_id"], item_type="event", label=item["event_kind"])
                item["payload"] = json.loads(item.pop("payload_json"))
                return item
            found = conn.execute(
                "SELECT * FROM trace_spans WHERE run_id=? AND span_row_id=?", (rid, str(entity_id))
            ).fetchone()
            if not found:
                raise Problem(404, "not_found", "Evidence not found in this run")
            item = dict(found)
            item.update(
                id=item["span_row_id"],
                item_type="span",
                label=item["name"],
                trust_class="self_report",
            )
            item["attributes"] = json.loads(item.pop("attributes_json"))
            item["start_unix_ns"] = str(item["start_unix_ns"])
            if item["end_unix_ns"] is not None:
                item["end_unix_ns"] = str(item["end_unix_ns"])
            return item
