"""HTTP authority boundaries for the cooperative control protocol."""

import asyncio
import json
import time
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool

from swarmcircuit_server.controller.models import (
    Ack,
    Backpressure,
    CheckpointEnter,
    CommandBatch,
    CommandRecord,
    CommandRequest,
    ControlProblem,
    Presentation,
    PresentationResult,
    Registration,
    RuntimeRegistered,
)
from swarmcircuit_server.controller.service import command, row
from swarmcircuit_server.errors import Problem

runtime_bearer = HTTPBearer(auto_error=False, scheme_name="RuntimeSessionBearer")


def install(app: FastAPI, read_auth: Any, sdk_auth: Any, run_access: Any) -> None:
    router = APIRouter(
        responses={code: {"model": ControlProblem} for code in (401, 403, 404, 409, 413, 422, 503)}
    )

    def operator(role: str = Depends(read_auth)) -> None:
        if role != "operator":
            raise Problem(403, "operator_required", "This action requires the operator credential")

    def runtime(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(runtime_bearer)],
    ) -> str:
        if not credentials:
            raise Problem(401, "unauthorized", "Runtime session credential required")
        return request.app.state.control.authenticate(credentials.credentials)

    def target(session_id: UUID, sid: str = Depends(runtime)) -> str:
        if str(session_id) != sid:
            raise Problem(403, "wrong_session", "Credential is scoped to another runtime session")
        return sid

    @router.post(
        "/api/v1/runs/{run_id}/runtime-sessions",
        status_code=201,
        dependencies=[Depends(sdk_auth)],
        operation_id="registerRuntime",
        response_model=RuntimeRegistered,
    )
    def register(request: Request, run_id: UUID, body: Registration) -> dict[str, Any]:
        return request.app.state.control.register(run_access(request, run_id), body)

    @router.get(
        "/api/v1/runs/{run_id}/runtime-sessions",
        dependencies=[Depends(read_auth)],
        operation_id="listRuntimeSessions",
    )
    def sessions(request: Request, run_id: UUID) -> dict[str, Any]:
        rid = run_access(request, run_id)
        request.app.state.control.write(lambda conn, at: None)
        with request.app.state.db.read() as conn:
            items = []
            for record in conn.execute(
                "SELECT s.*,k.expires_at_ms FROM runtime_sessions s "
                "JOIN runtime_credentials k ON k.runtime_session_id=s.runtime_session_id "
                "WHERE s.run_id=? ORDER BY s.connected_at_ms,s.runtime_session_id",
                (rid,),
            ):
                item = dict(record)
                item["capabilities"] = json.loads(item.pop("capabilities_json"))
                item["checkpoints"] = [
                    dict(p)
                    for p in conn.execute(
                        "SELECT checkpoint_id,task_id,label,state,generation,updated_at_ms "
                        "FROM runtime_checkpoints "
                        "WHERE runtime_session_id=? ORDER BY created_at_ms",
                        (item["runtime_session_id"],),
                    )
                ]
                items.append(item)
            return {"items": items}

    @router.post("/api/v1/runtime-sessions/{session_id}/heartbeat", operation_id="runtimeHeartbeat")
    def heartbeat(request: Request, sid: str = Depends(target)) -> dict[str, Any]:
        return request.app.state.control.heartbeat(sid)

    @router.get(
        "/api/v1/runtime-sessions/{session_id}/commands",
        operation_id="pollCommands",
        response_model=CommandBatch,
    )
    async def poll(
        request: Request, sid: str = Depends(target), wait_ms: int = Query(10000, ge=0, le=20000)
    ) -> dict[str, Any]:
        deadline = time.monotonic() + wait_ms / 1000
        while True:
            result = await run_in_threadpool(request.app.state.control.poll, sid)
            if result["commands"] or time.monotonic() >= deadline:
                return result
            await asyncio.sleep(min(0.1, max(0, deadline - time.monotonic())))

    @router.post(
        "/api/v1/runtime-sessions/{session_id}/checkpoints",
        status_code=201,
        operation_id="enterCheckpoint",
    )
    def enter(
        request: Request, body: CheckpointEnter, sid: str = Depends(target)
    ) -> dict[str, Any]:
        return request.app.state.control.enter(sid, body)

    @router.get(
        "/api/v1/runtime-sessions/{session_id}/checkpoints/{checkpoint_id}",
        operation_id="getCheckpoint",
    )
    def checkpoint(
        request: Request, checkpoint_id: UUID, sid: str = Depends(target)
    ) -> dict[str, Any]:
        with request.app.state.db.read() as conn:
            return row(
                conn,
                "SELECT * FROM runtime_checkpoints WHERE checkpoint_id=? AND runtime_session_id=?",
                (str(checkpoint_id), sid),
            )

    @router.post(
        "/api/v1/runtime-sessions/{session_id}/checkpoints/{checkpoint_id}/leave",
        operation_id="leaveCheckpoint",
    )
    def leave(request: Request, checkpoint_id: UUID, sid: str = Depends(target)) -> dict[str, Any]:
        return request.app.state.control.leave(sid, str(checkpoint_id))

    @router.post(
        "/api/v1/runs/{run_id}/control-commands",
        status_code=202,
        dependencies=[Depends(operator)],
        operation_id="enqueueControlCommand",
        response_model=CommandRecord,
    )
    def enqueue(
        request: Request,
        run_id: UUID,
        body: CommandRequest,
        idempotency_key: Annotated[str, Header(min_length=8, max_length=180)],
    ) -> dict[str, Any]:
        return request.app.state.control.enqueue(run_access(request, run_id), body, idempotency_key)

    @router.get(
        "/api/v1/control-commands/{command_id}",
        dependencies=[Depends(read_auth)],
        operation_id="getControlCommand",
        response_model=CommandRecord,
    )
    def get_command(request: Request, command_id: UUID) -> dict[str, Any]:
        request.app.state.control.write(lambda conn, at: None)
        with request.app.state.db.read() as conn:
            return command(conn, request.app.state.settings.project_id, str(command_id))

    @router.post(
        "/api/v1/control-commands/{command_id}/ack",
        operation_id="acknowledgeCommand",
        response_model=CommandRecord,
    )
    def ack(
        request: Request, command_id: UUID, body: Ack, sid: str = Depends(runtime)
    ) -> dict[str, Any]:
        return request.app.state.control.ack(sid, str(command_id), body)

    @router.post(
        "/api/v1/runs/{run_id}/backpressure",
        dependencies=[Depends(operator)],
        operation_id="requestBackpressure",
    )
    def backpressure(
        request: Request,
        run_id: UUID,
        body: Backpressure,
        idempotency_key: Annotated[str, Header(min_length=8, max_length=180)],
    ) -> dict[str, Any]:
        return request.app.state.control.backpressure(
            run_access(request, run_id), body, idempotency_key
        )

    @router.get(
        "/api/v1/runs/{run_id}/backpressure",
        dependencies=[Depends(read_auth)],
        operation_id="getBackpressureRequest",
    )
    def policy_request(
        request: Request, run_id: UUID, key: str = Query(min_length=8, max_length=180)
    ) -> dict[str, Any]:
        rid = run_access(request, run_id)
        request.app.state.control.write(lambda conn, at: None)
        with request.app.state.db.read() as conn:
            saved = row(
                conn,
                (
                    "SELECT result_json FROM control_policy_requests WHERE run_id=? AND "
                    "idempotency_key=?"
                ),
                (rid, key),
            )
            result = json.loads(saved["result_json"])
            result["commands"] = [
                command(conn, request.app.state.settings.project_id, cid)
                for cid in result["command_ids"]
            ]
            return result

    @router.post(
        "/api/v1/runtime-sessions/{session_id}/approval-presentations",
        operation_id="claimApprovalPresentation",
    )
    def present(request: Request, body: Presentation, sid: str = Depends(target)) -> dict[str, Any]:
        return request.app.state.control.present(sid, str(body.event_id))

    @router.post(
        "/api/v1/runtime-sessions/{session_id}/approval-presentations/{presentation_id}/result",
        operation_id="reportApprovalPresentation",
    )
    def presentation_result(
        request: Request,
        presentation_id: UUID,
        body: PresentationResult,
        sid: str = Depends(target),
    ) -> dict[str, Any]:
        return request.app.state.control.finish_presentation(sid, str(presentation_id), body.state)

    app.include_router(router)
