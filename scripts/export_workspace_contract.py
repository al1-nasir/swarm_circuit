"""Export additive guided-workflow and workspace reads; frozen target spec remains unchanged."""

import json
from pathlib import Path
from typing import Any

import yaml
from swarmcircuit_server.app import create_app


def workspace_contract() -> dict[str, Any]:
    schema = create_app().openapi()
    paths = {
        path: ops
        for path, ops in schema["paths"].items()
        if any(
            part in path
            for part in (
                "/demos",
                "/demo-capabilities",
                "/workspace",
                "/brief",
                "/backpressure/history",
            )
        )
    }
    for operations in paths.values():
        for method, operation in operations.items():
            operation["x-credential-role"] = (
                "operator; owned demo only" if method == "post" else "SDK project or operator"
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
            "title": "SwarmCircuit guided workspace supplement",
            "version": "0.8.0",
            "description": (
                "Source-bound progress, connected-host summaries and durable control history. "
                "Guided workflows run bounded local fixtures through actual SDK checkpoints. "
                "Fixture mode makes no model calls. Explicit live mode permits a writer, "
                "reviewer and at most one repair over sample data, with three calls maximum. "
                "Demo permission decisions cannot authorize other workflows, real payments "
                "or production approvals."
            ),
        },
        "paths": paths,
        "components": {
            "schemas": {name: schemas[name] for name in sorted(needed)},
            "securitySchemes": schema["components"].get("securitySchemes", {}),
        },
    }


if __name__ == "__main__":
    output = Path(__file__).resolve().parents[1] / "contracts/workspace-v1.openapi.yaml"
    output.write_text(yaml.safe_dump(workspace_contract(), sort_keys=False))
    print(output)
