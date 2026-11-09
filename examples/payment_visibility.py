"""Unchanged GateKeep402 over an in-memory mock payment boundary; no signing or RPC."""

import asyncio
import base64
import json
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Any
from uuid import uuid4

import httpx
from swarmcircuit import SwarmCircuit
from swarmcircuit.adapters.gatekeep402 import GateKeep402Observer


class MockPaymentTransport:
    """Explicit simulator boundary; never opens a wallet or network connection.

    Stable native payment IDs reconcile one mock effect. This is separate from
    the observation adapter and does not claim to extend GateKeep402 security.
    """

    def __init__(
        self, observer: GateKeep402Observer, *, body: dict[str, Any] | None = None
    ) -> None:
        from openlibx402_core import PaymentRequest

        self.observer = observer
        self.body = (
            body if body is not None else {"data": "Mock paid data for structural verification"}
        )
        self.authorizations: dict[str, Any] = {}
        self.request = PaymentRequest(
            max_amount_required="0.01",
            asset_type="SPL",
            asset_address="mock-asset",
            payment_address="mock-recipient",
            network="solana-devnet",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            nonce="mock-nonce",
            payment_id=observer.intent_id,
            resource="https://mock.example/data.json",
        )

    async def _make_request(
        self, method: str, url: str, *, payment: Any = None, **kwargs: Any
    ) -> httpx.Response:
        if payment is None:
            header = base64.b64encode(json.dumps(self.request.to_dict()).encode()).decode()
            return httpx.Response(
                402, headers={"X-Payment-Request": header}, request=httpx.Request(method, url)
            )
        return httpx.Response(200, json=self.body, request=httpx.Request(method, url))

    async def create_payment(self, request: Any) -> Any:
        from openlibx402_core import PaymentAuthorization

        if request.payment_id not in self.authorizations:
            self.observer.submitted()
            self.authorizations[request.payment_id] = PaymentAuthorization(
                payment_id=request.payment_id,
                actual_amount=request.max_amount_required,
                payment_address=request.payment_address,
                asset_address=request.asset_address,
                network=request.network,
                timestamp=datetime.now(UTC),
                signature="mock-no-signature",
                public_key="mock-no-key",
                transaction_hash=None,
            )
        return self.authorizations[request.payment_id]


