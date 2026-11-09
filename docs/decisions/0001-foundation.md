# Foundation decisions

Reviewed on November 1, 2026: all six supplied DOCX documents (paragraphs and
table cells), the implementation backlog and action catalog, SQL, and OpenAPI.
The original specifications remain untouched. Frozen copies in `migrations/`
and `contracts/` must match the originals byte for byte.

## Reconciliation

- Only one Implementation Plan is present. Referenced `schema_smoke_test.py`,
  `event_envelope.schema.json`, and `backlog/tasks.csv` are absent. The supplied
  backlog CSV is used; replacement schema tests are explicitly new tests.
- TRD SDK prose permits Python 3.10; PRD/platform require 3.11+. Use 3.11+ for
  both packages and verify on the available Python 3.12 runtime.
- The schema's illustrative event envelope differs from OpenAPI. The executable
  REST contract takes precedence: the server supplies project, source and trust.
- `task.completed` updates an **observed** task state. This records an authenticated
  host report, never independent proof of completion or external effects.
- Parent spans and span links do not create business dependencies. Graphs are
  read-time projections of explicit domain records. No inferred control authority.
- Unknown lifecycle types are retained with an empty metadata payload and have
  no domain effect. Unsupported control/approval-resolution/payment events
  cannot modify privileged state. Phase 1 accepts Observe runs only (Control
  creation returns a structured conflict until runtime enforcement exists).
- App Flow identifies a missing durable command-status GET. Reconcile the
  contract in Phase 3 before adding that endpoint. Original OpenAPI is retained
  as the full target contract, while FastAPI `/openapi.json` describes only
  implemented endpoints. No placeholder endpoints for later features.
- Approved SQL remains unchanged. All 31 tables are installed; only Phase 1
  data paths are populated. Migration digests live in a checked-in manifest
  because the approved migration table has no checksum column.
  Identical SQL/manifest resources are also bundled in the server wheel so
  initialization does not depend on a source-checkout path.
- Local bootstrap provisions one project, SDK source and OTLP source. Separate
  SDK/operator bearer secrets come from the environment. OTLP claims are
  `self_report`; lifecycle events are `sdk_observation`. Neither token is an
  approval authority, settlement verifier or runtime command credential.
- A bounded writer thread serializes short transactions and commits before
  success. Queue saturation and commit failure return 503. A response timeout
  may leave a committed write; retrying the same key reconciles it safely.
- Metadata allowlists drop unknown payload/OTel fields; there is no raw-body
  archive. Evidence is sanitized source evidence, not a content capture system.
  Accepted names/titles/identifiers are metadata supplied by the caller: callers
  must not place secrets in these fields. Automated retention is deferred.

## Phase 1 implementation sequence

1. Python workspace, dependencies/lock, environment, lint/type/test CI.
2. Atomic original migration, foreign keys/WAL/busy timeout, digest checks.
3. Project/run/agent/task repository and credential-scoped services.
4. Commit-before-ACK lifecycle ingestion, stable dedup keys and transactional outbox.
5. OTLP protobuf and JSON, gzip/size guards, exact timestamps, links/correlation.
6. Run list/detail, task/agent graph, cursor-paginated timeline.
7. API-only SDK, optional explicit OTel provider factory, deterministic six-agent demo.
8. Integration tests including replay, redaction, isolation and persistence failure.

## Following slices

Phase 2: evidence-linked detectors and incident lifecycle. Phase 3: fenced runtime
sessions, cooperative checkpoints, durable command reads and ACKs, then Causal
Backpressure. Phase 4: optional unchanged GateKeep402 adapter. Phase 5: Studio.
Phase 6: matched-seed evaluation with independent simulator truth; prioritize
control and research over UI polish. No measured research benefit is claimed.

Protocol references checked: [OTLP](https://opentelemetry.io/docs/specs/otlp/),
[Python instrumentation](https://opentelemetry.io/docs/languages/python/instrumentation/).

