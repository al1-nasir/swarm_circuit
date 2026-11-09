# Workspace improvements — November 6, 2026

This delivery implements the product review as UI and backend changes. Research
paper work is excluded. The existing two-tone visual direction is retained.

## Start with a useful workflow

Open **Overview → Explore the guided demo**, or `/demo`. The job is concrete:
prepare a quarterly sales brief from public reference notes and a restricted
sample CSV.

1. Start the walkthrough. A managed, bounded Python worker uses the real SDK and
   its task/dependency/checkpoint protocol. All input data is a local fixture.
2. Read the public findings. That branch completes on its own schedule while
   four dependent tasks wait quietly for sample dataset permission.
3. Select **Review sample access**, enter a reason and approve or deny. This
   changes permission only for this walkthrough's mock dataset.
4. Approval allows the guarded branch to calculate and independently validate
   sales growth, then produce a readable, downloadable final brief. Denial keeps
   protected work blocked and retains the public findings.
5. The workflow map remains available for inspection. Optional operator pauses
   still require reviewed scope, current SDK boundaries and matching host ACKs;
   existing pauses require explicit resume even after sample permission is granted.

The useful outputs are public findings, dataset analysis and the final sales
brief. Their content hashes and the separate protected-effect ledger are retained.
A pending permission is normal waiting, not automatically an incident. The demo
records four initial access requests; it does not claim a retry storm or savings
caused by pausing work that the SDK already guards.

This is a deterministic local-fixture workflow, **not a live LLM-team benchmark**.
It makes zero model calls, uses no paid provider, performs no payment and changes
no production permission. Starting another active walkthrough is bounded per
project; original request keys reconcile uncertain outcomes. Expired or
interrupted workers are recorded honestly and require a fresh walkthrough.

## Clearer daily use

- Overview explains the product and offers the guided example before SDK setup.
  Project-wide counts distinguish recorded workflow status from currently
  connected control hosts. Diagnostic runs are hidden by default and remain
  available through an explicit filter; nothing is deleted.
- Workflow briefs summarize completed/total tasks, the declared branch linked to
  pending permission, work outside that branch and the next useful action.
  “Outside the branch” does not independently prove a task is ready to run.
- Current host connectivity is separate from historical pause confirmation.
  A fresh page snapshot does not make an old worker live. Technical IDs, epochs
  and evidence remain inspectable without carrying the main explanation.
- Group pause history is discovered from the server. A fresh browser can inspect
  the same canonical commands without inheriting the original local intent.
  Unconfirmed requests anywhere in the run remain visible to the submission guard.
- Native focus and button behavior remain; no custom navigation shortcuts were
  introduced. The guided output reader and controls were checked at desktop and
  mobile widths during final browser verification.

## Backend changes

Additive migration 006 stores managed walkthrough state, actions, output artifacts,
append-only protected effects and prepared experiment summaries. Demo decisions
are operator-only, idempotent, project-scoped and restricted to owned simulation
runs. They do not expose the general mock-broker mutation surface through Studio.
Downloads allow only known output slugs, with safe Markdown attachment headers.

Workspace/brief/history reads are authenticated and no-store. Liveness uses
heartbeat freshness, credential expiry and fencing. Counts do not silently turn
disconnected historical runs into cancelled or completed work.

Experiment aggregates now persist across restart and prepare after completed
recording. The optimized presentation calculation preserves the original seed
sampling and exact numeric outcomes. A failed optional summary preparation cannot
turn an already sealed trial into a failed write. The original November 5 study
manifests/results remain unchanged; this is a cache and UI improvement, not a new
study. The new SDK dependency changes `uv.lock`, so the current source fingerprint
is expected to differ from that historical study's source fingerprint.

## Run locally

```bash
make bootstrap
make init-local
make server PORT=18005
# Another terminal:
make studio-install
SWARM_API_URL=http://127.0.0.1:18005 make studio STUDIO_PORT=3300
# Open http://127.0.0.1:3300/demo
```

`make server` sets `SWARM_DEMO_API_URL` to its actual loopback port. Direct Uvicorn
startup must set that variable explicitly when using a port other than its
8000 default. The backend accepts only a configured loopback HTTP origin; it never
derives this worker destination from browser headers. Studio's `SWARM_API_URL`
separately configures its own private gateway. Use one backend worker for SQLite.

This remains a trusted single-user local workspace with cooperative host hooks.
It is not a remote multi-user authentication service or a hostile-process sandbox.
Credentials stay server-side. `SWARM_STUDIO_READ_ONLY=true` disables Studio writes,
including walkthrough start and sample-permission decisions.

## Verification and evidence

- Full backend `make check`: Ruff, format, mypy and **163 tests passed**.
- Studio: **13 unit cases**, strict TypeScript and production build passed;
  **5 live HTTP/WebSocket integration checks passed** against the final servers.
- Final actual SDK walkthrough `f70ae6bc-a990-4184-bf73-203eaf743566` completed
  **6/6 tasks**, recorded four approved protected steps and **zero model calls**.
  It remained in legitimate permission wait for over 62 seconds without a stall
  incident before approval. Public findings completed independently.
- The denied walkthrough recorded **zero protected effects**, with public findings
  retained. A four-task pause obtained matching ACKs; the same server-side history
  remained discoverable after clearing only the QA browser's local intent.
- Existing 2,160-trial aggregate values matched the sealed export exactly. The
  local cache check recorded an approximately **32 ms warm read**; the final
  post-restart check recorded approximately **235 ms**. These are individual local checks,
  not a production latency benchmark. Initial preparation can still take seconds.

Screenshots and structured evidence are in
[the verification folder](/home/ali-nasir/PycharmProjects/swarm_circuit/artifacts/web-improvement-2026-11-06).
The final completed state is
[final-live-completed.json](/home/ali-nasir/PycharmProjects/swarm_circuit/artifacts/web-improvement-2026-11-06/final-live-completed.json),
the denied state is
[denied-demo.json](/home/ali-nasir/PycharmProjects/swarm_circuit/artifacts/web-improvement-2026-11-06/denied-demo.json),
and numeric cache equivalence is in
[cache-check.json](/home/ali-nasir/PycharmProjects/swarm_circuit/artifacts/web-improvement-2026-11-06/cache-check.json).
The final service, workflow and test results are recorded in
[verification-summary.json](/home/ali-nasir/PycharmProjects/swarm_circuit/artifacts/web-improvement-2026-11-06/verification-summary.json).
The guided output reader was also inspected at 390, 1024 and 1440 pixels, with no
page-level horizontal overflow. Browser logs contained unused CSS-preload warnings;
no JavaScript exceptions were observed during these checks.

Older delivery reports and research artifacts describe their own historical
checks. They are retained rather than rewritten as evidence for these changes.
