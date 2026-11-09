"""Explicit local configuration; credentials never come from telemetry labels."""

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid5

from swarmcircuit_server.detectors.rules import DetectorPolicy


@dataclass(frozen=True)
class Settings:
    db_path: Path
    sdk_token: str
    operator_token: str
    project_id: str = "11111111-1111-4111-8111-111111111111"
    max_bytes: int = 2_097_152
    queue_size: int = 128
    write_timeout: float = 5
    allowed_origins: tuple[str, ...] = ("http://localhost:3000",)
    detector_policy: DetectorPolicy = DetectorPolicy()
    detector_interval_seconds: float = 1
    runtime_heartbeat_timeout_ms: int = 15_000
    runtime_token_ttl_ms: int = 1_800_000
    command_timeout_ms: int = 30_000
    backpressure_limit: int = 20
    mock_broker_enabled: bool = False
    mock_broker_token: str = ""

    def __post_init__(self) -> None:
        UUID(self.project_id)
        if len(self.sdk_token) < 24 or len(self.operator_token) < 24:
            raise ValueError("Set separate random SDK/operator tokens (make init-local)")
        if self.sdk_token == self.operator_token:
            raise ValueError("SDK and operator tokens must differ")
        if self.mock_broker_enabled and (
            len(self.mock_broker_token) < 24
            or self.mock_broker_token in {self.sdk_token, self.operator_token}
        ):
            raise ValueError("Mock broker requires a separate random credential")
        if self.max_bytes < 1 or self.queue_size < 1 or self.write_timeout <= 0:
            raise ValueError("Ingestion limits must be positive")
        if not 0 <= self.detector_interval_seconds < float("inf"):
            raise ValueError("Detector interval must be finite and nonnegative")
        if (
            min(
                self.runtime_heartbeat_timeout_ms,
                self.runtime_token_ttl_ms,
                self.command_timeout_ms,
                self.backpressure_limit,
            )
            <= 0
        ):
            raise ValueError("Runtime timeouts and policy bounds must be positive")

    def source_id(self, kind: str) -> str:
        return str(uuid5(UUID(self.project_id), f"local:{kind}"))

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            db_path=Path(os.getenv("SWARM_DB_PATH", "data/swarmcircuit.db")),
            sdk_token=os.getenv("SWARM_SDK_PROJECT_TOKEN", ""),
            operator_token=os.getenv("SWARM_OPERATOR_TOKEN", ""),
            project_id=os.getenv("SWARM_PROJECT_ID", cls.project_id),
            max_bytes=int(os.getenv("SWARM_OTLP_MAX_BYTES", "2097152")),
            queue_size=int(os.getenv("SWARM_WRITE_QUEUE_SIZE", "128")),
            write_timeout=float(os.getenv("SWARM_WRITE_TIMEOUT_SECONDS", "5")),
            allowed_origins=tuple(
                os.getenv("SWARM_ALLOWED_ORIGINS", "http://localhost:3000").split(",")
            ),
            detector_interval_seconds=float(os.getenv("SWARM_DETECTOR_INTERVAL_SECONDS", "1")),
            runtime_heartbeat_timeout_ms=int(
                os.getenv("SWARM_RUNTIME_HEARTBEAT_TIMEOUT_MS", "15000")
            ),
            runtime_token_ttl_ms=int(os.getenv("SWARM_RUNTIME_TOKEN_TTL_MS", "1800000")),
            command_timeout_ms=int(os.getenv("SWARM_COMMAND_TIMEOUT_MS", "30000")),
            backpressure_limit=int(os.getenv("SWARM_BACKPRESSURE_LIMIT", "20")),
            mock_broker_enabled=os.getenv("SWARM_MOCK_BROKER_ENABLED", "false").lower() == "true",
            mock_broker_token=os.getenv("SWARM_MOCK_BROKER_TOKEN", ""),
            detector_policy=DetectorPolicy(
                approval_window_ms=int(os.getenv("SWARM_APPROVAL_WINDOW_MS", "30000")),
                approval_duplicate_threshold=int(
                    os.getenv("SWARM_APPROVAL_DUPLICATE_THRESHOLD", "3")
                ),
                retry_window_ms=int(os.getenv("SWARM_RETRY_WINDOW_MS", "60000")),
                retry_ratio_threshold=float(os.getenv("SWARM_RETRY_RATIO_THRESHOLD", "1.0")),
                stall_timeout_ms=int(os.getenv("SWARM_STALL_TIMEOUT_MS", "60000")),
            ),
        )
