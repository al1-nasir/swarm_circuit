"""Export implemented control routes without modifying the frozen target contract."""

import json
from pathlib import Path
from typing import Any

import yaml
from swarmcircuit_server.app import create_app

ROOT = Path(__file__).resolve().parents[1]


def control_contract() -> dict[str, Any]:
    schema = create_app().openapi()
    paths = {
        path: operations
        for path, operations in schema["paths"].items()
        if any(part in path for part in ("runtime-sessions", "control-commands", "backpressure"))
    }
    for path, operations in paths.items():
        for method, operation in operations.items():
            if "runtime-sessions/{session_id}" in path or path.endswith("/ack"):
                role = "runtime session"
            elif (path.endswith("/backpressure") and method == "post") or (
                path.endswith("/control-commands") and method == "post"
            ):
                role = "operator"
            elif method == "post":
                role = "SDK project"
            else:
                role = "SDK project or operator"
            operation["x-credential-role"] = role
    needed: set[str] = set()
    pending = [json.dumps(paths)]
    schemas = schema["components"]["schemas"]
    while pending:
        content = pending.pop()
        for name in schemas:
            if f'#/components/schemas/{name}"' in content and name not in needed:
                needed.add(name)
                pending.append(json.dumps(schemas[name]))
    return {
        "openapi": schema["openapi"],
        "info": {
            "title": "SwarmCircuit implemented control protocol supplement",
            "version": "0.5.0",
            "description": (
                "Phase 3 protocol with Phase 5 durable history; original openapi.yaml is frozen. "
                "Only hold/resume at explicitly owned reversible checkpoints are supported. "
                "Task ID is mandatory. Credential roles are enforced by the service; "
                "runtime tokens are returned only at SDK registration. "
                "See docs/decisions/0003-control.md for safety and recovery semantics."
            ),
        },
        "paths": paths,
        "components": {
            "schemas": {name: schemas[name] for name in sorted(needed)},
            "securitySchemes": {
                name: value
                for name, value in schema["components"]["securitySchemes"].items()
                if any(
                    name in security
                    for ops in paths.values()
                    for operation in ops.values()
                    for security in operation.get("security", [])
                )
            },
        },
    }


if __name__ == "__main__":
    destination = ROOT / "contracts/control-v1.openapi.yaml"
    destination.write_text(yaml.safe_dump(control_contract(), sort_keys=False))
    print(destination)
