# Live agent handoffs

SwarmCircuit now has an optional live case that follows work between two model
roles. A writer produces a structured draft from sample sales facts. A reviewer
receives that actual draft and recomputed source facts. If the review or source
check finds a problem, the writer receives that feedback for one repair. A final
brief is published only after its supported typed claims pass the source check.

The earlier offline brief was templated. It demonstrated cooperative control,
but not a model-to-model feedback loop. Both modes remain available, with offline
selected by default. Live mode has a separate review showing the configured
provider, the synthetic inputs and a three-call ceiling. Starting a live
walkthrough does not call a model until sample access is granted. Denial performs
zero model calls. Existing operator pauses still require explicit resume.

## What a reviewer can inspect

- The writer's original structured draft and its unverified rationale.
- The separate reviewer's actual verdict and feedback.
- The repaired draft, if one was requested.
- Source-check errors before and after repair, the supported source quantities,
  attempted-call count, provider-reported usage when available, and response hashes.
- The final checked brief, or a failed handoff with its available evidence.

The source-data check is outside the reporting model. It recomputes the bundled
CSV quantities and checks the supported typed facts and limitation labels.
Equivalent finite decimal formatting does not trigger a false mismatch. Arbitrary
model rationale is not certified and is not used as factual final-brief prose.
A repair receives deterministic fact checks without a second model review.

The live graph makes review depend on the writer task; it cannot review a draft
that does not exist yet. Calls execute outside SQLite write transactions. Every
attempt is recorded before provider I/O, with a durable limit of three calls and
no automatic provider retry. Authority, task state, deadline and cancellation are
checked before calls and before outputs are published. Provider failures cannot
silently become successful offline outputs.

## Run it locally

Configure `SWARM_MODEL_BASE_URL`, `SWARM_MODEL_NAME` and `SWARM_MODEL_API_KEY`
privately in root `.env`. Never use `NEXT_PUBLIC_*` for credentials. The provider
must implement the configured HTTPS chat-completions endpoint. The requested
model name and provider-reported identity are recorded, not independently verified.

```bash
make server PORT=18005
# Another terminal:
SWARM_API_URL=http://127.0.0.1:18005 make studio STUDIO_PORT=3300
```

Open `/demo`, choose **Live writer and reviewer**, review the bounded start, then
review sample access. Read the three normal output tabs and expand **Agent
handoff evidence** for draft, feedback, repair and source checks. Returning to the
mode chooser never automatically launches another paid run.

Model messages contain only bundled synthetic facts, public notes and the roles'
draft/feedback. They exclude operator reasons, application credentials and other
workspace content. The provider key is used for HTTPS authentication; it is not
exposed to the browser or retained evidence. Unknown or missing token usage is
shown as unknown, not zero. The original start mode and key are preserved when
the browser must reconcile an uncertain start.

## API and storage

Migration 007 preserves existing fixture walkthroughs and artifacts while adding
execution mode, start-payload binding, call receipts and retained handoff state.
There are seven migrations and fifty tables including SQLite metadata.

- `GET /api/v1/projects/{project_id}/demo-capabilities`: bounded availability
  metadata without credentials.
- `POST /api/v1/projects/{project_id}/demos`: `{}` remains the offline default;
  `{"mode":"live"}` requires the operator role and an idempotency key.
- Existing demo reads now include execution mode, attempted calls, usage and the
  handoff outcome. An existing key cannot be reused for a different mode.
- Existing artifact reads add `agent-draft`, `agent-review`, `agent-repair` and
  `handoff-evidence`. Only known names are available through Studio.

The additive [workspace contract](../contracts/workspace-v1.openapi.yaml) records
these routes. Original supplied specs and historical study results are retained.

## Scope and event fit

The official oversight/control examples ask whether workers' completion claims
match actual state before later workers act. This case makes handoff claims,
review feedback and source checks inspectable in one running workflow.
[Official Track 4 examples](https://apartresearch.com/sprints/swarm-alignment-2026#guidelines).

There are two model roles within six SDK tasks, using the same configured
provider. Tools, data and permission authority remain local fixtures. This is a
small closed-loop case, not a large-swarm benchmark, proof of independent model
judgment, general safety or comparative cost savings. No error is deliberately
forced into a live response. Controlled failures in tests are labelled as injected
provider responses. This delivery does not modify the paper or submit anything
to the event.

## Verified execution and final release checks

The retained live case ran on November 8 in Pakistan (November 7 at 22:17 UTC).
It completed all six SDK tasks with two successful provider requests: one writer
and one reviewer. The reviewer accepted the original draft, and the external CSV
check found no typed-claim errors. No repair was needed. Reported aggregate usage
was 997 input tokens and 304 output tokens. The configured and returned model name
was `DeepSeek-V4-Flash`; the third-party provider's model identity is not
independently authenticated.

Before sample access, this run recorded zero model calls and zero protected
effects. Six downloaded artifacts were checked against their stored SHA-256
values. On November 9, the completed run and both successful call receipts were
verified after restarting the API. No additional provider request was made for
the final release checks.

The final November 9 release passed 208 backend tests, Ruff, formatting and mypy;
18 frontend unit tests, TypeScript, formatting and a production build; and six
gateway integration tests. Injected-response tests cover repair, rejected repair,
failed provider calls, malformed usage, cancellation, expiry and lost authority.
These are implementation checks, separate from the single actual provider case.

A fresh offline browser run ended in denied access with zero model calls and
zero protected effects while preserving public findings. Returning to the chooser
immediately showed its terminal state without manual refresh. The accepted-status
cache and navigation refresh were corrected to prevent a saved run appearing
active. The evidence reader and desktop/narrow-screen layouts were checked; no
page-level horizontal overflow was observed. Temporary viewport overrides were
restored.

Evidence and persisted release logs are in
[`artifacts/live-handoffs-2026-11-08`](../artifacts/live-handoffs-2026-11-08/),
including `release-verification-2026-11-09.json`, original outputs, call receipts,
artifact hashes and screenshots. The report was subsequently authorized on
November 9 as a separate submission deliverable; this does not change historical
results.
