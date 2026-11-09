# Phase 2 delivery

Prepared November 2, 2026, before the hackathon. This slice implements observation
rules and durable incident lifecycle. Runtime control remains Phase 3.

## Implemented behavior

- Deterministic approval-request storms, requested retry amplification, active-task
  stalls, suspected explicit task dependency cycles, and shared-blocker retry cascades.
- Evidence-backed findings with affected task IDs, source event references, window
  and threshold metrics, denominators, policy identity/hash and uncertainty.
- Persistent open/update/resolve/reopen transitions with retained evidence history,
  append-only derived events, transactional outbox and idempotent reconciliation.
- Post-commit evaluation plus a one-second scanner for timeouts, expiration,
  restart catch-up and recovery from detector persistence failures.
- Scoped `GET /api/v1/runs/{run_id}/incidents`, run incident counts and task graph
  incident overlays. No incident mutation endpoint or runtime enforcement.
- SDK `task.record_progress()` signals; fixed same-millisecond lifecycle ordering
  so random UUID order cannot discard waiting/completed transitions.
- Configurable/versioned thresholds, SDK/server package version 0.2.0, locked
  dependencies, and a live six-agent example that prints recorded incidents.

The existing 31-table schema supports this slice unchanged. Original specification
documents, SQL and OpenAPI remain untouched and their frozen copies still match.
See [the decision record](decisions/0002-detection.md) for definitions and choices.

## Verification executed

| Check | Actual result |
| --- | --- |
| `make check` with workspace uv executable | **65 passed**, Ruff lint/format passed, mypy passed for 18 source files |
| Added coverage | 24 detector cases plus one foundation regression; all 40 original tests retained |
| Negative controls | Single human wait, transitive human blockers, distinct approval scopes, independent retry lineages, message/span loops, unrelated branches, cross-run evidence and untrusted incident claims |
| Lifecycle/failure checks | Recurrence, retained evidence, suppression/acknowledgement preservation, policy replacement, restart, backward clocks, atomic rollback, degraded health/recovery and quiet timer detection |
| Real `make server` + `make demo SEED=7` | Six agents/tasks, five explicit dependencies, seven spans; three open incidents read back by the CLI; no SDK telemetry degradation; exporter flush completed |
| Real authenticated API readback | Evidence present for all three findings; no stall/dependency-cycle false positive; two completed tasks and four human waits; no control eligibility |
| Window expiration | All three recorded signatures later resolved without approving the still-pending gate or changing waiting tasks |
| Offline source/wheel builds | SDK and server 0.2.0 built successfully |
| Wheel smoke check outside checkout | Detector modules, frozen migration and policy initialization work; all 31 tables present, policy auto-application disabled |

One upstream Starlette/HTTPX TestClient deprecation warning remains. No test failure
or Phase 2 runtime blocker remains. Local execution used Python 3.12.3 and uv
0.13.6. CI on Python 3.11/3.12 is configured but was not run remotely.

The real smoke-test run is `6ce8c0be-57c4-4477-8d48-d76e36fd401d`. Its incidents were:

- `30f7d5d1-008b-5ddd-b574-589e8043dce7`: approval storm.
- `36fadab4-6914-540f-a31f-ad5e4a1d4c7e`: requested retry amplification.
- `af92b3ea-e868-59b5-a384-8b7685c7f7f1`: explicit shared-blocker cascade hypothesis.

The run, source events, incident history and policy snapshot remain in the ignored
local database. The temporary smoke-test backend was stopped. Local credentials
were preserved and never printed. These are engineering demo results, not research
comparisons, evidence of malicious agents, or confirmed runtime interventions.

## Files added or changed

Added:

- `packages/server/src/swarmcircuit_server/detectors/{__init__.py,rules.py,service.py}`.
- `tests/test_detectors.py`.
- `docs/decisions/0002-detection.md` and this delivery report.

Changed:

- `packages/server/src/swarmcircuit_server/{app.py,config.py,repository.py}` for
  scheduling, configuration, readiness and incident reads/overlays.
- `packages/server/src/swarmcircuit_server/ingest/events.py` for same-time state precedence.
- `packages/sdk/src/swarmcircuit/run.py` for progress signals and SDK version.
- `examples/stalled_dependency.py` for a recent live clock and API incident readback.
- `tests/test_foundation.py` for the timestamp regression test.
- Root/package `pyproject.toml` files and `uv.lock` for version 0.2.0.
- `.env.example`, `README.md`, and `docs/provenance/PREEXISTING_WORK.md`.

## Run and inspect

```bash
make bootstrap
make init-local
make db-init
make server
# In a second terminal:
make demo SEED=7
make check
```

The example prints incident IDs/kinds/states. Use the SDK or operator credential
to query `/api/v1/runs/{run_id}/incidents`. Read `current_evidence_event_ids` for
the current/last triggering set, `evidence_event_ids` for accumulated history, and
`resolution_reason` when a signature has expired. Endpoint examples and settings
are in the README and `.env.example`.

## Remaining scope and next task

The incident API is read-only. Acknowledge/suppress writes remain deferred per
App Flow until a separate audited API is designed. Plain OTLP reports do not
establish business dependencies or independent external truth. Missing progress
can also reflect telemetry loss/disconnection. The local scanner reads retained
SDK evidence per run; high-volume incremental processing, retention and historical
backfill are future work. Thresholds have not been validated by comparative research.

Next is Phase 3: scoped runtime/session capabilities, fencing epochs, cooperative
checkpoints, idempotent command submission/dispatch, durable command readback,
validated ACKs and explicit uncertain outcomes. Only after those safety tests
pass should dependency-aware Causal Backpressure request supported holds/resumes.
No command may approve ASK, override DENY, or replay an uncertain payment.
