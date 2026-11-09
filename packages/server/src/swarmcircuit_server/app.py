"""Loopback-only FastAPI service. Run one worker for this SQLite MVP."""

import logging
import os
import secrets
import sqlite3
import zlib
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.protobuf.json_format import ParseError
from google.protobuf.message import DecodeError
from google.rpc.status_pb2 import Status
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from swarmcircuit_server import repository
from swarmcircuit_server.api.control import install as install_control
from swarmcircuit_server.api.demo import install as install_demo
from swarmcircuit_server.api.payments import install as install_payments
from swarmcircuit_server.api.research import install as install_research
from swarmcircuit_server.api.studio import install as install_studio
from swarmcircuit_server.api.workspace import install as install_workspace
from swarmcircuit_server.config import Settings
from swarmcircuit_server.controller.service import ControlService, availability
from swarmcircuit_server.db.store import Database, WriterUnavailable, migrate, now_ms
from swarmcircuit_server.demo import DemoManager
from swarmcircuit_server.detectors.service import DetectionService, list_incidents
from swarmcircuit_server.errors import Problem
from swarmcircuit_server.ingest.events import EventBatch, ingest_batch
from swarmcircuit_server.ingest.otlp import decode, encoded, ingest_traces
from swarmcircuit_server.logging_config import configure_logging
from swarmcircuit_server.realtime import StreamTickets

log = logging.getLogger("swarmcircuit")
bearer = HTTPBearer(auto_error=False)


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=150)
    mode: Literal["observe", "control"]
    external_run_key: str | None = Field(default=None, max_length=150)
    simulation: bool = False