def scenario(
    config: dict[str, str],
    *,
    client: Any = None,
    clock_ms: Any = None,
) -> dict[str, Any]:
    from gatekeep402 import PaymentDeniedError, TrustGate, TrustLedger, TrustPolicy

    endpoint = config["endpoint"]
    network = client or httpx.Client(timeout=5)
    owned = client is None
    headers = {
        role: {"Authorization": "Bearer " + config[role]} for role in ("sdk", "operator", "broker")
    }

    def api(method: str, path: str, role: str = "operator", **kwargs: Any) -> dict[str, Any]:
        response = network.request(
            method,
            endpoint + path,
            headers={**headers[role], **kwargs.pop("headers", {})},
            **kwargs,
        )
        response.raise_for_status()
        return dict(response.json())

    def wait_applied(cid: str) -> None:
        until = time.monotonic() + 8
        while time.monotonic() < until:
            command = api("GET", f"/api/v1/control-commands/{cid}")
            if command["state"] == "applied":
                return
            if command["state"] not in {"queued", "dispatched"}:
                raise RuntimeError("Mock demonstration command did not apply")
            time.sleep(0.02)
        raise RuntimeError("Mock demonstration ACK deadline passed")

    try:
        with tempfile.TemporaryDirectory(prefix="swarm-mock-ledger-") as folder:
            ledger = TrustLedger(str(Path(folder) / "ledger.db"))
            try:
                with SwarmCircuit(
                    config["project_id"], config["sdk"], endpoint, client=network, clock_ms=clock_ms
                ) as sdk:
                    with sdk.run(
                        "gatekeep402-mock-approval", mode="control", simulation=True
                    ) as run:
                        root = run.task("Mock paid research", agent="buyer")
                        child = run.task("Dependent analysis", agent="analyst")
                        independent = run.task("Public research", agent="independent")
                        denied = run.task("Denied mock payment", agent="blocked-buyer")
                        child.depends_on(root)
                        observer = GateKeep402Observer(
                            root,
                            action_key="read-once",
                            principal="mock-host",
                            purpose="research",
                            asset_code="MOCK",
                        )
                        transport = MockPaymentTransport(observer)
                        root_entered, child_entered, payment_returned, receipt_confirmed = (
                            Event(),
                            Event(),
                            Event(),
                            Event(),
                        )
                        child_executions: list[str] = []
                        with run.runtime("mock-payment-host", poll_interval=0.02) as runtime:

                            async def on_ask(request: Any, context: Any) -> bool:
                                await asyncio.to_thread(
                                    runtime.checkpoint,
                                    root,
                                    action="before_mock_payment",
                                    timeout=20,
                                    on_enter=lambda point: root_entered.set(),
                                )
                                approvals = api(
                                    "GET", f"/api/v1/runs/{run.run_id}/approvals", "sdk"
                                )["items"]
                                return any(
                                    a["approval_id"] == observer.approval_id
                                    and a["state"] == "approved"
                                    and a["action_fingerprint"] == observer.scope_fingerprint
                                    and a["verified_resolution_source"] == "mock-broker-v1"
                                    for a in approvals
                                )

                            native = observer.client(
                                transport,
                                ledger=ledger,
                                on_ask=on_ask,
                                raise_on_delivery_failure=True,
                            )

                            def buy() -> None:
                                with root:
                                    response = asyncio.run(native.get(transport.request.resource))
                                    if response.status_code != 200:
                                        raise RuntimeError("Mock response failed")
                                    payment_returned.set()
                                    if not receipt_confirmed.wait(8):
                                        raise RuntimeError(
                                            "Mock receipt was not independently recorded"
                                        )
                                    root.mark_completed()

                            def analyze() -> None:
                                with child:
                                    runtime.checkpoint(
                                        child,
                                        action="before_mock_analysis",
                                        timeout=20,
                                        on_enter=lambda point: child_entered.set(),
                                    )
                                    child_executions.append("once")

                            def resume(task_id: str) -> str:
                                graph = api("GET", f"/api/v1/runs/{run.run_id}/graph")
                                task = next(n for n in graph["nodes"] if n["id"] == task_id)
                                result = api(
                                    "POST",
                                    f"/api/v1/runs/{run.run_id}/control-commands",
                                    headers={"Idempotency-Key": str(uuid4())},
                                    json={
                                        "command_kind": "resume_task",
                                        "runtime_session_id": runtime.session_id,
                                        "task_id": task_id,
                                        "expected_task_version": task["state_version"],
                                        "reason": "Mock approval and prerequisite satisfied",
                                    },
                                )
                                wait_applied(result["command_id"])
                                return str(result["command_id"])

                            with ThreadPoolExecutor(max_workers=2) as pool:
                                root_future, child_future = pool.submit(buy), pool.submit(analyze)
                                try:
                                    if not root_entered.wait(8) or not child_entered.wait(8):
                                        raise RuntimeError(
                                            "Mock runtime did not reach both boundaries"
                                        )
                                    group = api(
                                        "POST",
                                        f"/api/v1/runs/{run.run_id}/backpressure",
                                        headers={"Idempotency-Key": str(uuid4())},
                                        json={
                                            "approval_id": observer.approval_id,
                                            "reason": "Mock shared ASK",
                                            "apply": True,
                                        },
                                    )
                                    if len(group["command_ids"]) != 2:
                                        raise RuntimeError("Expected two explicit dependent holds")
                                    for cid in group["command_ids"]:
                                        wait_applied(cid)
                                    if transport.authorizations:
                                        raise RuntimeError("Mock payment happened before approval")
                                    with independent:
                                        pass
                                    resolution = api(
                                        "POST",
                                        f"/api/v1/mock/runs/{run.run_id}/approvals/{observer.approval_id}/resolution",
                                        "broker",
                                        headers={"Idempotency-Key": str(uuid4())},
                                        json={
                                            "action_fingerprint": observer.scope_fingerprint,
                                            "decision": "approved",
                                        },
                                    )
                                    root_resume = resume(root.task_id)
                                    if not payment_returned.wait(8):
                                        root_future.result(timeout=1)
                                        raise RuntimeError("Mock payment did not return")
                                    before = api("GET", f"/api/v1/runs/{run.run_id}/payments")[
                                        "items"
                                    ][0]
                                    if before["state"] != "unknown":
                                        raise RuntimeError(
                                            "Delivery was incorrectly treated as settlement"
                                        )
                                    settlement = api(
                                        "POST",
                                        f"/api/v1/mock/runs/{run.run_id}/payment-attempts/{observer.attempt_id}/settlement",
                                        "broker",
                                        headers={"Idempotency-Key": str(uuid4())},
                                        json={
                                            "scope_fingerprint": observer.scope_fingerprint,
                                            "receipt_reference": "mock:" + str(uuid4()),
                                        },
                                    )
                                    receipt_confirmed.set()
                                    root_future.result(timeout=5)
                                    child_resume = resume(child.task_id)
                                    child_future.result(timeout=5)
                                finally:
                                    receipt_confirmed.set()
                                    if not root_future.done() or not child_future.done():
                                        runtime.stopping.set()
                        deny_observer = GateKeep402Observer(
                            denied,
                            action_key="deny-once",
                            principal="mock-host",
                            purpose="negative-control",
                            asset_code="MOCK",
                        )
                        deny_transport = MockPaymentTransport(deny_observer)
                        denied_native = deny_observer.client(
                            deny_transport,
                            ledger=ledger,
                            gate=TrustGate(ledger, TrustPolicy(unknown_domain_default="deny")),
                        )
                        # Use another unknown domain; the successful one now has local history.
                        deny_transport.request.resource = "https://denied.example/data.json"
                        try:
                            asyncio.run(denied_native.get(deny_transport.request.resource))
                        except PaymentDeniedError:
                            pass
                        else:
                            raise RuntimeError("Expected GateKeep402 DENY")
                        if (
                            deny_transport.authorizations
                            or len(transport.authorizations) != 1
                            or child_executions != ["once"]
                        ):
                            raise RuntimeError("Mock effect count violated")
                        return {
                            "run_id": run.run_id,
                            "simulation": True,
                            "gatekeep402_version": "0.2.1",
                            "approval_id": observer.approval_id,
                            "approval_state": resolution["state"],
                            "hold_command_ids": group["command_ids"],
                            "resume_command_ids": [root_resume, child_resume],
                            "mock_payment_effects": len(transport.authorizations),
                            "denied_mock_effects": len(deny_transport.authorizations),
                            "independent_completed": independent.completed,
                            "dependent_executions": len(child_executions),
                            "state_before_mock_receipt": before["state"],
                            "settlement_state": settlement["state"],
                            "settlement_trust": settlement["trust_class"],
                            "telemetry_degraded": sdk.telemetry_degraded
                            or observer.telemetry_degraded
                            or deny_observer.telemetry_degraded,
                        }
            finally:
                ledger.close()
    finally:
        if owned:
            network.close()


def main() -> None:
    config = {
        "endpoint": os.getenv("SWARM_API_URL", "http://127.0.0.1:8000"),
        "project_id": os.environ["SWARM_PROJECT_ID"],
        "sdk": os.environ["SWARM_SDK_PROJECT_TOKEN"],
        "operator": os.environ["SWARM_OPERATOR_TOKEN"],
        "broker": os.environ["SWARM_MOCK_BROKER_TOKEN"],
    }
    print(json.dumps(scenario(config), indent=2))


if __name__ == "__main__":
    main()
