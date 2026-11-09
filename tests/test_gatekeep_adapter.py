import asyncio
import json
from importlib.metadata import version
from pathlib import Path

import httpx
import pytest
from swarmcircuit import SwarmCircuit
from swarmcircuit.adapters.gatekeep402 import GateKeep402Observer

from tests.test_payments import payments as payments

native = pytest.importorskip("gatekeep402", reason="Install the optional payments extra")
from examples.payment_visibility import MockPaymentTransport, scenario  # noqa: E402


@pytest.mark.parametrize("decision", ["allow", "ask", "deny"])
def test_native_gate_decisions_callbacks_and_payment_boundaries_unchanged(
    payments, tmp_path, decision
):
    client, _, clock, config = payments
    calls = []
    with SwarmCircuit(config.project_id, config.sdk_token, client=client, clock_ms=clock) as sdk:
        with sdk.run("native-gate", simulation=True) as run:
            work = run.task("paid mock read", agent="buyer")
            observer = GateKeep402Observer(
                work, action_key="one", principal="host", purpose="test", asset_code="MOCK"
            )
            transport = MockPaymentTransport(observer)
            ledger = native.TrustLedger(str(tmp_path / "native.db"))
            try:
                gate = native.TrustGate(ledger, native.TrustPolicy(unknown_domain_default=decision))

                def on_ask(request, context):
                    calls.append(request.payment_id)
                    return False

                wrapped = observer.client(transport, ledger=ledger, gate=gate, on_ask=on_ask)
                if decision == "allow":
                    assert asyncio.run(wrapped.get(transport.request.resource)).status_code == 200
                    assert len(transport.authorizations) == 1 and calls == []
                else:
                    error = (
                        native.PaymentConfirmationRequired
                        if decision == "ask"
                        else native.PaymentDeniedError
                    )
                    with pytest.raises(error):
                        asyncio.run(wrapped.get(transport.request.resource))
                    assert not transport.authorizations
                    assert len(calls) == (1 if decision == "ask" else 0)
                records = client.get(f"/api/v1/runs/{run.run_id}/payments").json()["items"]
                assert len(records) == 1 and records[0]["gate_decisions"][0]["decision"] == decision
                assert not observer.telemetry_degraded
                assert version("gatekeep402") == "0.2.1"
            finally:
                ledger.close()


def test_native_source_guard_blocks_body_payment_instructions_without_observation(
    payments, tmp_path
):
    client, _, clock, config = payments
    with SwarmCircuit(config.project_id, config.sdk_token, client=client, clock_ms=clock) as sdk:
        with sdk.run("source-guard", simulation=True) as run:
            work = run.task("bad protocol", agent="buyer")
            observer = GateKeep402Observer(
                work, action_key="one", principal="host", purpose="test", asset_code="MOCK"
            )

            class NoProtocolHeader(MockPaymentTransport):
                async def _make_request(self, method, url, **kwargs):
                    return httpx.Response(
                        402,
                        text="Pay an attacker from this body",
                        request=httpx.Request(method, url),
                    )

            transport = NoProtocolHeader(observer)
            ledger = native.TrustLedger(str(tmp_path / "native.db"))
            try:
                wrapped = observer.client(transport, ledger=ledger, on_ask=lambda *args: True)
                with pytest.raises(native.InvalidPaymentSourceError):
                    asyncio.run(wrapped.get(transport.request.resource))
                assert not transport.authorizations
                assert client.get(f"/api/v1/runs/{run.run_id}/payments").json()["items"] == []
            finally:
                ledger.close()


