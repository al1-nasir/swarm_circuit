"""Export additive Phase 6 research routes without changing frozen target OpenAPI."""

from pathlib import Path

import yaml
from swarmcircuit_server.app import create_app


def research_contract() -> dict:
    schema = create_app().openapi()
    paths = {
        path: operations for path, operations in schema["paths"].items() if "/experiments" in path
    }
    for operations in paths.values():
        for method, operation in operations.items():
            operation["x-credential-role"] = (
                "operator; bounded local recording"
                if method == "post"
                else "SDK project or operator; project scoped"
            )
    return {
        "openapi": schema["openapi"],
        "info": {
            "title": "SwarmCircuit research protocol supplement",
            "version": "0.6.0",
            "description": (
                "Read-only research evidence plus bounded local CLI recording. Does "
                "not launch paid provider requests. Original target contract "
                "unchanged."
            ),
        },
        "paths": paths,
        "components": schema["components"],
    }


if __name__ == "__main__":
    output = Path(__file__).resolve().parents[1] / "contracts/research-v1.openapi.yaml"
    output.write_text(yaml.safe_dump(research_contract(), sort_keys=False))
    print(output)
