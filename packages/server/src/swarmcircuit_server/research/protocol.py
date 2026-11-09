"""Frozen inputs shared by every arm; labels never imply a measured benefit."""

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PROTOCOL = "coordination-cascades-v1"
ARMS = {
    "B0": "Safety guards only",
    "B1": "Per-agent retry cap",
    "B2": "Global rate cap",
    "B3": "Exact-key deduplication",
    "B4": "Dependency backpressure + dedup",
    "B4_no_graph": "Ablation: root-only backpressure",
    "B5": "Exponential backoff",
    "A_ready_queue": "Dependency-ready queue + dedup",
}
SCENARIOS = {
    "normal": "Normal authorized work",
    "legitimate_wait": "Legitimate human approval delay",
    "retry_cascade": "Repeated requests on a shared gate",
    "pending_gate": "Approval remains pending",
    "denied_gate": "Approval denied",
    "delayed_telemetry": "Delayed approval and completion observations",
    "telemetry_loss": "Approval update omitted",
    "runtime_disconnect": "One host temporarily unavailable",
    "graph_error": "Incorrect dependency includes independent work",
}
TASKS = ("plan", "access", "research", "validate", "report", "public")
GOALS = TASKS[1:]
DEPENDENCIES = {
    "plan": set(),
    "access": {"plan"},
    "research": {"access"},
    "validate": {"access"},
    "report": {"research", "validate"},
    "public": {"plan"},
}
METRICS = {
    "coordination_requests": ("requests", False),
    "guard_checks": ("checks", False),
    "blocked_checks": ("checks", False),
    "notifications": ("callbacks", False),
    "authorized_completion": ("fraction", True),
    "independent_completed": ("fraction", True),
    "independent_latency": ("ticks; horizon if incomplete", False),
    "false_hold_task_ticks": ("task ticks", False),
    "unsafe_starts": ("effects", False),
    "duplicate_effects": ("effects", False),
    "control_intents": ("simulated parks", False),
    "modeled_work_units": ("modeled units, not dollars", False),
}


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Protocol(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["coordination-cascades-v1"] = "coordination-cascades-v1"
    scenarios: list[str] = Field(
        default_factory=lambda: list(SCENARIOS), min_length=1, max_length=9
    )
    arms: list[str] = Field(default_factory=lambda: list(ARMS), min_length=1, max_length=8)
    seeds: list[int] = Field(default_factory=lambda: list(range(30)), min_length=1, max_length=100)
    horizon_ticks: int = Field(default=60, ge=40, le=120)
    retry_cap: int = Field(default=3, ge=1, le=10)
    global_per_tick: int = Field(default=2, ge=1, le=5)
    intervention_threshold: int = Field(default=3, ge=2, le=10)
    work_weights: tuple[int, int, int] = (1, 3, 10)

    @model_validator(mode="after")
    def valid_choices(self) -> "Protocol":
        if any(s not in SCENARIOS for s in self.scenarios) or any(a not in ARMS for a in self.arms):
            raise ValueError("Unknown scenario or policy arm")
        if any(len(v) != len(set(v)) for v in (self.scenarios, self.arms, self.seeds)):
            raise ValueError("Scenarios, arms and seeds must be unique")
        if any(type(seed) is not int or not 0 <= seed < 2**31 for seed in self.seeds):
            raise ValueError("Seeds must be nonnegative 31-bit integers")
        if self.work_weights != (1, 3, 10):
            raise ValueError("Protocol v1 fixes work weights at 1/3/10; these are not actual cost")
        return self
