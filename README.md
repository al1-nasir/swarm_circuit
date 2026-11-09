# SwarmCircuit

Follow how agents hand work to each other, compare their outputs with the source,
and review shared waits. SwarmCircuit connects to an existing Python workflow with
a live map, readable progress and cooperative pause/resume at SDK checkpoints.

Start with **Overview → Explore the guided demo**. The local sales-brief example
shows public findings finishing independently, a protected sample dataset waiting
for your decision, and a downloadable brief after access is granted. Denying
access keeps protected work blocked. The default offline walkthrough uses local
fixtures and actual SDK workers with no model calls. Optional **Live writer and
reviewer** mode adds an actual draft, a separate model review, and at most one
repair using that feedback. Typed facts must match independently computed sample
data before publication. Neither mode makes payments or changes production permissions.

Live mode is reviewed explicitly before starting and permits at most three model
calls. Configure `SWARM_MODEL_BASE_URL`, `SWARM_MODEL_NAME` and
`SWARM_MODEL_API_KEY` privately in `.env`; keys stay server-side. Only the bundled
sample facts and agent draft/feedback are sent. Drafts, failed checks and provider
failures remain visible; a failed live run never substitutes an offline brief.
Writer and reviewer use the same configured provider, and arbitrary model
rationale is retained as unverified evidence. This is a small closed-loop case,
not a general safety or cost-saving result.

See [live agent handoffs](docs/LIVE_HANDOFFS_2026-11-08.md) for the current demo
flow, retained evidence, provider setup and validation boundaries.

**Prior work and event contribution.** The SDK, telemetry/control foundations,
original offline example and November 5 synthetic study are pre-existing
preparation. The event-period contribution is the clearer workflow, bounded live
writer/reviewer handoff, retained original feedback, independent source checks
and failure handling documented above. The 2,160 old synthetic trials and failed
model pilots are retained as historical evidence, not presented as new event
results. Final release checks and submission preparation continued on November 9
before the AoE deadline.

The workspace separates connected control hosts from historical workflow status.
Diagnostics are hidden by default, pause history loads without browser storage,
and stored comparison results persist across backend restarts. Technical evidence
and the existing graph/timeline views remain available when you need them.

## Run locally

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/). Dependencies are locked
in `uv.lock`; development was verified on Python 3.12.3 using uv 0.13.6.

```bash
make bootstrap
make init-local
make db-init
make server
```

In another terminal, from this repository:

```bash
make demo SEED=7
```

The server binds to `127.0.0.1:8000` with one worker. `make init-local` creates a
mode-0600 `.env` containing distinct random SDK and operator tokens, and preserves
any existing file. Neither token is printed. Uvicorn loads `.env`; the example
loads it separately. Settings are described in `.env.example`.

If port 8000 is occupied, use `make server PORT=18003` and run examples with
`SWARM_API_URL=http://127.0.0.1:18003 make demo-control` (or `make demo SEED=7`).

The example prints its recorded run ID and the incidents returned by the API.
It uses six plain Python agents, a seeded relative schedule and retry counts.
The CLI anchors its logical clock to recent UTC time for live detector windows;
the scenario function retains a fixed origin for tests. The graph has five explicit
dependencies. One shared **mock** approval remains pending, four tasks wait past
their declared deadlines, and an independent public-research task completes.
Phase 2 detects approval-request/retry amplification and the explicit shared
dependency cascade. Ordinary human waiting is excluded from stall detection.
This original example makes no payments or LLM calls. Comparative research is a
separate Phase 6 runner, not inferred from this demonstration. Span timings reflect actual
execution; UUIDs and transport timings are not deterministic experiment outputs.

## Local Studio

Requires Node.js 22.18+ (verified on Node 22.23.4) and npm. Start the backend above,
then open the Studio in another terminal:

```bash
make studio-install
make studio
# Open http://127.0.0.1:3000
# Interactive mock checkpoint for the UI hold/resume flow:
make demo-studio
```

