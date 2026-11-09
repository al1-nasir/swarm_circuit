# SwarmCircuit — four-minute demonstration

Use the retained successful case; this rehearsal does not require another paid
model call. Record the application window and your voice. Avoid showing `.env`,
terminal environment variables, the private database or unrelated browser tabs.

## 0:00–0:25 — The problem

“A team of agents can report progress while passing an unsupported result to the
next worker. SwarmCircuit makes those handoffs inspectable: we retain the original
draft, show what the reviewer actually received, and compare the supported claims
with source data before publishing an output.”

Show the guided demo page. Keep the story about the sales-brief task, rather than
listing every dashboard page or security feature.

## 0:25–1:00 — What actually ran

Open the saved live case:
`http://127.0.0.1:3300/demo?demo=d449f1a6-1ba2-4f04-aaee-774197881a11`.

“This is the saved evidence of an actual model run. Six SDK tasks completed. Two
of those tasks use model roles: a writer and a reviewer on the same configured
provider. The run made two model calls, reporting 997 input and 304 output tokens.
It did not need a repair.”

Point to the 6/6 progress and 2/3 call count. Do not describe the saved worker as
currently connected or claim six independent LLM agents.

## 1:00–1:55 — Inspect the handoff

Expand **Agent handoff evidence**. Choose **Writer's original draft**, then
**Reviewer's feedback**.

“The reviewer receives this actual structured draft, not a template that merely
says review happened. It also receives facts independently recomputed from the
sample CSV. The original draft and the review stay available, even when a later
step fails. The writer's free-form explanation is evidence, not certified truth.”

Show the typed quantities and reviewer verdict. Briefly open the workflow map if
it helps establish that review depends on the writer task; return to the output
instead of touring graph controls.

## 1:55–2:45 — Check the result against the source

Choose **Handoff checks and provenance**, then read the finished brief.

“The checker recomputes 120000 first-quarter revenue and 166980 last-quarter
revenue: 39.15% growth. It also checks four quarters, 1800 customer-quarters and
the required limitations. Publication needs the source check, not just an
accepting reviewer. The final brief renders those supported structured claims.”

“Revenue is not profit; customer-quarters are not unique customers; four quarters
do not establish a forecast. These are synthetic sample units.”

## 2:45–3:25 — Bound the work and expose failure

Show the mode chooser and live-use review without starting another run, or show
the saved `live-start-review.png` image.

“Live use is optional and explicitly reviewed. A writer and reviewer normally
take two calls. If the review or source check rejects the draft, its actual
feedback can trigger one repair, with a ceiling of three calls. A failed repair
stays visible and produces no final brief. There is no silent offline substitute
and no automatic paid retry.”

“The repair path and failure cases are exercised using controlled responses in
tests. This particular real run was accepted immediately; it does not demonstrate
a naturally occurring model error.”

## 3:25–4:00 — Permission and useful independent work

Show the saved offline denial case:
`http://127.0.0.1:3300/demo?demo=1176c620-69d8-4878-8bff-f5d80790d545`.

“Public findings can finish while the sample dataset is awaiting a decision.
Denial keeps those findings available and leaves protected effects at zero. In
the live case, before sample access was granted, there were zero model calls and
zero protected effects. An operator pause requires a separate resume.”

## 4:00–4:20 — State the contribution and its limit

“The contribution is a working, inspectable handoff with independent source
checks, bounded model work and retained failure evidence. It is a small
same-provider case, not a large-swarm benchmark or a proof of general safety.
The next study should measure whether these checks reduce downstream mistakes
across more tasks and model families.”

Do not claim a win, broad novelty, dollar savings, measured superiority to a ready
queue, independent model-family judgment or an error-rate estimate from one run.

## Optional supporting files

- `artifacts/live-handoffs-2026-11-08/live-before-access.json`
- `artifacts/live-handoffs-2026-11-08/live-completed.json`
- `artifacts/live-handoffs-2026-11-08/handoff-evidence.md`
- `artifacts/live-handoffs-2026-11-08/artifact-verification.json`

The November 5 synthetic comparison and failed model pilots are historical
preparation. If mentioned, label them separately and retain the stronger ready
queue baseline and adverse graph/telemetry cases.