def create_app(
    settings: Settings | None = None,
    *,
    detector_clock: Callable[[], int] = now_ms,
    control_clock: Callable[[], int] = now_ms,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        config = settings or Settings.from_env()
        migrate(config.db_path)
        database = Database(config.db_path, config.queue_size, config.write_timeout)
        app.state.settings, app.state.db = config, database
        try:
            app.state.demo_origin = os.getenv("SWARM_DEMO_API_URL", "http://127.0.0.1:8000")
            app.state.demo = DemoManager(database, config, app.state.demo_origin)
            database.write(lambda conn: repository.bootstrap(conn, config))
            app.state.control = ControlService(database, config, control_clock)
            app.state.stream_tickets = StreamTickets(control_clock)
            app.state.control.start()
            detector = DetectionService(
                database,
                config.project_id,
                config.detector_policy,
                config.detector_interval_seconds,
                detector_clock,
            )
            app.state.detector = detector
            detector.start()
            app.state.demo.start()
            log.info(
                "server_ready", extra={"project_id": config.project_id, "schema_version": "007"}
            )
            yield
        finally:
            if hasattr(app.state, "demo"):
                app.state.demo.close()
            if hasattr(app.state, "detector"):
                app.state.detector.stop()
            if hasattr(app.state, "control"):
                app.state.control.stop()
            database.close()

    app = FastAPI(title="SwarmCircuit", version="0.5.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(
            settings.allowed_origins
            if settings
            else os.getenv("SWARM_ALLOWED_ORIGINS", "http://localhost:3000").split(",")
        ),
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )

    def error_response(request: Request, status: int, code: str, message: str) -> Response:
        cid = getattr(request.state, "correlation_id", str(uuid4()))
        headers = {"X-Correlation-ID": cid}
        if status == 503:
            headers["Retry-After"] = "1"
        if request.url.path == "/v1/traces":
            is_json = request.headers.get("content-type", "").split(";")[0] == "application/json"
            return Response(
                encoded(Status(message=message), is_json),
                status_code=status,
                media_type="application/json" if is_json else "application/x-protobuf",
                headers=headers,
            )
        return JSONResponse(
            {"code": code, "message": message, "correlation_id": cid},
            status_code=status,
            headers=headers,
        )

    @app.middleware("http")
    async def bound_body(request: Request, call_next: Any) -> Response:
        request.state.correlation_id = str(uuid4())
        if request.method == "POST":
            data = bytearray()
            async for chunk in request.stream():
                if len(data) + len(chunk) > request.app.state.settings.max_bytes:
                    return error_response(request, 413, "too_large", "Request exceeds size limit")
                data.extend(chunk)
            request._body = bytes(data)
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = request.state.correlation_id
        return response

    @app.exception_handler(Problem)
    async def problem_handler(request: Request, exc: Problem) -> Response:
        return error_response(request, exc.status, exc.code, exc.message)

    @app.exception_handler(WriterUnavailable)
    async def unavailable(request: Request, exc: WriterUnavailable) -> Response:
        log.warning("writer_unavailable", extra={"correlation_id": request.state.correlation_id})
        return error_response(request, 503, "writer_unavailable", str(exc))

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, exc: RequestValidationError) -> Response:
        # Pydantic's default includes raw invalid inputs, potentially including secrets.
        return error_response(
            request, 422, "invalid_request", "Request does not match the contract"
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> Response:
        return error_response(request, exc.status_code, "http_error", "Request unavailable")

    def read_auth(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> str:
        config = request.app.state.settings
        header = f"Bearer {credentials.credentials}" if credentials else ""
        for role, token in (("sdk", config.sdk_token), ("operator", config.operator_token)):
            if secrets.compare_digest(header.encode(), f"Bearer {token}".encode()):
                return role
        raise Problem(401, "unauthorized", "A valid local project credential is required")

    def sdk_auth(request: Request, role: str = Depends(read_auth)) -> None:
        if role != "sdk":
            raise Problem(403, "forbidden", "This endpoint requires the SDK project credential")
        config = request.app.state.settings
        kind = "otlp" if request.url.path == "/v1/traces" else "sdk"
        with request.app.state.db.read() as conn:
            source = conn.execute(
                "SELECT enabled FROM telemetry_sources WHERE project_id=? AND source_id=?",
                (config.project_id, config.source_id(kind)),
            ).fetchone()
        if not source or not source["enabled"]:
            raise Problem(403, "source_disabled", "This telemetry source is disabled")

    def run_access(request: Request, run_id: UUID) -> str:
        with request.app.state.db.read() as conn:
            repository.get_run(conn, request.app.state.settings.project_id, str(run_id))
        return str(run_id)

    @app.get("/api/v1/health", operation_id="health")
    def health(request: Request) -> dict[str, str]:
        try:
            with request.app.state.db.read() as conn:
                version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
            db = request.app.state.db
            ready = (
                not db.closed
                and db.thread.is_alive()
                and version == "007"
                and request.app.state.detector.healthy
                and request.app.state.control.healthy
            )
            return {"status": "ready" if ready else "degraded", "schema_version": version}
        except sqlite3.Error:
            return {"status": "degraded", "schema_version": "unknown"}

    @app.post(
        "/api/v1/projects/{project_id}/runs",
        status_code=201,
        dependencies=[Depends(sdk_auth)],
        operation_id="createRun",
    )
    def create_run(request: Request, project_id: UUID, body: RunCreate) -> dict[str, Any]:
        config = request.app.state.settings
        if str(project_id) != config.project_id:
            raise Problem(404, "not_found", "Project not found")
        return request.app.state.db.write(
            lambda conn: repository.create_run(
                conn,
                config.project_id,
                body.name,
                body.mode,
                body.external_run_key,
                body.simulation,
            )
        )

    @app.get(
        "/api/v1/projects/{project_id}/runs",
        dependencies=[Depends(read_auth)],
        operation_id="listRuns",
    )
    def list_runs(
        request: Request,
        project_id: UUID,
        cursor: str | None = None,
        limit: int = Query(25, ge=1, le=100),
        kind: Literal["all", "workflow", "research"] = "all",
        include_diagnostics: bool = True,
    ) -> dict[str, Any]:
        if str(project_id) != request.app.state.settings.project_id:
            raise Problem(404, "not_found", "Project not found")
        with request.app.state.db.read() as conn:
            return repository.list_runs(
                conn, str(project_id), limit, cursor, kind, include_diagnostics
            )

    @app.get("/api/v1/runs/{run_id}", dependencies=[Depends(read_auth)], operation_id="getRun")
    def get_run(request: Request, run_id: UUID) -> dict[str, Any]:
        with request.app.state.db.read() as conn:
            return repository.get_run(conn, request.app.state.settings.project_id, str(run_id))

    @app.post(
        "/api/v1/runs/{run_id}/events",
        dependencies=[Depends(sdk_auth)],
        operation_id="appendEvents",
    )
    def events(request: Request, body: EventBatch, run_id: UUID) -> dict[str, Any]:
        rid, config = run_access(request, run_id), request.app.state.settings
        if request.headers.get("content-encoding", "identity") != "identity":
            raise Problem(415, "unsupported_encoding", "Lifecycle events require uncompressed JSON")
        result = request.app.state.db.write(
            lambda conn: ingest_batch(
                conn,
                rid,
                config.project_id,
                config.source_id("sdk"),
                body,
            )
        )
        log.info(
            "events_persisted",
            extra={"correlation_id": request.state.correlation_id, "run_id": rid, **result},
        )
        if result["accepted"]:
            request.app.state.detector.after_ingest(rid)
        return result

    @app.get(
        "/api/v1/runs/{run_id}/incidents",
        dependencies=[Depends(read_auth)],
        operation_id="listIncidents",
    )
    def incidents(request: Request, run_id: UUID) -> dict[str, Any]:
        rid = run_access(request, run_id)
        with request.app.state.db.read() as conn:
            result = list_incidents(conn, rid)
            for item in result["items"]:
                actions = [
                    availability(
                        conn,
                        request.app.state.settings,
                        rid,
                        tid,
                        request.app.state.control.clock(),
                    )
                    for tid in item["affected_task_ids"]
                ]
                item["can_control"] = any(a["hold_task"] or a["resume_task"] for a in actions)
                item["can_control_reason"] = (
                    "Eligible cooperative checkpoint; operator request required"
                    if item["can_control"]
                    else "No eligible live cooperative boundary"
                )
            return result

    @app.get(
        "/api/v1/runs/{run_id}/graph", dependencies=[Depends(read_auth)], operation_id="getGraph"
    )
    def graph(
        request: Request, run_id: UUID, view: Literal["task", "agent"] = "task"
    ) -> dict[str, Any]:
        rid = run_access(request, run_id)
        with request.app.state.db.read() as conn:
            result = repository.graph(conn, rid, view)
            for node in result["nodes"]:
                if node["node_kind"] == "task":
                    node["control"] = availability(
                        conn,
                        request.app.state.settings,
                        rid,
                        node["id"],
                        request.app.state.control.clock(),
                    )
                    node["control_available"] = (
                        node["control"]["hold_task"] or node["control"]["resume_task"]
                    )
            result["control_available"] = any(n["control_available"] for n in result["nodes"])
            return result

    @app.get(
        "/api/v1/runs/{run_id}/timeline",
        dependencies=[Depends(read_auth)],
        operation_id="getTimeline",
    )
    def timeline(
        request: Request,
        run_id: UUID,
        cursor: str | None = None,
        limit: int = Query(100, ge=1, le=500),
    ) -> dict[str, Any]:
        rid = run_access(request, run_id)
        with request.app.state.db.read() as conn:
            return repository.timeline(conn, rid, cursor, limit)

    @app.post("/v1/traces", dependencies=[Depends(sdk_auth)])
    async def traces(request: Request) -> Response:
        media = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if media not in {"application/json", "application/x-protobuf"}:
            raise Problem(415, "unsupported_media", "Use OTLP JSON or binary protobuf")
        is_json = media == "application/json"
        body = await request.body()
        encoding = request.headers.get("content-encoding", "identity").lower()
        if encoding == "gzip":
            try:
                decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
                body = decoder.decompress(body, request.app.state.settings.max_bytes + 1)
                if len(body) > request.app.state.settings.max_bytes or decoder.unconsumed_tail:
                    raise Problem(413, "too_large", "Decompressed request exceeds size limit")
                if not decoder.eof or decoder.unused_data:
                    raise ValueError("Incomplete or concatenated gzip stream")
            except (zlib.error, ValueError) as exc:
                raise Problem(400, "invalid_gzip", "Malformed gzip stream") from exc
        elif encoding != "identity":
            raise Problem(415, "unsupported_encoding", "Supported encodings: identity, gzip")
        try:
            export = decode(body, is_json)
        except (ValueError, DecodeError, ParseError, TypeError, RecursionError) as exc:
            raise Problem(400, "invalid_otlp", "Malformed OTLP trace export") from exc
        config = request.app.state.settings
        rejected = await run_in_threadpool(
            request.app.state.db.write,
            lambda conn: ingest_traces(
                conn,
                config.project_id,
                config.source_id("otlp"),
                export,
            ),
        )
        result = ExportTraceServiceResponse()
        if rejected:
            result.partial_success.rejected_spans = rejected
            result.partial_success.error_message = (
                "Spans rejected: invalid correlation, data or replay"
            )
        log.info(
            "traces_persisted",
            extra={"correlation_id": request.state.correlation_id, "rejected": rejected},
        )
        return Response(encoded(result, is_json), media_type=media)

    install_control(app, read_auth, sdk_auth, run_access)
    install_payments(app, read_auth, run_access)
    install_studio(app, read_auth, run_access)
    install_research(app, read_auth)
    install_workspace(app, read_auth, run_access)
    install_demo(app, read_auth)
    return app


app = create_app()
