"""Explicit workflow categories plus a narrow legacy label for old gateway checks."""

from typing import Any


def diagnostic_sql(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    return (
        f"(COALESCE(json_extract({prefix}metadata_json,'$.diagnostic'),0)=1 OR "
        f"COALESCE(json_extract({prefix}metadata_json,'$.kind') IN ('diagnostic','test'),0) OR "
        f"{prefix}name='Studio gateway verification')"
    )


def classify(name: str, metadata: dict[str, Any]) -> str:
    if metadata.get("research") == 1:
        return "research"
    if (
        metadata.get("diagnostic") == 1
        or metadata.get("kind") in ("diagnostic", "test")
        or name == "Studio gateway verification"
    ):
        return "diagnostic"
    return "workflow"
