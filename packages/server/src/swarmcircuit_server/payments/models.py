"""Metadata allowlists; raw protocol headers, content and wallet data are never accepted."""

from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from swarmcircuit_server.controller.models import Model


class Observation(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    payment_intent_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    integration_version: Literal["0.2.1"]


class GateObservation(Observation):
    intent_key: str = Field(min_length=1, max_length=180)
    domain: str = Field(pattern=r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")
    asset_code: str = Field(pattern=r"^[A-Za-z0-9_-]{1,30}$")
    amount_decimal: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,29})(?:\.[0-9]{1,18})?$")
    chain_network: str = Field(pattern=r"^[A-Za-z0-9_-]{1,60}$")
    decision: Literal["allow", "ask", "deny"]
    policy_revision: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    scope_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    trust_score: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)

    @field_validator("amount_decimal")
    @classmethod
    def positive_amount(cls, value: str) -> str:
        if Decimal(value) <= 0:
            raise ValueError("Payment amount must be positive")
        return value


class AttemptObservation(Observation):
    payment_attempt_id: str = Field(pattern=r"^[0-9a-f-]{36}$")


class DeliveryObservation(AttemptObservation):
    structural_ok: bool
    reason_code: Literal["structural_ok", "structural_failure"]

    @model_validator(mode="after")
    def matching_reason(self) -> Self:
        if self.reason_code != ("structural_ok" if self.structural_ok else "structural_failure"):
            raise ValueError("Structural result and reason code differ")
        return self


class ApprovalCallback(Model):
    action_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    decision: Literal["approved", "denied"]


class SettlementCallback(Model):
    scope_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    receipt_reference: str = Field(pattern=r"^mock:[A-Za-z0-9_-]{8,120}$")
