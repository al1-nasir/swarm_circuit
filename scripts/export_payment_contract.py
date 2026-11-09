"""Export Phase 4 read/callback routes and the simulation run-creation extension."""

import json
from pathlib import Path
from typing import Any

import yaml
from swarmcircuit_server.app import create_app


def payment_contract() -> dict[str, Any]:
    schema = create_app().openapi()
    paths = {
        path: ops
        for path, ops in schema["paths"].items()
        if any(part in path for part in ("/approvals", "/payments", "/api/v1/mock/"))
        or path == "/api/v1/projects/{project_id}/runs"
    }
    for path, operations in paths.items():
        for method, operation in operations.items():
            operation["x-credential-role"] = (
                "mock broker; explicit simulation runs only; disabled by default"
                if "/mock/" in path
                else "SDK project"
                if method == "post"
                else "SDK project or operator"
            )
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
            "title": "SwarmCircuit payment evidence and mock authority supplement",
            "version": "0.4.0",
            "description": (
                "Phase 4. SDK observations cannot establish approval or settlement. "
                "Mock callbacks require an independent broker credential and simulation=true; "
                "they establish simulation truth only. No signing or real payment replay "
                "endpoint exists. Read responses are extensible metadata objects with root "
                "pagination and bounded nested lists."
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
    destination = Path(__file__).resolve().parents[1] / "contracts/payments-v1.openapi.yaml"
    destination.write_text(yaml.safe_dump(payment_contract(), sort_keys=False))
    print(destination)
