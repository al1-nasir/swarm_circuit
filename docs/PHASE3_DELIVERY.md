# Phase 3 delivery

Prepared November 2, 2026, before the November 6–8 hackathon. This phase implements
trusted cooperative runtime control and bounded Causal Backpressure. Engineering
tests and mock demonstrations are not comparative research results.

## Implemented behavior

- Explicit Control-mode runs, SDK-authorized runtime registration, hashed private
  credentials, idempotent nonce replay, fencing epochs, absolute TTL and heartbeat
  leases. Operator submission and runtime ACK authority are separate.
- Exclusive task ownership and reversible checkpoint enter/get/leave. The SDK
  physically blocks inside the checkpoint; it never interrupts in-flight work.
- Idempotent hold/resume submission, dispatch/redelivery, durable command GET,
  stable ACK replay and atomic task/command/evidence/outbox updates. Enqueue alone
  never changes a task to held or reports a successful intervention.
- Capability, current session/epoch, task version and owned boundary checks at
  submission, dispatch and applied ACK. Resume/leave also check dependency,
  human-approval and payment guards. Observations cannot overwrite active control.
- Queued timeout becomes `timed_out`; dispatched timeout or a failed ACK becomes
  `unknown`. Restart/disconnection makes active boundaries uncertain. Replacement
  epochs cannot adopt unresolved boundaries or silently resume affected work.
- Causal Backpressure preview and explicit operator application over the pending
  approval root's explicit dependency closure. Independent branches are excluded;
  target bounds reject atomically. Policy/configuration/target snapshots and
  child command IDs persist. Auto-application and auto-resume remain off.
- Optional approval notification coalescing at a separate SDK presentation hook.
  Original request evidence and pending approval remain intact; uncertain callback
  effects are not retried. This grants no authorization.
- Graph control eligibility/reasons, incident control hints, sanitized session
  reads, additive OpenAPI supplement, schema 002 and package version 0.3.0.

The original SQL, OpenAPI and specification documents remain unchanged. Migration
002 adds six control-context tables, taking the database from 31 to 37 tables.
An upgrade test confirms existing run data survives. See
[the control decision](decisions/0003-control.md) for contract tightenings, trust
assumptions and failure semantics.

## Verification executed

| Check | Actual result |
| --- | --- |
| `UV_CACHE_DIR=/tmp/swarm-uv make check UV=.venv/bin/uv` | **97 passed**; Ruff lint/format passed; mypy passed for 23 source files |
| Authority and replay | SDK/operator/runtime separation, scoped task ownership, nonce fencing, command/ACK idempotency and changed-payload rejection |
| Failure handling | Healthy-heartbeat command deadlines, absolute credential expiry, stale task version/epoch/session ACK rejection, server restart and uncertain boundaries |
| Transaction safety | Injected failure after ACK/task mutation rolls back command, task, checkpoint and ACK evidence; stable retry then succeeds |
| SDK integration | Physical park/resume, independent task completion, lost ACK-response canonical reconciliation, fail-closed timeout and notification coalescing |
| Causal Backpressure | Explicit/bounded/idempotent application; bound exhaustion creates no commands; two concurrent SDK checkpoints remain parked while independent work completes and approval stays pending |
| Safety guards | Unfinished prerequisites, unverified/pending approval, ASK/DENY gates and unknown payments prevent resume; no public bypass endpoint |
| Migration/contracts | Original bytes preserved, root/bundled migration manifests match, 001→002 retains existing data, generated supplement matches implemented routes |
| Real HTTP control example | Applied hold and resume, independent completion, one mock action, two stored runtime ACKs, both tasks completed; telemetry healthy and OTel flush succeeded |
| Observe regression demo, seed 7 | Six-agent scenario still returns approval-storm, retry-amplification and shared-blocker-cascade incidents; telemetry healthy and OTel flush succeeded |
| SDK/server distributions | Version 0.3.0 source distributions and wheels built offline |
| Wheel smoke outside checkout | SDK/runtime imports, control routes, packaged schema 002, all 37 tables and foreign-key checks passed |

