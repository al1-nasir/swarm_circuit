"""Run, export and independently replay bounded preparation experiments."""

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import load_dotenv

from swarmcircuit_server.research.metrics import measurements
from swarmcircuit_server.research.protocol import Protocol, canonical, digest
from swarmcircuit_server.research.provider import ModelClient, ProviderFailure, collect_workload
from swarmcircuit_server.research.simulator import simulate


def source_fingerprint(root: Path) -> dict:
    paths = sorted((root / "packages/server/src/swarmcircuit_server/research").glob("*.py"))
    paths += [root / "packages/server/src/swarmcircuit_server/detectors/rules.py", root / "uv.lock"]
    hashes = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    return {"kind": "source_sha256; not a git commit", "sha256": digest(hashes), "files": hashes}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run", "llm", "verify"])
    parser.add_argument("--api", default=os.getenv("SWARM_API_URL", "http://127.0.0.1:18005"))
    parser.add_argument("--seeds", type=int, default=30)
    parser.add_argument("--seed-start", type=int, default=0)
    parser.add_argument("--scenarios", help="Comma-separated protocol scenario keys")
    parser.add_argument("--arms", help="Comma-separated policy IDs")
    parser.add_argument("--experiment-id")
    parser.add_argument("--output", type=Path, default=Path("artifacts/research"))
    parser.add_argument(
        "--max-calls",
        type=int,
        default=30,
        help="Total live-model request cap for the whole invocation; max 60",
    )
    args = parser.parse_args()
    load_dotenv(Path.cwd() / ".env", override=False)
    if args.command == "verify":
        manifest = json.loads((args.output / "manifest.json").read_text())
        protocol = Protocol.model_validate(manifest["protocol"])
        verified_count = 0
        expected_rows = {}
        for artifact in sorted(args.output.glob("*/outcome.json")):
            saved = json.loads(artifact.read_text())
            replay = simulate(
                protocol, saved["scenario"], saved["arm"], saved["seed"], saved.get("proposals")
            )
            if replay["artifact_sha256"] != saved["artifact_sha256"]:
                raise SystemExit(f"Replay mismatch: {artifact.parent.name}")
            if measurements(protocol, replay["truth"]) != saved["measurements"]:
                raise SystemExit(f"Metric mismatch: {artifact.parent.name}")
            for key, value in saved["measurements"].items():
                expected_rows[(saved["trial_id"], key)] = value
            verified_count += 1
        if verified_count != manifest["completed_trials"]:
            raise SystemExit("Missing outcome artifacts")
        csv_path = args.output / "metrics.csv"
        if hashlib.sha256(csv_path.read_bytes()).hexdigest() != manifest["csv_sha256"]:
            raise SystemExit("CSV artifact checksum mismatch")
        csv_rows = list(csv.DictReader(io.StringIO(csv_path.read_text())))
        found_rows = set()
        failed_ids = set()
        for row in csv_rows:
            if (
                row["experiment_id"] != manifest["experiment_id"]
                or row["protocol_sha256"] != manifest["protocol_sha256"]
                or row["source_sha256"] != manifest["source"]["sha256"]
            ):
                raise SystemExit("CSV provenance does not match its manifest")
            if row["state"] == "failed":
                if row["value"] or not row["failure_code"]:
                    raise SystemExit("A failed trial was filled with a numeric outcome")
                failed_ids.add(row["trial_id"])
                continue
            identity = (row["trial_id"], row["metric"])
            if identity in found_rows or identity not in expected_rows:
                raise SystemExit("Unexpected or duplicate CSV measurement")
            value = expected_rows[identity]
            if (
                float(row["value"]) != value["value"]
                or float(row["denominator"]) != value["denominator"]
                or row["unit"] != value["unit"]
            ):
                raise SystemExit("CSV measurement differs from replayed tool/host truth")
            found_rows.add(identity)
        if found_rows != set(expected_rows) or len(failed_ids) != manifest["failed_trials"]:
            raise SystemExit("CSV is missing completed measurements or failed trial records")
        print(
            json.dumps(
                {
                    "verified_trials": verified_count,
                    "csv_sha256": manifest["csv_sha256"],
                    "provider_calls": 0,
                }
            )
        )
        return
    if not 1 <= args.seeds <= 100 or not 1 <= args.max_calls <= 60:
        parser.error("Use 1–100 seeds and a 1–60 total model-call cap")
    p = Protocol(
        seeds=list(range(args.seed_start, args.seed_start + args.seeds)),
        **({"scenarios": args.scenarios.split(",")} if args.scenarios else {}),
        **({"arms": args.arms.split(",")} if args.arms else {}),
    )
    if args.command == "llm" and ("B0" not in p.arms or not args.scenarios):
        parser.error("LLM workload collection requires B0 and an explicit --scenarios list")
    eid = args.experiment_id or str(uuid4())
    output = args.output / eid
    output.mkdir(parents=True, exist_ok=True)
    source = source_fingerprint(Path.cwd())
    model = None
    if args.command == "llm":
        model = ModelClient(
            os.environ["SWARM_MODEL_BASE_URL"],
            os.environ["SWARM_MODEL_NAME"],
            os.environ["SWARM_MODEL_API_KEY"],
            args.max_calls,
        )
    token = os.environ["SWARM_OPERATOR_TOKEN"]
    source_kind = "llm_workload_replay" if model else "synthetic"
    completed = failed = 0

    def checked(response: httpx.Response) -> httpx.Response:
        if not response.is_success:
            # Never print request headers, provider bodies or secrets in a traceback.
            try:
                code = response.json().get("code", "request_failed")
            except ValueError:
                code = "request_failed"
            raise SystemExit(f"Local research API returned HTTP {response.status_code}: {code}")
        return response

    try:
        with httpx.Client(
            base_url=args.api.rstrip("/") + "/api/v1/",
            headers={"Authorization": f"Bearer {token}"},
            timeout=120,
            trust_env=False,
        ) as api:
            checked(
                api.post(
                    "experiments",
                    json={
                        "experiment_id": eid,
                        "title": "LLM workload pilot (preparation)"
                        if model
                        else "Coordination policy pilot (preparation)",
                        "protocol": p.model_dump(mode="json"),
                        "implementation_sha": source["sha256"],
                        "source_kind": source_kind,
                    },
                )
            )
            for scenario in p.scenarios:
                for seed in p.seeds:
                    tape = None
                    failure = None
                    calls_before = model.calls if model else 0
                    entries_before = len(model.entries) if model else 0
                    input_before = model.input_tokens if model else 0
                    output_before = model.output_tokens if model else 0
                    try:
                        if model:
                            if model.calls >= model.limit:
                                raise ProviderFailure("budget_exhausted")
                            tape = collect_workload(model, p, scenario, seed)
                    except ProviderFailure as exc:
                        failure = exc.code
                    provenance = model.provenance() if model else {}
                    if model:
                        provenance["calls"] = model.calls - calls_before
                        provenance["transcript_sha256"] = digest(model.entries[entries_before:])
                        provenance["input_tokens"] = (
                            model.input_tokens - input_before if model.usage_available else None
                        )
                        provenance["output_tokens"] = (
                            model.output_tokens - output_before if model.usage_available else None
                        )
                        (output / f"model-{scenario}-{seed}.json").write_text(
                            canonical(model.entries[entries_before:]) + "\n"
                        )
                    for arm in p.arms:
                        request = {
                            "scenario": scenario,
                            "arm": arm,
                            "seed": seed,
                            "provenance": provenance,
                        }
                        if tape is not None:
                            request["proposals"] = tape
                        if failure:
                            request["failure_code"] = failure
                            checked(api.post(f"experiments/{eid}/trials", json=request))
                            failed += 1
                            continue
                        result = simulate(p, scenario, arm, seed, tape)
                        request["expected_artifact_sha256"] = result["artifact_sha256"]
                        saved = checked(api.post(f"experiments/{eid}/trials", json=request)).json()
                        directory = output / f"{scenario}--{arm}--{seed}"
                        directory.mkdir(exist_ok=True)
                        result["proposals"] = tape
                        result["measurements"] = measurements(p, result["truth"])
                        result["trial_id"], result["run_id"] = saved["trial_id"], saved["run_id"]
                        (directory / "outcome.json").write_text(canonical(result) + "\n")
                        for name in ("truth", "observations"):
                            (directory / f"{name}.jsonl").write_text(
                                "\n".join(canonical(e) for e in result[name]) + "\n"
                            )
                        completed += 1
                    if model:
                        (output / "model-transcript.json").write_text(
                            canonical(model.entries) + "\n"
                        )
                        print(
                            json.dumps(
                                {
                                    "scenario": scenario,
                                    "seed": seed,
                                    "calls_this_workload": model.calls - calls_before,
                                    "total_calls": model.calls,
                                    "failure": failure,
                                }
                            ),
                            flush=True,
                        )
            csv_bytes = checked(api.get(f"experiments/{eid}/export.csv")).content
            (output / "metrics.csv").write_bytes(csv_bytes)
            results = checked(api.get(f"experiments/{eid}/results")).json()
            (output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
            manifest = {
                "experiment_id": eid,
                "protocol": p.model_dump(mode="json"),
                "protocol_sha256": digest(p.model_dump(mode="json")),
                "source": source,
                "source_kind": source_kind,
                "completed_trials": completed,
                "failed_trials": failed,
                "csv_sha256": hashlib.sha256(csv_bytes).hexdigest(),
                "preparation_date": "2026-11-05",
                "sprint_contribution": False,
                "model_provenance": model.provenance() if model else None,
                "limitations": [
                    "Algorithm simulation, not measured production performance.",
                    "Safety guards are identical by construction.",
                    "LLM proposals are replayed open-loop, not resampled in every counterfactual.",
                    "Pre-sprint preparation; no claim of hackathon-period work.",
                ],
            }
            (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
            print(
                json.dumps(
                    {
                        "experiment_id": eid,
                        "completed": completed,
                        "failed": failed,
                        "artifacts": str(output),
                        "view": f"http://127.0.0.1:3300/experiments/{eid}",
                    }
                ),
                flush=True,
            )
    finally:
        if model:
            model.close()


if __name__ == "__main__":
    main()
