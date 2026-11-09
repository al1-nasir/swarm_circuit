# Phase 2 detection decisions

November 2, 2026. Implements backlog SC-014/015 and the observation-only incident
path from TRD section 5 and the App Flow. The original SQL/OpenAPI remain unchanged.

## Evidence and authority

Five deterministic rules consume authenticated SDK lifecycle observations:
approval storm, requested retry amplification, missing progress, suspected task
dependency cycle, and retry cascade through an explicit shared blocker.
OTLP self-reports and detector-derived events never become trusted lifecycle
evidence. Graph projections are not input to these rules. Dependency evidence
must be a same-run SDK `task.dependency_added` event matching the canonical edge.
An SDK observation remains a host report, not proof of an external effect.

The processor uses the existing `incidents`, `incident_evidence`, `run_events`,
`ui_outbox` and `control_policies` tables. No migration or new API authority is
needed. Detector policies are stored with `policy_kind=detection`, `auto_apply=0`,
immutable configuration snapshots and SHA-256 identities. The internal derived
source uses `source_kind=collector` because the approved enum has no detector
kind. Its events are always `trust_class=derived`, never runtime ACKs or receipts.

## Operational definitions

- Approval storm: at least **three duplicate requests**, meaning four total SDK
  requests for one pending canonical approval within 30 seconds. Separate scopes
  remain separate approval IDs; a single pending approval never triggers a storm.
  The measure is requests observed, not notifications actually delivered to humans.
- Retry amplification: requested retries / distinct `(task_id, retry_of)` lineages
  in 60 seconds, strictly greater than 1.0. Each lineage implies one initial
  logical action; executed attempts are not established. Ordinal attempt numbers
  are not used as counts. Window inclusion is `(as_of - window, as_of]`.
- Stall: an active running/ready/recovering task lacks a qualifying SDK start or
  `task.progress` signal for 60 seconds, and any explicit absolute deadline has
  also passed. The trigger is `max(deadline, last_progress + timeout)`. Created,
  held, terminal and human-waiting tasks are excluded. Explicit transitive
  dependents of human-waiting tasks are excluded too. Retries, messages, spans
  and arbitrary event names do not count as progress. Missing telemetry can also
  explain the signal, so it is never labeled proven runtime failure.
- Dependency cycle: a strongly connected component among unfinished tasks linked
  by explicit `depends_on`/`waits_for` evidence. Completed/failed/cancelled/held
  and human-waiting tasks are excluded. Message loops, span loops, inferred edges
  and cross-run evidence do not establish a cycle. This is suspected circular
  dependency, not a verified deadlock or malicious behavior.
- Cascade: at least two retrying tasks exceed the same retry ratio within the
  explicit reverse dependency closure of one pending approval's related task.
  Evidence includes the original request, retry requests and paths to the root.
  Shared labels or shared approval IDs without dependency paths are insufficient.
  This supports a causal hypothesis; it does not establish independently verified
  causation. General semantic duplicate delegation/failure propagation is deferred.

## Lifecycle and durability

Ingestion commits first. A subsequent serialized transaction reconciles incidents,
source evidence links, append-only derived lifecycle events and outbox entries.
Detector failure cannot turn a durable source commit into a rejected ingest.
The server logs the failure, reports degraded health, and retries through the
periodic scanner. A successful complete scan restores healthy status.

The default one-second scanner detects elapsed deadlines and window expiration
without further ingestion and re-evaluates persisted runs after restart. It pages
run IDs and writes one run per transaction. It stops before the DB closes. An
interval of zero disables only periodic scanning, useful for deterministic tests;
post-ingestion evaluation remains enabled.

Incidents open, update when evidence/metrics change, resolve when the signature
is no longer observed, and reopen under the same stable identity if it returns.
Source evidence accumulates for history; `current_evidence_event_ids` identifies
the latest triggering set. Repeated unchanged scans emit no new audit/outbox rows.
Resolution may mean window expiration or a policy replacement; it never means
an approval was granted, a payment settled, or a task independently succeeded.
Backward evaluation clocks cannot overwrite a later persisted incident revision.

Acknowledged findings remain acknowledged while active; suppressed findings stay
suppressed. App Flow explicitly defers acknowledge/suppress UI actions and the
target OpenAPI supplies no mutation route, so this phase adds no public state
mutation endpoint. Those states are preserved for later audited operator flows.

`GET /api/v1/runs/{run_id}/incidents` is scoped/read-only and returns evidence,
metrics, policy version, uncertainty and `can_control=false`. Run summaries expose
open incident counts; task graphs expose incident IDs. Detector findings do not
overwrite observed task/run states. SDK-sent incident/control/payment claims
cannot mutate incidents or privileged state.

## Time and example behavior

The service evaluates occurrence timestamps against its current UTC clock, with
an injectable clock only in Python tests/internal services. No endpoint accepts
an agent-provided evaluation clock. Late traces/events retain their original
timestamps; old storm activity does not count as current activity. This is not a
historical incident backfill service or a historical state reconstruction API.

The deterministic scenario function retains a fixed default logical origin for
tests. The CLI uses a recent UTC origin with the same seeded relative schedule,
so live rolling windows can detect its actual emitted activity. Neither mode is
a scientific evaluation. Span durations remain real transport/execution timings.

Tests exposed same-millisecond task transitions previously ordered by UUID. The
projector now gives human-wait/terminal transitions explicit precedence over a
same-time start; random UUID order cannot discard completion. Terminal task states
remain absorbing. Contradictory terminal reports are retained as evidence rather
than treated as externally verified truth.

## Limitations and next boundary

This local MVP scans retained SDK evidence in memory per run; high-volume history,
retention, incremental detector checkpoints, and historical backfill need later
work. The one-worker SQLite limit still applies. Thresholds are versioned starting
values, not empirically validated universal settings. Phase 3 must supply fenced
sessions, capability checks, cooperative execution boundaries and trusted ACKs
before any runtime intervention. No comparison or benefit over baseline policies
is claimed by these engineering tests.
