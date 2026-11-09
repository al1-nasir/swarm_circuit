# Coordination policy evaluation

Protocol: `coordination-cascades-v1`, prepared November 5, 2026, before the sprint.
All reported effects are simulated. SDK group-control browser checks are separate
engineering evidence. Nothing here establishes adversarial containment or real
payment safety.

## Reproduce

```bash
make bootstrap
make init-local
make server PORT=18005
# Another terminal:
make research  # 30 matched seeds × 9 scenarios × 8 policies = 2160 trials
# Printed artifact directory contains the experiment UUID.
make research-verify EXPERIMENT_DIR=artifacts/research/<experiment-uuid>
```

Runner options: `python -m swarmcircuit_server.research.cli run --help`.
`--experiment-id` resumes the same sealed identity idempotently when the protocol
and source fingerprint match. A changed sealed trial is rejected, never replaced.
An interrupted import shows missing trials until resumed. Offline verification
makes no provider calls and checks deterministic replay, reducer metrics, every
CSV row and artifact checksums. The source SHA is a file fingerprint, not a Git
commit. Root and packaged migration 005 must match.

For optional live workload collection, configure `SWARM_MODEL_BASE_URL`,
`SWARM_MODEL_NAME`, and `SWARM_MODEL_API_KEY` privately in root `.env`, then:

```bash
make research-llm  # explicit scenario, one seed, 30 total model calls maximum
```

Never put credentials in a report, terminal recording or source archive. No paid
call can be launched from Studio. Provider errors produce failed trials without
numeric outcomes. Recorded proposal tapes replay open-loop across all policies;
this is not a closed-loop multi-agent benchmark. Five LLM actors share a fixed
planning node. Only synthetic metadata is sent; no real tools are connected.

## Protocol

Six tasks form a declared DAG: plan → access → {research, validate} → report;
public depends only on plan. Planning begins complete. Every arm shares identical
seeded world inputs, approval guards, task durations and business-effect guards.
The simulator writes an independent truth journal and a separate delivered
observation journal. Policies see only observations. Research projections are
Observe runs, and carry no invented human approval or runtime ACK.

| Policy | Intervention |
| --- | --- |
| B0 | Safety guards only |
| B1 | Three attempts per actor per observed gate version |
| B2 | Two tool requests per tick globally |
| B3 | Exact-key request deduplication |
| B4 | B3 plus dependency backpressure |
| B4_no_graph | Root-only ablation |
| B5 | Exponential backoff, capped at 16 ticks |
| A_ready_queue | Dependency-ready queue plus deduplication |

Scenarios: normal, legitimate wait, retry cascade, approval pending, approval
denied, seven-tick delayed telemetry, lost approval update, disconnected host
(ticks 5–25), and an incorrect dependency edge. The last adds public→access to
the observed graph and delays public proposals until tick 12 in every arm so the
fault is exercised. The horizon is 60 logical ticks; gate delay is seeded 18–27,
legitimate wait is 8, normal is immediate. Exact parameters are in the manifest.

B4 parks after three pending demands and releases on the delivered approval
update. Its closure uses the production detector's `reverse_closure`. This is a
model of an automatic policy. Production application still requires operator
review, eligible SDK boundaries, exact-preview validation and runtime ACKs;
production resume is explicit. Do not equate simulated policy performance with
measured operator response time.

## Outcomes and uncertainty

Observed gate changes reset retry counters, backoff and dedup caches; observed
prerequisite completion invalidates dependent cached blocks. The request metric
counts policy-admitted proposals, excluding suppressed actor wakeups.

Twelve metrics include coordination requests, guard checks, blocked checks,
notifications, permitted completion, independent-branch completion/latency,
oracle-ready held task-ticks, unsafe starts, duplicate effects, control intents
and modeled work. Work units use fixed weights 1 request + 3 checks + 10 notices;
they are not dollars, token prices, wall time or production throughput.

Permitted completion counts five goals if the gate is approved by the horizon,
otherwise public only. Incomplete independent latency is censored at the horizon;
inspect its completion indicator alongside latency. False-hold ticks mean ready
by simulator truth but parked: under missing telemetry this can reflect a
conservative fail-closed response. Safety guards enforce zero unsafe starts by
construction. That is an invariant check, not an empirical risk estimate.

Means and 95% percentile-bootstrap intervals use 1000 resamples across seeds.
Contrasts are paired arm-minus-B3 on the intersection of seeds, never unpaired
missing data. One-seed intervals are unavailable. Failures are excluded and shown
explicitly. Comparisons are exploratory with no multiplicity adjustment.
A ready queue and adverse telemetry/graph cases are retained even when unfavorable
to backpressure. Read the raw observations as well as aggregate charts.

Studio `/experiments` supports Comparison, Trials and Protocol tabs, CSV and raw
journal downloads. Research runs are separate from ordinary workflow listings.
For the preparation report and engineering checks, see
[Phase 6 delivery](../docs/PHASE6_DELIVERY.md).
