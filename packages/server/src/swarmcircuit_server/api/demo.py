"""Operator-started, strictly isolated local-fixture walkthrough APIs."""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from swarmcircuit_server.errors import Problem


class StartDemo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["fixture", "live"] = "fixture"


class DemoDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approved", "denied"]
    reason: str = Field(min_length=1, max_length=1000)


def install(app: FastAPI, read_auth: Any) -> None:
    def operator(role: str = Depends(read_auth)) -> None:
        if role != "operator":
            raise Problem(
                403, "operator_required", "A local operator is required for guided workflow actions"
            )

    @app.get(
        "/api/v1/projects/{project_id}/demo-capabilities",
        dependencies=[Depends(read_auth)],
        operation_id="getGuidedWorkflowCapabilities",
    )
    def capabilities(request: Request, project_id: UUID) -> dict[str, Any]:
        return request.app.state.demo.capabilities(str(project_id))

    @app.get(
        "/api/v1/projects/{project_id}/demos",
        dependencies=[Depends(read_auth)],
        operation_id="listGuidedWorkflows",
    )
    def recent(
        request: Request,
        project_id: UUID,
        key: str | None = Query(None, min_length=8, max_length=180),
    ) -> dict[str, Any]:
        return request.app.state.demo.list(str(project_id), key)

    @app.post(
        "/api/v1/projects/{project_id}/demos",
        status_code=201,
        dependencies=[Depends(operator)],
        operation_id="startGuidedWorkflow",
    )
    def start(
        request: Request,
        project_id: UUID,
        body: StartDemo,
        idempotency_key: Annotated[str, Header(min_length=8, max_length=180)],
    ) -> dict[str, Any]:
        return request.app.state.demo.create(str(project_id), idempotency_key, body.mode)

    @app.get(
        "/api/v1/demos/{demo_id}",
        dependencies=[Depends(read_auth)],
        operation_id="getGuidedWorkflow",
    )
    def detail(request: Request, demo_id: UUID) -> dict[str, Any]:
        return request.app.state.demo.status(str(demo_id))

    @app.post(
        "/api/v1/demos/{demo_id}/decision",
        dependencies=[Depends(operator)],
        operation_id="resolveGuidedFixturePermission",
    )
    def decision(
        request: Request,
        demo_id: UUID,
        body: DemoDecision,
        idempotency_key: Annotated[str, Header(min_length=8, max_length=180)],
    ) -> dict[str, Any]:
        reason = body.reason.strip()
        if not reason:
            raise Problem(422, "invalid_reason", "Explain the demo-only permission decision")
        return request.app.state.demo.decision(str(demo_id), body.decision, reason, idempotency_key)

    @app.get(
        "/api/v1/demos/{demo_id}/artifacts/{slug}",
        dependencies=[Depends(read_auth)],
        operation_id="getGuidedWorkflowOutput",
    )
    def output(request: Request, demo_id: UUID, slug: str) -> Response:
        if slug not in {
            "public-findings",
            "dataset-analysis",
            "final-brief",
            "agent-draft",
            "agent-review",
            "agent-repair",
            "handoff-evidence",
        }:
            raise Problem(404, "not_found", "Output not found")
        item = request.app.state.demo.get_artifact(str(demo_id), slug)
        return Response(
            item["content"],
            media_type="text/markdown",
            headers={
                "Content-Disposition": f'attachment; filename="{slug}.md"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "ETag": '"' + item["sha256"] + '"',
            },
        )
