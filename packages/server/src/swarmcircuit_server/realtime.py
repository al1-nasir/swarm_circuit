"""Read-only outbox invalidations with durable cursors and one-use scoped upgrade tickets."""

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
from collections.abc import Callable
from threading import Lock
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from swarmcircuit_server.db.store import Database, now_ms
from swarmcircuit_server.errors import Problem


class StreamTickets:
    def __init__(self, clock: Callable[[], int] = now_ms) -> None:
        self.clock, self.key = clock, secrets.token_bytes(32)
        self.used: dict[str, int] = {}
        self.lock = Lock()

    def mint(self, run_id: str) -> dict[str, Any]:
        expires = self.clock() + 60_000
        raw = json.dumps(
            {"run_id": run_id, "expires": expires, "nonce": secrets.token_hex(16)},
            separators=(",", ":"),
        ).encode()
        payload = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        signature = hmac.new(self.key, payload.encode(), hashlib.sha256).hexdigest()
        return {
            "ticket": payload + "." + signature,
            "expires_at_ms": expires,
            "protocol": "swarmcircuit.v1",
            "run_id": run_id,
        }

    def consume(self, ticket: str, run_id: str) -> bool:
        try:
            if len(ticket) > 600:
                return False
            payload, signature = ticket.split(".")
            expected = hmac.new(self.key, payload.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                return False
            body = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            at = self.clock()
            if body["run_id"] != run_id or not at < body["expires"] <= at + 60_000:
                return False
            with self.lock:
                self.used = {key: expiry for key, expiry in self.used.items() if expiry > at}
                if body["nonce"] in self.used or len(self.used) >= 5000:
                    return False
                self.used[body["nonce"]] = body["expires"]
            return True
        except (ValueError, TypeError, KeyError):
            return False


def snapshot(db: Database, project_id: str, run_id: str, after: int | None) -> dict[str, Any]:
    with db.read() as conn:
        # db.read() keeps head, source version and invalidations in one read snapshot.
        if not conn.execute(
            "SELECT 1 FROM workflow_runs WHERE project_id=? AND run_id=?", (project_id, run_id)
        ).fetchone():
            raise Problem(404, "not_found", "Run not found")
        head_row = conn.execute(
            "SELECT sequence FROM ui_stream_heads WHERE run_id=?", (run_id,)
        ).fetchone()
        head = head_row[0] if head_row else 0
        version = conn.execute(
            "SELECT (SELECT COUNT(*) FROM run_events WHERE run_id=?) + "
            "(SELECT COUNT(*) FROM trace_spans WHERE run_id=?)",
            (run_id, run_id),
        ).fetchone()[0]
        rows = (
            []
            if after is None
            else conn.execute(
                "SELECT n.sequence,o.notification_id,o.run_id,o.topic,o.entity_id,o.created_at_ms "
                "FROM ui_stream_notifications n JOIN ui_outbox o "
                "ON o.notification_id=n.notification_id "
                "WHERE n.run_id=? AND n.sequence>? ORDER BY n.sequence LIMIT 100",
                (run_id, after),
            ).fetchall()
        )
        gap = (
            after is None
            or after > head
            or (after < head and (not rows or rows[0]["sequence"] != after + 1))
        )
        if not gap and rows:
            gap = any(
                b["sequence"] != a["sequence"] + 1 for a, b in zip(rows, rows[1:], strict=False)
            )
        if gap:
            return {
                "type": "snapshot_required",
                "run_id": run_id,
                "cursor": head,
                "projection_version": version,
            }
        return {
            "type": "notifications",
            "run_id": run_id,
            "cursor": rows[-1]["sequence"] if rows else after,
            "projection_version": version,
            "notifications": [
                {**dict(row), "projection_version": version, "payload": {"snapshot_required": True}}
                for row in rows
            ],
        }


async def stream(websocket: WebSocket, run_id: str) -> None:
    state = websocket.app.state
    protocols = websocket.scope.get("subprotocols", [])
    if (
        len(protocols) != 2
        or protocols[0] != "swarmcircuit.v1"
        or not state.stream_tickets.consume(protocols[1], run_id)
    ):
        await websocket.close(code=1008)
        return
    try:
        raw = websocket.query_params.get("after")
        after = int(raw) if raw is not None else None
        if after is not None and not 0 <= after <= 2**63 - 1:
            raise ValueError("Invalid cursor")
        first = await run_in_threadpool(
            snapshot, state.db, state.settings.project_id, run_id, after
        )
    except (ValueError, Problem):
        await websocket.close(code=1008)
        return
    await websocket.accept(subprotocol="swarmcircuit.v1")
    try:
        await websocket.send_json(first)
        after = first["cursor"]
        last_heartbeat = now_ms()
        while True:
            try:
                message = await asyncio.wait_for(websocket.receive(), timeout=0.2)
                if message["type"] == "websocket.disconnect":
                    return
                await websocket.close(code=1008, reason="Read-only stream")
                return
            except TimeoutError:
                pass
            batch = await run_in_threadpool(
                snapshot, state.db, state.settings.project_id, run_id, after
            )
            if batch["type"] == "snapshot_required" or batch.get("notifications"):
                await websocket.send_json(batch)
                after = batch["cursor"]
            elif now_ms() - last_heartbeat >= 10_000:
                await websocket.send_json({"type": "heartbeat", "run_id": run_id, "cursor": after})
                last_heartbeat = now_ms()
    except (WebSocketDisconnect, RuntimeError):
        return
    except sqlite3.Error:
        await websocket.close(code=1011, reason="Snapshot unavailable")
