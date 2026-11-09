"""Create a secret-scanned, allowlisted local reproducibility archive."""

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/research"
OUT.mkdir(parents=True, exist_ok=True)
IDS = [
    "0ada95ca-a10a-4835-ade4-31c088c2e031",
    "c62bf7f9-78f0-4b3d-8ed5-996122ec36f2",
    "bb241eed-3584-4b64-aa15-1c2e2ea8bf54",
]
files = set()
for name in (
    "README.md",
    ".env.example",
    ".gitignore",
    "Makefile",
    "pyproject.toml",
    "uv.lock",
    "001_initial.sql",
    "openapi.yaml",
):
    files.add(ROOT / name)
for directory in (
    "packages",
    "apps/studio",
    "contracts",
    "migrations",
    "examples",
    "tests",
    "scripts",
    "experiments",
    "docs",
    "output/pdf",
    "artifacts/research/qa",
    *(f"artifacts/research/{eid}" for eid in IDS),
):
    for path in (ROOT / directory).rglob("*"):
        if (
            path.is_file()
            and not path.is_symlink()
            and not any(
                part
                in {
                    "__pycache__",
                    "node_modules",
                    ".next",
                    ".venv",
                    ".pytest_cache",
                    ".mypy_cache",
                    ".ruff_cache",
                    ".git",
                }
                for part in path.relative_to(ROOT).parts
            )
            and path.suffix not in {".pyc", ".tsbuildinfo", ".db", ".sqlite", ".log"}
        ):
            files.add(path)
secrets = [
    value.encode()
    for name, value in dotenv_values(ROOT / ".env").items()
    if value and len(value) >= 12 and ("TOKEN" in name or name.endswith("KEY"))
]
manifest = {}
for path in sorted(files):
    data = path.read_bytes()
    if path.name in {".env", ".env.mock"} or any(secret in data for secret in secrets):
        raise SystemExit("Refusing archive: a selected member contains a private credential")
    manifest[str(path.relative_to(ROOT))] = hashlib.sha256(data).hexdigest()
readme = """SwarmCircuit preparation reproducibility bundle - November 5, 2026

This is pre-sprint preparation, not an event-period submission or release.
The repository has no selected open-source license; this local archive does not
confer redistribution rights to supplied documents or third-party dependencies.
No .env, private database, credential, dependency installation or build cache is
included. Screenshots show mock workflows. Author/affiliation metadata needs review.

1. Extract; install Python 3.11+, uv and Node 22.18+.
2. make bootstrap; make init-local; make db-init; make server PORT=18005.
3. Offline replay (no provider calls):
   make research-verify EXPERIMENT_DIR=artifacts/research/0ada95ca-a10a-4835-ade4-31c088c2e031
   Repeat for each failed-study directory; expected verified completed trials 0.
4. make research recreates the synthetic study under a NEW UUID and populates the
   local DB; the included raw files do not ship a private SQLite database.
5. make studio-install; SWARM_API_URL=http://127.0.0.1:18005 make studio STUDIO_PORT=3300.
6. SWARM_API_URL=http://127.0.0.1:18005 make demo-containment for fresh SDK boundaries.
7. Optional paid calls require private provider configuration and an explicit
   make research-llm invocation. The included pilots FAILED. Do not treat them as
   completed live-model evidence. No call is needed to verify the archive.

The PDF is output/pdf/swarmcircuit-research-draft.pdf. Source script:
scripts/build_research_report.py (ReportLab 4.5.1, Matplotlib 3.11.2; Linux
Liberation Sans TrueType fonts). It reads the included results, not the network.
See experiments/README.md for metrics, censoring, denominators and limitations;
docs/DEMO_SCRIPT.md for the four-minute walkthrough; docs/PHASE6_DELIVERY.md
for actual checks. Model replay is open-loop; zero unsafe starts is a common
simulator guard invariant, not measured real-world risk. The queue outperforms
backpressure on some workloads. Graph/telemetry counterexamples are retained.

BUNDLE_MANIFEST.json maps each included member to its SHA-256. Validate those
hashes after extraction. The manifest itself and this README are container
metadata. Research manifests separately seal protocol, original source files,
CSV and completed trial journals. No Git commit is invented.
"""
archive = OUT / "swarmcircuit-preparation-bundle.zip"
with ZipFile(archive, "w", compression=ZIP_DEFLATED, compresslevel=7) as z:
    for path in sorted(files):
        z.write(path, str(path.relative_to(ROOT)))
    z.writestr("BUNDLE_MANIFEST.json", json.dumps(manifest, indent=2) + "\n")
    z.writestr("BUNDLE_README.txt", readme)
with ZipFile(archive) as z:
    assert z.testzip() is None
    for name, checksum in manifest.items():
        assert hashlib.sha256(z.read(name)).hexdigest() == checksum
sha = hashlib.sha256(archive.read_bytes()).hexdigest()
(OUT / "swarmcircuit-preparation-bundle.zip.sha256").write_text(sha + "  " + archive.name + "\n")
print(
    json.dumps(
        {
            "archive": str(archive),
            "members": len(manifest) + 2,
            "bytes": archive.stat().st_size,
            "sha256": sha,
            "credential_scan": "passed",
            "archive_checksums": "passed",
        }
    )
)
