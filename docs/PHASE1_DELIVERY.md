# Phase 1 delivery

Prepared November 1, 2026, before the hackathon. This report covers the observation
vertical slice only. No production reliability, benchmark advantage, payment
integration or successful runtime intervention is claimed.

## Repository findings and decisions

The initial repository contained six DOCX specifications, one Implementation Plan,
the implementation backlog CSV, UI action CSV, SQL and OpenAPI; no application
code. All DOCX paragraphs and table-cell text were extracted and read. A second
Implementation Plan and the referenced schema smoke test/event-envelope JSON
schema were absent. New tests replace the missing smoke test; they are not
presented as the supplied original test.

The architecture, source precedence and conflict decisions are recorded in
`docs/decisions/0001-foundation.md`. Python 3.11+ resolves the minimum-version
conflict. OpenAPI's lifecycle envelope governs REST; trust/source/project come
from credentials. Original files remain unchanged. Their SQL/API copies are
byte-identical. The packaged SQL/manifest copies match the frozen migration.

## Working behavior

The SDK creates Observe runs, registers agents, creates tasks, records starts,
host-reported completions/failures, retries, explicit dependencies, handoffs and
pending approval requests. It supports W3C context propagation, application-owned
tracers, stable event retries, lost-response reconciliation and bounded degraded
telemetry buffering. It does not replace the global OTel provider.

FastAPI accepts lifecycle batches and official OTLP/HTTP protobuf/JSON exports,
including bounded gzip decoding. Ingestion validates correlation, stores exact
timestamps, links and sanitized evidence, rejects conflicting replays, and commits
domain projections/outbox notifications before acknowledging. A bounded SQLite
writer uses the unchanged 31-table migration, foreign keys, WAL and busy timeout.

Authenticated REST returns run lists/detail, explicit task/agent graphs and
cursor-paginated events/spans. Graph versions count accepted evidence records.
No span hierarchy is converted into a business dependency. Span events are
untrusted reports and never drive task completion or privileged state.

## Verification actually executed

Environment: Python 3.12.3, SQLite supplied by that interpreter, uv 0.13.6;
dependency versions are recorded in `uv.lock`. Python 3.11 is configured in CI
but was not separately executed locally. CI itself has not been run remotely.

| Check | Observed result |
| --- | --- |
| `.venv/bin/pytest -q -o faulthandler_timeout=15` | **40 passed**, one upstream Starlette/HTTPX deprecation warning |
| `.venv/bin/ruff check .` | Passed |
| `.venv/bin/ruff format --check .` | Passed |
| `.venv/bin/mypy` | Passed; 15 source files checked |
| `make init-local` | Generated ignored mode-0600 local credentials |
| `make db-init` | Schema 001 initialized |
| `make server` + `make demo SEED=7` | Real HTTP ingestion succeeded; no SDK telemetry degradation; exporter flush completed |
| Authenticated real HTTP graph/timeline queries | Six tasks, five edges, seven spans, 50 timeline items, two completed tasks and four waiting tasks |
| Server source/wheel build | Passed; wheel initialized 31 tables outside the source checkout |
| Standalone SDK source/wheel build | Passed; typed package has no backend/agent-framework dependencies |
| Implemented OpenAPI inspection | Bearer scheme registered; health remains public |
| `make check` (using the workspace uv executable) | Passed: Ruff lint/format, mypy, 40 tests; one upstream deprecation warning |

The real smoke-test run is stored locally under
`6072f1e3-de9a-4604-bd0f-608f1871e6bc`. Its run state is `waiting`; no approval
was granted. The backend started for verification was stopped after the test.
The `.env` and local database are ignored and not release artifacts.

Integration tests exercise official protobuf responses, JSON hex identifiers,
unknown-field handling, malformed/gzip/size errors, partial acceptance, exact
nanoseconds, link persistence, redaction, project/run membership, concurrent
deduplication, per-record rollback, write-failure rollback/503, writer saturation,
out-of-order events, workflow completion, pagination, SDK lost responses and
the six-agent ingestion-to-query path. Separate schema tests verify that the
original migration rejects applied commands without ACKs and unverified
settlement claims; this does not constitute implemented command/payment APIs.

The sandbox blocked package downloads and TestClient's event-loop wakeup;
dependency installation and integration tests succeeded with the tool's approved
environment access. This was not an application startup failure.

## Created implementation files

- Workspace: `pyproject.toml`, `uv.lock`, `Makefile`, `.env.example`, `.gitignore`,
  `.github/workflows/ci.yml`, `README.md`.
- SDK: `packages/sdk/pyproject.toml`, `src/swarmcircuit/{__init__.py,run.py,
  instrumentation.py,py.typed}` under that package.
- Server: `packages/server/pyproject.toml`, `src/swarmcircuit_server/{__init__.py,
  app.py,config.py,errors.py,repository.py,logging_config.py,py.typed}`;
  `api/__init__.py`; `db/{__init__.py,store.py,migrations/001_initial.sql,
  migrations/manifest.json}`; `ingest/{__init__.py,events.py,otlp.py}`.
- Frozen contracts: `migrations/{001_initial.sql,manifest.json}`,
  `contracts/openapi.yaml`.
- Example/setup: `examples/{__init__.py,stalled_dependency.py}`,
  `scripts/{init_local.py,db_init.py}`.
- Tests: `tests/{__init__.py,conftest.py,test_foundation.py,test_otlp.py,
  test_failures.py,test_sdk_integration.py,test_schema_safety.py}`.
- Documentation: this report, `docs/decisions/0001-foundation.md`,
  `docs/provenance/PREEXISTING_WORK.md`, `apps/studio/README.md`,
  `experiments/README.md`.

## Start and validate

```bash
make bootstrap
make init-local
make db-init
make server
# In another terminal:
make demo SEED=7
make check
```

Full SDK/query examples and environment configuration are in `README.md`.
Use one loopback worker. No Langfuse, NestJS, agent framework or external service
is required. Initial run creation requires the local server.

## Remaining work and next task

No remaining blocker prevents running Phase 1. The upstream deprecation warning
is disclosed; tests currently pass with the pinned environment. A license still
needs to be selected before public open-source distribution.

Phase 2 remains next: implement deterministic stall/retry/approval-storm detectors
with evidence IDs, detector version/thresholds, incident lifecycle, and negative
tests for legitimate human waiting. Phase 3 must add fenced runtime sessions,
cooperative checkpoints, command dispatch/readback and validated ACKs before any
hold/resume claims or Causal Backpressure. GateKeep402, Studio/WebSockets and
matched-seed comparative experiments are later phases. Automated retention and
persistent offline SDK spooling are also deferred. The example is preparation,
not a research evaluation or evidence of general multi-agent behavior.