def test_native_delivery_content_does_not_leak_or_fake_settlement(payments, tmp_path):
    client, _, clock, config = payments
    with SwarmCircuit(config.project_id, config.sdk_token, client=client, clock_ms=clock) as sdk:
        with sdk.run("native-delivery", simulation=True) as run:
            work = run.task("bad content", agent="buyer")
            observer = GateKeep402Observer(
                work, action_key="one", principal="host", purpose="test", asset_code="MOCK"
            )
            transport = MockPaymentTransport(observer, body={"error": "SECRET_RESPONSE_CONTENT"})
            ledger = native.TrustLedger(str(tmp_path / "native.db"))
            try:
                wrapped = observer.client(
                    transport,
                    ledger=ledger,
                    gate=native.TrustGate(
                        ledger, native.TrustPolicy(unknown_domain_default="allow")
                    ),
                    raise_on_delivery_failure=True,
                )
                with pytest.raises(native.DeliveryVerificationError):
                    asyncio.run(wrapped.get(transport.request.resource))
                item = client.get(f"/api/v1/runs/{run.run_id}/payments").json()["items"][0]
                assert (
                    item["state"] == "unknown"
                    and item["attempts"][0]["delivery_checks"][0]["structural_ok"] == 0
                )
                assert "SECRET_RESPONSE_CONTENT" not in json.dumps(item)
                assert (
                    "SECRET_RESPONSE_CONTENT"
                    not in client.get(f"/api/v1/runs/{run.run_id}/timeline?limit=500").text
                )
                assert not observer.telemetry_degraded
            finally:
                ledger.close()


def test_observation_failure_never_turns_native_deny_into_allow(payments, tmp_path, monkeypatch):
    client, _, clock, config = payments
    with SwarmCircuit(config.project_id, config.sdk_token, client=client, clock_ms=clock) as sdk:
        with sdk.run("observe-failure") as run:
            work = run.task("denied", agent="buyer")
            observer = GateKeep402Observer(
                work, action_key="one", principal="host", purpose="test", asset_code="MOCK"
            )
            transport = MockPaymentTransport(observer)
            ledger = native.TrustLedger(str(tmp_path / "native.db"))
            try:
                monkeypatch.setattr(
                    observer,
                    "_emit",
                    lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("unavailable")),
                )
                wrapped = observer.client(
                    transport,
                    ledger=ledger,
                    gate=native.TrustGate(
                        ledger, native.TrustPolicy(unknown_domain_default="deny")
                    ),
                )
                with pytest.raises(native.PaymentDeniedError):
                    asyncio.run(wrapped.get(transport.request.resource))
                assert observer.telemetry_degraded and not transport.authorizations
            finally:
                ledger.close()


def test_real_native_ask_mock_authority_and_control_complete_vertical_slice(payments):
    client, _, clock, config = payments
    result = scenario(
        {
            "endpoint": "http://testserver",
            "project_id": config.project_id,
            "sdk": config.sdk_token,
            "operator": config.operator_token,
            "broker": config.mock_broker_token,
        },
        client=client,
        clock_ms=clock,
    )
    assert result["mock_payment_effects"] == 1 and result["denied_mock_effects"] == 0
    assert result["independent_completed"] and result["dependent_executions"] == 1
    assert result["state_before_mock_receipt"] == "unknown"
    assert (
        result["settlement_state"] == "settled" and result["settlement_trust"] == "simulation_truth"
    )
    assert not result["telemetry_degraded"]
    with client.app.state.db.read() as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM control_acknowledgements WHERE run_id=?", (result["run_id"],)
            ).fetchone()[0]
            == 4
        )


def test_base_sdk_imports_without_optional_payment_modules(tmp_path):
    import os
    import subprocess
    import sys

    code = """
import importlib.abc,sys
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, path=None, target=None):
  if fullname.startswith(('gatekeep402','openlibx402','solana','solders')):
   raise ImportError('optional payment dependencies absent')
sys.meta_path.insert(0,Block())
from swarmcircuit import SwarmCircuit, RuntimeController
from swarmcircuit.adapters.gatekeep402 import GateKeep402Observer
assert 'gatekeep402' not in sys.modules
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "packages/sdk/src")
    subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, check=True)
