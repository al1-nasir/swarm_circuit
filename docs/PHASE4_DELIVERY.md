# Phase 4 delivery

Prepared November 2, 2026, before the November 6–8 hackathon. Implements optional
GateKeep402 observations and separately trusted mock approval/settlement callbacks
(SC-023–024). No real payment, wallet, signing or blockchain RPC was used.

## Implemented behavior

- Optional SDK adapter for the unchanged published GateKeep402 0.2.1, with
  openlibx402 core/client pinned to 0.1.1. Base SDK/backend imports work without
  payment packages. Native SourceGuard, policy decisions, ASK callbacks, delivery
  checks, exceptions and underlying auto-retry protection remain in GateKeep402.
- Metadata-only gate/submission/delivery observations, exact decimal amounts,
  full action-scope fingerprints, durable payment projection and immutable gate
  history. Unknown fields and raw protocol/content/credential data are discarded.
- Read-only, scoped, paginated approval/payment APIs with request counts,
  observation/receipt provenance, simulation labels and explicit blocking state.
- Disabled-by-default mock authority with a separate credential and explicit
  simulation-run restriction. Exact-scope approval/receipt callbacks are durable,
  idempotent and audited. DENY, terminal decisions, reused receipts, changed scope
  and retroactive approval are rejected. No generic force-approve or retry API.
- A simulated ASK becomes resume-eligible only after the exact independent
  broker approval. Operators still request resume and runtimes still ACK it.
  Unresolved dependencies and uncertain outcomes remain blocking. A DENY arriving
  after dispatch prevents the resume ACK from applying.
- Separate evidence-linked warnings for unknown settlement and failed structural
  delivery. A mock receipt resolves uncertainty without erasing delivery failure.
  Host success messages cannot mark payment settled.
- Complete native-package demonstration with two physically held branches,
  independent progress, scoped broker approval, explicit resumes, one mock effect,
  independent mock receipt, one dependent execution and a zero-effect DENY case.
- Additive migration 003 (two tables, 39 total), payment OpenAPI supplement,
  opt-in local mock credentials and package version 0.4.0.

The original specifications, SQL and OpenAPI remain unchanged. See the
[Phase 4 decision](decisions/0004-payment-evidence.md) for trust boundaries,
upstream version reconciliation and exact API/guard semantics.

## Verification executed

| Check | Actual result |
| --- | --- |
| Full `make check` with workspace uv | **124 passed**; Ruff lint/format and mypy passed for 30 source files |
| Baseline compatibility | All 97 previous foundation/control cases retained; baseline also passed after installing optional dependencies |
| New coverage | 27 additional cases covering metadata projection, amount validation, authority, callback replay/rollback, receipts, native integration, late DENY and ingestion ordering |
| Actual upstream package | Native ALLOW/ASK/DENY paths, unchanged callback behavior, SourceGuard header rejection, structural delivery failure, telemetry-failure DENY preservation |
| Payment safety | SDK/operator cannot invoke broker; explicit simulation scope required; exact fingerprints checked; DENY remains blocking after later ALLOW reports; unapproved effects cannot be approved retroactively |
| Receipt safety | Delivery success and forged privileged events leave settlement unknown; no new attempt replay; unique mock receipts and stable callbacks reconcile one state effect |
| Persistence failure | Injected failure after receipt/payment updates rolls back receipt, settlement, callback and audit evidence; no false durable success |
| Control composition | Actual native ASK with two concurrent SDK checkpoints; independent branch completes; four matching runtime ACKs; approval alone does not resume anything |
| Contracts/migrations | Original bytes preserved; root/bundled migrations/manifests match; 001→003 upgrade retains existing data; supplements match implemented routes |
| Real HTTP payment demo | One mock payment, zero denied mock effects, one dependent execution, independent completion; delivery leaves unknown until mock receipt; telemetry healthy |
| Real HTTP control regression | Existing hold/resume example still records applied ACKs, one mock action, independent completion, healthy telemetry and successful OTel flush |
| Real HTTP Observe regression, seed 7 | Six-agent scenario still returns approval-storm, retry-amplification and shared-blocker-cascade incidents; healthy telemetry and successful OTel flush |
| Offline source/wheel builds | SDK/server 0.4.0 distributions built successfully |
| Wheel smoke outside checkout | SDK/adapter/server imports, packaged schema 003, all 39 tables, foreign keys and payment routes passed |
| Dependency isolation | Import blocker test confirms base SDK/runtime/adapter imports do not load GateKeep402, openlibx402, Solana or solders |