For an alternate backend: `SWARM_API_URL=http://127.0.0.1:18005 make studio STUDIO_PORT=3300`.
The custom Node server reads root `.env` privately. Credentials never enter the
browser bundle. Set `SWARM_STUDIO_READ_ONLY=true` to disable operator submission.
This is a trusted local workspace, not a multi-user authentication service.

The Studio includes paginated workflows, task/agent graphs with a click-based list,
virtual timeline, source-linked incidents, payment/approval provenance and durable
control history. Hold/resume requires a live eligible SDK checkpoint, a review
with a reason, backend validation and a matching runtime ACK. Payment and approval
views are read-only. Live reconnects preserve selection and refetch canonical
snapshots. Experiments now expose matched-policy results, raw evidence and CSV exports;
see [research reproduction](experiments/README.md).

See the [workspace improvement report](docs/WORKSPACE_IMPROVEMENTS_2026-11-06.md)
for the guided workflow, dashboard changes and latest checks. The earlier
[dashboard refinement report](docs/STUDIO_REFINEMENT.md) documents the two-tone visual system.
The [judge walkthrough](docs/JUDGE_WALKTHROUGH_2026-11-06.md) gives a focused demo
script and current event requirements; the [reviewer repair pass](docs/REVIEWER_PASS_2026-11-06.md)
records the subsequent lifecycle and recovery fixes.

```bash
make studio-check  # Formatting, TypeScript, eighteen unit cases, production build
# After building, with the backend running:
npm --prefix apps/studio start
```

See [Studio setup](apps/studio/README.md), [Phase 5 delivery](docs/PHASE5_DELIVERY.md)
and the [architecture decision](docs/decisions/0005-studio.md).

## Inspect recorded evidence

