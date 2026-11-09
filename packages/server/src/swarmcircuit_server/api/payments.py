"""Read-only payment/approval visibility plus isolated simulation callbacks."""

import secrets
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from swarmcircuit_server.controller.models import ControlProblem
from swarmcircuit_server.errors import Problem
from swarmcircuit_server.payments.models import ApprovalCallback, SettlementCallback
from swarmcircuit_server.payments.service import callback, list_entities

mock_bearer = HTTPBearer(auto_error=False, scheme_name="MockBrokerBearer")


def install(app: FastAPI, read_auth: Any, run_access: Any) -> None:
    router = APIRouter(
        responses={code: {"model": ControlProblem} for code in (401, 404, 409, 413, 422, 503)}
    )

    def broker(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(mock_bearer)],
    ) -> None:
        config = request.app.state.settings
        if not config.mock_broker_enabled:
            raise Problem(404, "not_found", "Mock broker is disabled")
        token = credentials.credentials if credentials else ""
        if not secrets.compare_digest(token.encode(), config.mock_broker_token.encode()):
            raise Problem(401, "unauthorized", "A separate mock broker credential is required")

    @router.get(
        "/api/v1/runs/{run_id}/approvals",
        dependencies=[Depends(read_auth)],
        operation_id="listApprovals",
    )
    def approvals(
        request: Request,
        run_id: UUID,
        limit: int = Query(50, ge=1, le=200),
        cursor: str | None = None,
    ) -> dict[str, Any]:
        rid = run_access(request, run_id)
        with request.app.state.db.read() as conn:
            return list_entities(conn, rid, "approvals", limit, cursor)

    @router.get(
        "/api/v1/runs/{run_id}/payments",
        dependencies=[Depends(read_auth)],
        operation_id="listPayments",
    )
    def payments(
        request: Request,
        run_id: UUID,
        limit: int = Query(50, ge=1, le=200),
        cursor: str | None = None,
    ) -> dict[str, Any]:
        rid = run_access(request, run_id)
        with request.app.state.db.read() as conn:
            return list_entities(conn, rid, "payments", limit, cursor)

    @router.post(
        "/api/v1/mock/runs/{run_id}/approvals/{approval_id}/resolution",
        dependencies=[Depends(broker)],
        operation_id="mockResolveApproval",
    )
    def resolve(
        request: Request,
        run_id: UUID,
        approval_id: UUID,
        body: ApprovalCallback,
        idempotency_key: Annotated[str, Header(min_length=8, max_length=180)],
    ) -> dict[str, Any]:
        rid = run_access(request, run_id)
        result = request.app.state.db.write(
            lambda conn: callback(
                conn, request.app.state.settings, rid, str(approval_id), body, idempotency_key
            )
        )
        request.app.state.detector.after_ingest(rid)
        return result

    @router.post(
        "/api/v1/mock/runs/{run_id}/payment-attempts/{attempt_id}/settlement",
        dependencies=[Depends(broker)],
        operation_id="mockConfirmSettlement",
    )
    def settle(
        request: Request,
        run_id: UUID,
        attempt_id: UUID,
        body: SettlementCallback,
        idempotency_key: Annotated[str, Header(min_length=8, max_length=180)],
    ) -> dict[str, Any]:
        rid = run_access(request, run_id)
        result = request.app.state.db.write(
            lambda conn: callback(
                conn, request.app.state.settings, rid, str(attempt_id), body, idempotency_key
            )
        )
        request.app.state.detector.after_ingest(rid)
        return result

    app.include_router(router)