One upstream Starlette/HTTPX TestClient deprecation warning remains. The first
full run found an incomplete approval scope in the new integration fixture; it
was corrected and the final full suite passed. No Phase 3 test failure remains.
Python 3.12.3 and uv 0.13.6 were used locally; remote CI was not executed.

The live control run was `0c0ac7d8-b9ad-4418-a13b-12737af7dd42`:

- Hold: `d0c75b95-d423-4f1a-9d28-b3064e5c00a6`, applied with one matching ACK.
- Resume: `7c8bdfb8-99b1-448a-8ae9-f59a873e0247`, applied with one matching ACK.
- Both recorded tasks completed; the protected task's version advanced through
  start, hold, resume and completion. Its mock action ran once in the example.

The Observe regression run was `4ff98f90-c380-442a-9395-3578b5299314`.
Sanitized HTTP readback was saved in ignored `artifacts/phase3-smoke.json`; raw
sanitized source evidence, ACKs and policy records remain in the ignored local
SQLite database. Local credentials were preserved and never printed. Port 8000
was occupied by an unrelated service, so the temporary SwarmCircuit backend used
loopback port 18003 and was stopped after verification. The unrelated service
was left running.

## Files added or changed

Added:

- `packages/server/src/swarmcircuit_server/controller/{__init__.py,models.py,service.py}`.
- `packages/server/src/swarmcircuit_server/api/control.py`.
- `packages/sdk/src/swarmcircuit/runtime.py`.
- `migrations/002_runtime_control.sql` and its packaged copy.
- `contracts/control-v1.openapi.yaml` and `scripts/export_control_contract.py`.
- `examples/cooperative_control.py`.
- `tests/test_control.py` and `tests/test_runtime_sdk.py`.
- `docs/decisions/0003-control.md` and this delivery report.

Changed:

- Server `app.py`, `config.py`, `repository.py` and `ingest/events.py` for control
  mode, readiness, lifecycle protection, graph eligibility and request wiring.
- SDK `run.py` and `__init__.py` for Control runs, runtime access, approval event
  correlation, fail-closed task contexts and public exports.
- Both migration manifests, `scripts/db_init.py` and foundation tests for schema
  002, upgrade preservation and frozen/implemented contract verification.
- Root/package `pyproject.toml` files and `uv.lock` for version 0.3.0.
- `Makefile`, `.env.example`, `README.md` and the provenance inventory.

## Run and inspect

```bash
make bootstrap
make init-local
make db-init
make server
# In a second terminal:
make demo-control
make demo SEED=7
make check
```

Use `PORT=18003` for the server and `SWARM_API_URL=http://127.0.0.1:18003` for
examples if necessary. The control example prints command IDs for canonical GET
readback with the SDK or operator credential. Runtime tokens are private to the
host. `make control-contract` regenerates only the additive supplement.

## Limitations and next phase

This is a single-worker local control MVP. Hosts must place honest cooperative
hooks before reversible work and stop on `ControlError`. ACKs establish the
trusted host's report, not independently verified external execution. Control
cannot interrupt or roll back an action that has already crossed its checkpoint.
The SDK has no durable cross-process journal or seamless recovery of uncertain
boundaries; no global exactly-once effect guarantee is claimed.

Cancellation, automated recovery, force clearing/adopting an uncertain boundary,
and command-based approval coalescing are deferred. The separate presentation hook
only suppresses duplicate notifications. Pending or denied approvals cannot be
resolved through it. Historical ASK/DENY payment decisions conservatively block
release pending an external reconciliation protocol. No payment is signed, retried
or authorized by this phase.

Next is Phase 4: optional GateKeep402 telemetry integration and payment/approval
visibility, with a separately trusted mock approval broker for demonstrations.
Keep signing and authorization inside that integration, distinguish observations
from verified service outcomes, and never replay an uncertain payment. Studio
remains Phase 5; reproducible baseline comparisons and evaluation remain Phase 6.
