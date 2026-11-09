"""Composition hooks for unchanged GateKeep402 0.2.1; no payment authority."""

import hashlib
import json
import logging
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid5

from swarmcircuit.run import TaskContext

log = logging.getLogger("swarmcircuit.sdk.payments")
VERSION = "0.2.1"


def fingerprint(value: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


class GateKeep402Observer:
    """One logical payment intent. Underlying signing and ASK callbacks stay with GateKeep402.

    Observation failure degrades telemetry and never converts a gate decision. The
    connector must call submitted() at its actual submission boundary. Neither a
    returned response nor DeliveryCheck success is treated as settlement proof.
    """

    def __init__(
        self,
        task: TaskContext,
        *,
        action_key: str,
        principal: str,
        purpose: str,
        asset_code: str,
    ) -> None:
        self.task = task
        self.intent_key = fingerprint(action_key)
        self.intent_id = str(
            uuid5(UUID(task.run.run_id), f"payment:{task.task_id}:{self.intent_key}")
        )
        self.attempt_id = str(uuid5(UUID(self.intent_id), "attempt:1"))
        self.principal, self.purpose, self.asset_code = principal, purpose, asset_code
        self.approval_id: str | None = None
        self.scope_fingerprint: str | None = None
        self.telemetry_degraded = False

    def _emit(self, kind: str, payload: dict[str, Any]) -> None:
        self.task.emit(
            kind,
            approval_id=self.approval_id,
            payload={
                "payment_intent_id": self.intent_id,
                "integration_version": VERSION,
                **payload,
            },
        )
        self.telemetry_degraded |= self.task.run.sdk.telemetry_degraded

    def _observe_gate(self, request: Any, decision: Any, gate: Any) -> None:
        try:
            policy = fingerprint(
                {
                    name: getattr(gate.policy, name)
                    for name in (
                        "min_score_to_autopay",
                        "block_below",
                        "unknown_domain_default",
                        "min_local_history_for_autopay",
                    )
                }
            )
            # Scope binds the exact native amount, recipient, asset, network and request ID.
            # Raw scope fields never leave this process; wait_for_approval emits its digest.
            scope = {
                "principal": self.principal,
                "purpose": self.purpose,
                "resource": fingerprint(request.resource),
                "counterparty": fingerprint(request.payment_address),
                "permission_scope": "single-payment-intent",
                "policy_revision": policy,
                "amount": request.max_amount_required,
                "asset": fingerprint(request.asset_address),
                "network": request.network,
                "native_request": fingerprint(request.payment_id),
                "intent_id": self.intent_id,
            }
            self.scope_fingerprint = fingerprint(scope)
            if decision.value == "ask":
                self.approval_id = self.task.wait_for_approval(scope)
            self._emit(
                "payment.gate_decided",
                {
                    "intent_key": self.intent_key,
                    "domain": (urlsplit(request.original_request_url).hostname or "").lower(),
                    "asset_code": self.asset_code,
                    "amount_decimal": request.max_amount_required,
                    "chain_network": request.network,
                    "decision": decision.value,
                    "policy_revision": policy,
                    "scope_fingerprint": self.scope_fingerprint,
                    "trust_score": float(gate.ledger.score(request.domain)),
                },
            )
        except Exception:
            self.telemetry_degraded = True
            log.warning("payment_observation_degraded")

    def submitted(self) -> None:
        """Connector observation before an effect; records uncertainty, never settlement."""
        try:
            self._emit("payment.attempt_submitted", {"payment_attempt_id": self.attempt_id})
        except Exception:
            self.telemetry_degraded = True
            log.warning("payment_observation_degraded")

    def _observe_delivery(self, result: Any) -> None:
        try:
            self._emit(
                "payment.delivery_checked",
                {
                    "payment_attempt_id": self.attempt_id,
                    "structural_ok": bool(result.ok),
                    # Native reasons can include response content, URLs or error messages.
                    "reason_code": "structural_ok" if result.ok else "structural_failure",
                },
            )
        except Exception:
            self.telemetry_degraded = True
            log.warning("payment_observation_degraded")

    def client(
        self,
        base_client: Any,
        *,
        ledger: Any,
        gate: Any = None,
        delivery_check: Any = None,
        on_ask: Any = None,
        raise_on_delivery_failure: bool = False,
    ) -> Any:
        """Construct the real native client with composed observation delegates.

        No private native methods are patched and the underlying client is passed
        unchanged, preserving GateKeep402's X402AutoClient auto-retry protection.
        """
        try:
            from gatekeep402 import DeliveryCheck, GateKeep402Client, TrustGate
        except ImportError as exc:
            raise ImportError(
                "Install swarmcircuit-sdk[payments] for GateKeep402 observation"
            ) from exc
        return GateKeep402Client(
            client=base_client,
            ledger=ledger,
            gate=_ObservedGate(gate if gate is not None else TrustGate(ledger), self),
            delivery_check=_ObservedDelivery(
                delivery_check if delivery_check is not None else DeliveryCheck(), self
            ),
            on_ask=on_ask,
            raise_on_delivery_failure=raise_on_delivery_failure,
        )


class _ObservedGate:
    def __init__(self, delegate: Any, observer: GateKeep402Observer) -> None:
        self.delegate, self.observer = delegate, observer
        self.policy, self.ledger = delegate.policy, delegate.ledger

    def evaluate(self, payment_request: Any, **kwargs: Any) -> Any:
        decision = self.delegate.evaluate(payment_request, **kwargs)
        self.observer._observe_gate(payment_request, decision, self.delegate)
        return decision


class _ObservedDelivery:
    def __init__(self, delegate: Any, observer: GateKeep402Observer) -> None:
        self.delegate, self.observer = delegate, observer

    def verify(self, payment_request: Any, response: Any) -> Any:
        result = self.delegate.verify(payment_request, response)
        self.observer._observe_delivery(result)
        return result
