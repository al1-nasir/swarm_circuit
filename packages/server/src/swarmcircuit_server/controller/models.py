from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ControlProblem(Model):
    code: str
    message: str
    correlation_id: UUID


class Registration(Model):
    runtime_key: str = Field(min_length=1, max_length=150)
    client_nonce: str = Field(min_length=16, max_length=180)
    capabilities: list[Literal["hold_task", "resume_task"]] = Field(min_length=1, max_length=2)


class CommandRequest(Model):
    command_kind: Literal["hold_task", "resume_task"]
    runtime_session_id: UUID
    task_id: UUID
    incident_id: UUID | None = None
    approval_id: UUID | None = None
    expected_task_version: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=1000)


class Ack(Model):
    runtime_session_id: UUID
    fencing_epoch: int = Field(ge=1)
    ack_key: str = Field(min_length=8, max_length=180)
    result: Literal["applied", "rejected", "failed"]
    result_detail: str | None = Field(default=None, max_length=250)


class CheckpointEnter(Model):
    task_id: UUID
    checkpoint_key: str = Field(min_length=16, max_length=180)
    label: str = Field(min_length=1, max_length=150)
    reversible: Literal[True]


class Backpressure(Model):
    expected_preview_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    approval_id: UUID
    apply: bool = False
    reason: str = Field(min_length=1, max_length=1000)


class Presentation(Model):
    event_id: UUID


class PresentationResult(Model):
    state: Literal["presented", "unknown"]


class RuntimeRegistered(Model):
    runtime_session_id: UUID
    fencing_epoch: int = Field(ge=1)
    session_token: str = Field(description="Secret; SDK registration response only")
    expires_at_ms: int


class CommandRecord(BaseModel):
    # Preserve the supplied command columns alongside the protocol's required fields.
    model_config = ConfigDict(extra="allow")
    command_id: UUID
    command_kind: Literal["hold_task", "resume_task", "cancel_task", "coalesce_approval"]
    state: Literal["queued", "dispatched", "applied", "rejected", "timed_out", "unknown"]
    runtime_session_id: UUID
    session_fencing_epoch: int = Field(ge=1)
    task_id: UUID | None
    checkpoint_id: UUID | None
    created_at_ms: int
    acknowledgements: list[dict[str, object]]


class CommandBatch(Model):
    commands: list[CommandRecord]