Local checks used Python 3.12.3 and uv 0.13.6. The final suite had no warnings or
failures. Remote CI and comparative research experiments were not executed.

The real payment demo run was `5bb36eed-233c-4170-baf1-62cb87b8bcd0`.
Its approval was `b9df9cdf-0f8b-5c44-a880-179a0ed08d07`. Stored readback confirmed:

- Two holds: `9dc7bd01-a179-4714-9786-407069e137c5` and
  `b35c7b00-c669-4061-827b-959eeaed9d47`.
- Two resumes: `330b265b-28ae-4833-b0ca-fb785f46415e` and
  `159bc60b-c6ff-465a-9e08-f473c402b770`.
- All four commands applied with exactly one matching ACK each.
- Three completed tasks and one intentionally blocked DENY task.
- Payment states `settled` and `denied`; the denied intent had no attempt.
- Approval/settlement events labelled `simulation_truth`, and the mock confirmed
  attempt labelled `receipt_trust=simulator_truth` as required by the schema.

Sanitized readback is in ignored `artifacts/phase4-smoke.json`. Source events,
ACKs, warnings and mock callbacks remain in the ignored local SQLite database.
The control regression run was `7d2fba66-ec08-4df4-9541-062e53f926ab`; the Observe
regression run was `1d17b99e-14f3-41c6-92d9-89a1573fb5ae`.

The temporary mock-enabled backend used loopback port 18004 and was stopped
after verification. `.env` was preserved; separately generated `.env.mock` is
ignored and mode 0600. No credential values were printed. The payment demo uses
SDK lifecycle evidence; it does not configure an additional OTel exporter.

## Files added or changed

Added:

- `packages/sdk/src/swarmcircuit/adapters/{__init__.py,gatekeep402.py}`.
- `packages/server/src/swarmcircuit_server/payments/{__init__.py,models.py,observations.py,service.py}`.
- `packages/server/src/swarmcircuit_server/api/payments.py`.
- `migrations/003_payment_evidence.sql` and its packaged copy.
- `contracts/payments-v1.openapi.yaml` and `scripts/export_payment_contract.py`.
- `examples/payment_visibility.py`.
- `tests/test_payments.py` and `tests/test_gatekeep_adapter.py`.
- `docs/decisions/0004-payment-evidence.md` and this report.

Changed:

- Server `app.py`, `config.py` and `repository.py` for run simulation metadata,
  mock configuration, route wiring, schema readiness and version.
- Server `ingest/events.py` for sanitized payment projection;
  `controller/service.py` for exact simulated ASK release;
  `detectors/rules.py` for payment warnings and stable delivery ordering.
- SDK `run.py` for simulation creation/reconciliation and tracer version.
- Root/package `pyproject.toml` files and `uv.lock` for version/optional pins.
- Migration manifests, schema initialization and foundation contract/schema tests.
- `scripts/init_local.py`, `scripts/export_control_contract.py`, `.gitignore`,
  `.env.example`, `Makefile`, README and provenance inventory.

## Run

```bash
make bootstrap
make init-local
make init-mock
make server-mock PORT=18004
# In another terminal:
SWARM_API_URL=http://127.0.0.1:18004 make demo-payment
make check
```

Normal `make server` leaves the broker disabled with default settings.
`make payment-contract` regenerates only the additive payment supplement.
Read APIs use SDK/operator credentials; callbacks require the independent broker
credential. No UI approval action is implemented.

## Remaining scope and next task

This is a single-worker local MVP with trusted cooperative hosts and an explicitly
isolated simulation broker. It is not a production payment authorizer or a
cryptographic audit log. No real human authentication, live receipt/finality
verification, wallet budget, global mandate, external action firewall or payment
execution/replay endpoint exists. Non-simulation ASK remains blocked pending a
real authority connector. Storage deduplication cannot prevent arbitrary wallet
calls outside the integration, and observation failure is disclosed through loss
indicators rather than changing native GateKeep402 decisions.

The upstream registry reader and structural delivery checks do not establish live
on-chain reputation or semantic content truth. Mock receipts prove only the
declared simulator's outcome. The original library is pre-existing work; adapter,
broker and demo changes are new pre-event preparation, not hackathon-period work.

Next is Phase 5: Next.js/TypeScript/Tailwind Studio with React Flow graph, timeline,
incident inspector and payment/approval visibility. Controls must reflect durable
ACKs, eligibility and uncertainty. Preserve Phase 6 matched-seed baselines,
independent ground truth and scientific evaluation ahead of frontend polish.
