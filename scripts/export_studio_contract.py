"""Export additive Studio REST routes; the socket protocol is documented separately."""

from pathlib import Path

import yaml
from swarmcircuit_server.app import create_app


def studio_contract() -> dict:
    schema = create_app().openapi()
    paths = {
        path: {
            method: operation
            for method, operation in operations.items()
            if method == "get" or "stream-tickets" in path
        }
        for path, operations in schema["paths"].items()
        if "/stream-tickets" in path
        or "/evidence/" in path
        or path == "/api/v1/runs/{run_id}/control-commands"
    }
    for operations in paths.values():
        for operation in operations.values():
            operation["x-credential-role"] = "SDK project or operator; project scoped"
    return {
        "openapi": schema["openapi"],
        "info": {
            "title": "SwarmCircuit Studio REST supplement",
            "version": "0.5.0",
            "description": (
                "Additive Phase 5 reads and one-use 60-second run stream tickets. "
                "Responses are extensible sanitized metadata objects. WebSocket wire "
                "protocol: docs/decisions/0005-studio.md and contracts/studio-stream-v1.md. "
                "Original target contract unchanged."
            ),
        },
        "paths": paths,
        "components": schema["components"],
    }


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "contracts/studio-v1.openapi.yaml"
    target.write_text(yaml.safe_dump(studio_contract(), sort_keys=False))
    print(target)