Open [interactive API docs](http://127.0.0.1:8000/docs) to see implemented routes.
For authenticated queries, load the local token and use the run ID printed above:

```bash
set -a
. ./.env
set +a
curl -s http://127.0.0.1:8000/api/v1/health
curl -s -H "Authorization: Bearer $SWARM_OPERATOR_TOKEN" \
  "http://127.0.0.1:8000/api/v1/projects/$SWARM_PROJECT_ID/runs"
# Set RUN_ID to the demo's printed run_id.
curl -s -H "Authorization: Bearer $SWARM_OPERATOR_TOKEN" \
  "http://127.0.0.1:8000/api/v1/runs/$RUN_ID/graph?view=task"
curl -s -H "Authorization: Bearer $SWARM_OPERATOR_TOKEN" \
  "http://127.0.0.1:8000/api/v1/runs/$RUN_ID/timeline?limit=100"
curl -s -H "Authorization: Bearer $SWARM_OPERATOR_TOKEN" \
  "http://127.0.0.1:8000/api/v1/runs/$RUN_ID/incidents"
```

Implemented routes:

| Endpoint | Behavior |
| --- | --- |
| `GET /api/v1/health` | Database/schema/writer readiness |
| `POST /api/v1/projects/{project_id}/runs` | SDK creates an Observe or Control run |
| `GET /api/v1/projects/{project_id}/runs` | Cursor-paginated run summaries |
| `GET /api/v1/runs/{run_id}` | Project-scoped observed run state |
| `POST /api/v1/runs/{run_id}/events` | Lifecycle batch, ≤250 events, dedup counts |
| `POST /v1/traces` | OTLP/HTTP binary protobuf or JSON, optional gzip |
| `GET /api/v1/runs/{run_id}/graph?view=task\|agent` | Versioned explicit graph |
| `GET /api/v1/runs/{run_id}/timeline` | Cursor-paginated sanitized events/spans |
| `GET /api/v1/runs/{run_id}/incidents` | Persisted findings, source evidence, policy and uncertainty |

Read routes accept SDK/operator credentials. Ingestion and run creation require
the SDK token. Runs in another project return 404. Control runs remain observation
only until a trusted host enters a supported SDK boundary. Operator credentials
submit controls; separate runtime credentials dispatch and acknowledge them.
The frozen target contract includes later-phase routes that are not implemented.

## Detection and incident lifecycle

The backend evaluates SDK observations after committed lifecycle batches and on
a one-second timer. It detects repeated requests for the same pending approval,
requested retry amplification, active tasks missing progress, suspected circular
task dependencies, and retry cascades linked by explicit dependency paths.
OTLP self-reports, span ancestry and message loops never establish those paths.

Default rules and their precise definitions are recorded in
[the detection decision](docs/decisions/0002-detection.md). Approval storms require
three duplicates (four requests) in 30 seconds. Requested retry amplification is
retries / distinct `(task_id, retry_of)` lineages over 60 seconds, strictly above
1.0. Missing progress requires 60 seconds without a host start/progress signal
and expiration of any declared deadline. Human waits, their explicit dependents,
held tasks and terminal tasks are excluded from stall detection.

Call `task.record_progress()` at meaningful host progress boundaries. Retries,
arbitrary messages and trace spans do not reset the stall timer. A progress signal
remains a host observation, not independent proof of an external effect.

Findings carry source event IDs, affected task IDs, observed metrics, denominators,
policy version/hash and uncertainty. Incidents open/update, resolve when a signal
expires or disappears, and reopen under the same identity if it returns. Historical
evidence is retained. Resolution means the signature is no longer observed; it
does not establish task success, approval or settlement. Read the resolution reason.

Incident evidence, append-only derived lifecycle events and outbox records commit
atomically. If detection fails, source ingestion remains committed; health becomes
degraded and the timer retries. Repeated unchanged scans produce no duplicate
lifecycle records. Saved runs are re-evaluated after restart. Detector configuration
is versioned in the existing policy table with auto-application disabled.

Configure thresholds through the `SWARM_*` detector settings in `.env.example`.
`SWARM_DETECTOR_INTERVAL_SECONDS=0` disables only the timer. There are no public
acknowledge/suppress mutation routes in this phase. Run summaries expose
`open_incident_count`; task graphs expose linked `incident_ids`. Observed task/run
states stay separate from derived diagnoses. Graphs expose current checkpoint
eligibility and its reason; incidents expose advisory `can_control` flags.
Every control write revalidates eligibility.

## Cooperative runtime control

```bash
# With make server running:
make demo-control
```

This example uses mock reversible work. It waits for a physically parked SDK
checkpoint and a matching runtime ACK, completes an independent branch, then
resumes the protected branch and executes its mock action once. It prints durable
command IDs and states. There are no payments or real approval decisions.

Opt in explicitly when integrating your own host:

```python
with sc.run("controlled-work", mode="control") as run:
    work = run.task("read public data", agent="reader")
    with run.runtime("my-host") as runtime:
        with work:
            runtime.checkpoint(work, action="before_public_read", timeout=60)
            # Execute your reversible host action only after checkpoint returns.
```

A checkpoint releases when prerequisites are safe and no hold is pending. A
pending approval or explicit unfinished prerequisite keeps it open. Operators can
hold only a currently active, owned checkpoint; commands cannot interrupt work
that already passed one. Catching `ControlError` must stop the protected action.
Use `reversible=False` to explicitly reject an unsupported irreversible boundary.
Host integration remains responsible for honest runtime ACKs and placing hooks
before work; this is cooperative control, not process isolation.

Control routes are documented in the additive
[implemented protocol](contracts/control-v1.openapi.yaml) and
[control decision](docs/decisions/0003-control.md):

| Endpoint | Authority and behavior |
| --- | --- |
| `POST /api/v1/runs/{run_id}/runtime-sessions` | SDK registration; session token returned here only |
| `GET /api/v1/runs/{run_id}/runtime-sessions` | SDK/operator sanitized session and checkpoint state |
| `POST /api/v1/runtime-sessions/{session_id}/heartbeat` | Runtime lease heartbeat |
| `GET /api/v1/runtime-sessions/{session_id}/commands?wait_ms=0` | Runtime dispatch/redelivery; bounded long poll also supported |
| `POST /api/v1/runtime-sessions/{session_id}/checkpoints` | Runtime enters reversible boundary with stable key |
| `GET /api/v1/runtime-sessions/{session_id}/checkpoints/{checkpoint_id}` | Runtime checks its own boundary |
| `POST /api/v1/runtime-sessions/{session_id}/checkpoints/{checkpoint_id}/leave` | Runtime atomic release handshake |
| `POST /api/v1/runs/{run_id}/control-commands` | Operator enqueues hold/resume with task version and `Idempotency-Key` |
| `GET /api/v1/control-commands/{command_id}` | SDK/operator canonical outcome and sanitized ACKs |
| `POST /api/v1/control-commands/{command_id}/ack` | Matching live runtime, epoch and stable ACK key only |
| `POST /api/v1/runs/{run_id}/backpressure` | Operator preview or bounded explicit policy application |
| `POST /api/v1/runtime-sessions/{session_id}/approval-presentations` | Runtime claims one pending notification |
| `POST /api/v1/runtime-sessions/{session_id}/approval-presentations/{presentation_id}/result` | Runtime records presented/unknown notification outcome |

Command submission requires `command_kind`, `runtime_session_id`, `task_id`,
`expected_task_version` from the graph, and `reason`. Only `hold_task` and
`resume_task` capabilities are supported. `queued` and `dispatched` do not establish
effect; only the validated runtime ACK can record `applied`. A queued timeout
becomes `timed_out`; a dispatched timeout becomes `unknown`. Duplicate keys
reconcile one effect; changed payloads reject.

Causal Backpressure previews the explicit dependency closure of a pending
`approval_id`. Send `{"approval_id": "<uuid>", "reason": "shared gate"}` to preview;
add `"apply": true` to request bounded hold commands. Use the operator token and
an `Idempotency-Key`. Independent branches are excluded. Policy version, bound,
targets, skipped reasons and child command IDs are retained with the application
request. The response's `applied: false` describes the policy request itself;
inspect each child's durable state for runtime effects. Auto-application and
auto-resume are disabled.

`runtime.present_approval_once(task, full_scope, presenter)` optionally coalesces
notification callbacks for the same complete approval scope. It preserves original
request evidence and never resolves the approval. An uncertain callback is not
retried. Emit approval requests before entering the task's checkpoint. Historical
request storms can still be detected even when notifications are coalesced.

Sessions expire on heartbeat loss (default 15 seconds) or absolute token TTL
(default 30 minutes). Commands have a 30-second deadline; the policy bound is 20
eligible targets. Settings are in `.env.example`. Keep the SDK heartbeat interval
below your lease. Server restart invalidates old sessions and active boundaries;
new epochs cannot adopt held/unknown boundaries. Stop affected work and reconcile
outside this protocol. SDK callback/command caches are in memory; there is no
cross-process execution journal or exactly-once guarantee. A runtime's historical
ACK remains historical evidence after disconnect, not proof it is still parked.

Resume/leave cannot bypass pending, denied or unverified approvals, unresolved
prerequisites, DENY payment decisions, or submitted/uncertain payments. A simulated
ASK becomes eligible only after its exact separately authenticated broker approval.
Live ASK remains blocked pending a real authority connector. No control command
resolves an approval or retries a payment.

## Optional GateKeep402 evidence and mock approval flow

The SDK's `payments` extra pins GateKeep402 0.2.1 and openlibx402 core/client
0.1.1. The base SDK and server do not require these packages. `make bootstrap`
installs all extras for native integration tests; standalone SDK users can install
`swarmcircuit-sdk[payments]` when this repository's package is available to them.
GateKeep402 remains unchanged and owns its SourceGuard, trust policy, native ASK
callback, signing integration, delivery checks and private ledger.

```bash
make init-local
make init-mock                 # Separate mode-0600 .env.mock; preserves .env
make server-mock PORT=18004    # Explicitly enable simulation-only callbacks
# In another terminal:
SWARM_API_URL=http://127.0.0.1:18004 make demo-payment
```

The demo uses the actual GateKeep402 package over an in-memory mock payment
transport. It creates no wallet, keypair, signature or blockchain RPC. A legitimate
ASK produces a pending approval; Causal Backpressure holds its root and dependent,
while independent work completes. A separate broker credential approves the exact
scope. Explicit runtime resumes then permit one mock payment. Successful structural
delivery leaves settlement `unknown` until the broker supplies a unique mock
receipt. Only after root completion does the dependent resume and execute once.
A separate DENY commits zero mock effects. These are engineering checks, not
research comparisons or live payment results.

For an existing host integration:

```python
from swarmcircuit.adapters.gatekeep402 import GateKeep402Observer

observer = GateKeep402Observer(
    task,
    action_key="one-logical-purchase",
    principal="trusted-host",
    purpose="research",
    asset_code="USDC",
)
client = observer.client(
    existing_openlib_client,
    ledger=existing_gatekeep_ledger,
    gate=existing_gate,
    on_ask=existing_native_approval_callback,
)
# Use this real GateKeep402 client through the host's normal async flow.
# The connector calls observer.submitted() at its actual effect boundary.
```

The observer returns native decisions/results unchanged. Notification/telemetry
failure cannot turn DENY into ALLOW. It records host observations, not independent
payment authorization. The supplied callback remains authoritative for the native
library. For real payments, no SwarmCircuit approval/settlement connector is
implemented yet; the simulation broker cannot authorize a non-simulation run.
The SDK's control `reversible=False` boundary remains unsupported for payments.
Do not treat observation hooks as a wallet budget, task mandate or external-effect
firewall. The mock transport's deduplication belongs to that separate simulator.

| Endpoint | Authority and behavior |
| --- | --- |
| `GET /api/v1/runs/{run_id}/approvals` | SDK/operator reads groups, request counts and resolution provenance |
| `GET /api/v1/runs/{run_id}/payments` | SDK/operator reads normalized gates, attempts, receipt trust and structural delivery checks |
| `POST /api/v1/mock/runs/{run_id}/approvals/{approval_id}/resolution` | Separate mock broker; exact fingerprint; explicit simulation run only |
| `POST /api/v1/mock/runs/{run_id}/payment-attempts/{attempt_id}/settlement` | Separate mock broker; exact scope and unique mock receipt; existing authorized simulation effect only |

Reads accept `limit` (default 50, maximum 200) and `cursor`; nested payment lists
are capped at 100, with total gate count and `has_deny` exposing older blockers.
Create runs with `simulation=True` in the SDK, or `simulation: true` in REST, only
for mock workflows. Normal runs default to false. The mock broker is disabled
unless explicitly configured; SDK, operator and runtime tokens cannot invoke it.

Approval callbacks require `action_fingerprint` and `decision` (`approved` or
`denied`). Settlement callbacks require `scope_fingerprint` and a unique
`receipt_reference` beginning with `mock:`. Both require `Idempotency-Key` and
the independent broker token. Exact replay returns one durable result; a changed
payload, terminal decision, reused receipt, DENY or retroactive approval rejects.
Callbacks never submit or replay payments and never auto-resume tasks.

Gate, submission and delivery events remain `sdk_observation`. Mock callback
events carry `simulation_truth`; mock confirmed attempts use the schema's
`simulator_truth` receipt label. An SDK message saying settled cannot set either.
Amounts remain exact decimal strings. Full headers, signed payloads, wallet data,
raw response/error text and URL queries are omitted. The observer reports
`telemetry_degraded`; the SDK's existing loss indicators still apply.

Unconfirmed settlement and failed structural delivery create separate evidence-
linked `policy_warning` incidents. A receipt resolves settlement uncertainty but
does not erase a delivery failure or undo payment. ASK/DENY alone are expected
safety behavior. External registry signals are not represented as verified live
on-chain reputation; structural checks do not establish semantic content truth.

See the [Phase 4 decision](docs/decisions/0004-payment-evidence.md),
[implemented payment contract](contracts/payments-v1.openapi.yaml) and
[delivery report](docs/PHASE4_DELIVERY.md) for safety boundaries and executed checks.

## Use the SDK

The base SDK package depends only on HTTPX and the OTel API. Install its `otel` extra
when configuring an exporter yourself. It accepts your existing tracer without
replacing the global OTel provider. The optional helper creates an
application-owned provider; callers must flush/shut it down.

```python
import os
from dotenv import load_dotenv
from swarmcircuit import SwarmCircuit
from swarmcircuit.instrumentation import create_otlp_provider

load_dotenv(".env")
token = os.environ["SWARM_SDK_PROJECT_TOKEN"]
provider = create_otlp_provider("http://127.0.0.1:8000", token)
try:
    with SwarmCircuit(
        os.environ["SWARM_PROJECT_ID"], token, tracer=provider.get_tracer("my-app")
    ) as sc:
        with sc.run("research") as run:
            collect = run.task("collect", agent="researcher")
            review = run.task("review", agent="validator")
            review.depends_on(collect)
            with collect:
                pass  # Run your own application code here.
            with review:
                pass
    provider.force_flush()
finally:
    provider.shutdown()
```

Contexts record host-observed starts/completions/failures. `wait_for_approval()`
records pending requests and suppresses automatic task completion; it grants no
authorization. `trace_headers()` exports W3C context for host-managed handoffs.
Explicit dependencies and handoffs use same-run IDs. Ordinary span ancestry and
links never become blocking dependencies.

Lifecycle transport retries preserve event IDs/keys with bounded backoff and
jitter. A lost response after commit deduplicates on retry. Unsent events remain
in a bounded **in-memory** queue; `telemetry_degraded`, `dropped_events`, and
`flush()` disclose loss/outages. Callers should retain/check this state. Initial
run creation requires the service; pending telemetry does not survive process
exit. OTel uses its own bounded exporter queue. No global exactly-once execution
guarantee is claimed.

## Evidence and persistence guarantees

- The original 31-table SQL is copied unchanged, digest-checked and applied
  atomically with its migration marker. Additive migration 002 adds six control
  context tables; migration 003 adds two payment-authority context tables and
  migration 004 adds two durable stream-index tables; migration 005 adds sealed research artifacts; migration 006 adds managed
  walkthroughs and a persistent results cache; migration 007 adds bounded live
  handoff receipts (50 tables, including SQLite metadata). Existing data and
  constraints are preserved. Every connection enables foreign keys
  and a 5-second busy timeout; the DB uses WAL.
- A bounded writer thread serializes writes. Ingestion success follows commit;
  queue pressure or database failure returns 503. A timeout is an uncertain
  commit outcome, reconciled with the same source keys.
- Stable lifecycle keys and span identities have one stored effect. Conflicting
  replays reject without overwriting evidence. Each rejected record rolls back
  its domain changes; valid records in a batch can still commit.
- OTLP uses official generated protobuf messages, matching response media types,
  numeric enum/hex-ID JSON rules, partial-success counts and protocol Status
  errors. Requests have a default 2 MiB compressed/decompressed limit.
- Nanoseconds remain exact SQLite integers. Timeline JSON exposes nanoseconds as
  decimal strings to avoid JavaScript precision loss. Events retain occurrence
  and ingestion times; ordering uses stable cursor tie-breakers.
- SDK lifecycle observations and untrusted OTLP reports have distinct
  server-assigned evidence classes. Neither proves human authorization,
  settlement or independently verified completion. Unsupported privileged
  lifecycle names remain metadata-only and cannot change those states.
- Unknown attributes/content payloads are dropped by allowlists before storage.
  Names, titles and identifier fields are caller-supplied metadata: do not put
  secrets in them. Full prompts, tool bodies, payment headers and raw content
  are not captured. Raw evidence here means sanitized source evidence.
- Outbox notifications and per-run stream sequences persist transactionally.
  Read-only WebSockets replay invalidations with snapshot recovery on gaps.
  Automated retention remains deferred.

## Layout and verification

```text
packages/sdk/src/swarmcircuit/          telemetry/checkpoint SDK; optional OTel setup
packages/server/src/swarmcircuit_server/
  app.py, repository.py                REST, identity services and read projections
  db/                                  migration runner and bounded writer
  ingest/                              OTLP codecs and lifecycle projector
  detectors/                           deterministic rules and durable incident lifecycle
  controller/, api/control.py           fenced commands, checkpoints and policy
  payments/, api/payments.py            sanitized observations and mock authority
migrations/, contracts/                frozen originals and additive control supplement
examples/stalled_dependency.py          seeded six-agent scenario
examples/cooperative_control.py         real HTTP mock hold/resume
examples/payment_visibility.py          native GateKeep402 with simulated effects
tests/                                 schema, API, SDK, OTLP and failure tests
docs/decisions/                         specification reconciliation and plan
docs/provenance/                        pre-event and prior-work inventory
apps/studio/                           local Next.js Studio and credential gateway
experiments/                           Matched-policy evaluation protocol
```

```bash
make check                  # Ruff check/format, mypy, pytest
make demo SEED=7             # Requires the running backend
make demo-control           # Physically parked cooperative boundary
```

Tests use temporary databases and no external services. They cover binary/JSON
OTLP, gzip bombs, invalid IDs/timestamps, partial rejection, links, redaction,
same-run/project boundaries, append-only evidence, concurrent replay,
out-of-order task state, stable pagination, lost responses, bounded queues,
rollback on disk-write failure, and the SDK-to-query six-agent path.
Phase 2 adds tests for rule thresholds, legitimate human waits, explicit versus
unrelated dependencies, timer detection, incident recurrence, policy replacement,
restart recovery, backward clocks, detector persistence failure, and same-time
lifecycle transitions. No performance or comparative research benefit is inferred.

## Scope and next work

This is a local MVP with cooperative controls. Cancellation, automatic recovery,
production human/payment authority connectors remain unimplemented.

Phase 6 now adds a bounded research runner, evidence exports, experiment views and
reviewed group containment. See [Phase 6 delivery](docs/PHASE6_DELIVERY.md).
Research results measure a synthetic environment, not production effectiveness.

Phase 3 adds tests for authority separation, nonce/command/ACK replay, fencing,
lease/token/deadline expiry, restart uncertainty, physical checkpoint parking,
lost ACK response reconciliation, bounded dependency backpressure, independent
branch progress, approval notification coalescing and approval/payment guards.
See [Phase 3 delivery](docs/PHASE3_DELIVERY.md) for executed checks and limitations.

The supplied contracts remain the full target design. See
`docs/decisions/0001-foundation.md` for conflicts, absent companion files,
payload conventions and phase ordering. The original specification documents
have not been overwritten. This repository does not yet select an open-source
license; resolve the PRD's license decision before public distribution.

Phase 1 work dated November 1 and Phases 2–5 work dated November 2, 2026 are
pre-hackathon preparation. The
[prior-work inventory](docs/provenance/PREEXISTING_WORK.md) separates supplied
assets, this implementation and the optional pre-existing
[GateKeep402](https://github.com/al1-nasir/gatekeep402). No benchmark wins,
live payment integration, or hackathon-period authorship is claimed.
