# Phase 6 delivery - research and reviewed containment

Prepared November 5, 2026, before the November 6–8 event. No submission, team
registration, author approval or hackathon-period contribution is claimed.

## Delivered

The matched-policy runner now records immutable plans and trials, separate truth
and observation journals, source/protocol hashes, twelve explicit metrics,
seed-level uncertainty, paired contrasts and CSV/raw exports. Migration 005 adds
one sealed-artifact table (42 tables total). Operator recording is bounded and
project-scoped. CLI-only optional provider collection has HTTPS configuration,
call/token provenance, strict output parsing, a total-call cap and no automatic
paid retries. Offline verification replays without provider calls.

Experiments has Comparison, Trials and Protocol tabs with scenario/metric/policy
filters, real CSV exports, raw evidence links, failure accounting and provenance.
Ordinary workflows exclude research projections. The reviewed group action lives
in Approvals: reason → target preview → exact-preview confirmation → canonical
runtime ACK reconciliation. Scope/version/epoch changes reject before mutation.
Original idempotency keys survive reload or unknown outcomes. External approval
and payment decisions remain separate. Backend/group-control authority is still
cooperative, not process isolation or a remote user-authentication system.

## Actual study

Synthetic experiment: `0ada95ca-a10a-4835-ade4-31c088c2e031`.
30 matched seeds × 9 scenarios × 8 arms = **2160 completed**, 0 failed, 0 missing.
Every completed artifact and CSV measurement passed offline replay verification.
Source fingerprint: `7be6aac8b415846ac88705179e8d801c235f9e381ca3a15b11292291a300f57a`
(a content fingerprint, not a Git commit).

Repeated-gate requests: B3 dedup **62.73**, B4 backpressure **17.27**, ready queue
**6.00**. Paired B4-minus-B3 difference **-45.47**, 95% interval **[-49.67,-40.93]**.
B4 guard-check improvement is small: -0.50, interval [-0.77,-0.30]; dedup already
removes most checks. B1 completion is 84%; B3, B4 and queue complete 100% in that
scenario. Normal/wait cases show no B4 false holds. These are synthetic logical
tick outcomes, not dollars, runtime throughput or real safety-risk estimates.

Counterexamples are retained. With a wrong graph edge, B4 and the queue prevent
the independent task from finishing (0/30), while B3 completes it (30/30). A lost
approval observation yields only 20% permitted completion under B3/B4/queue;
backoff achieves 93.3%. B4 remains fail-closed after truth changes. Zero unsafe
starts is enforced by shared simulator guards, not evidence of adversarial safety.
The automatic simulated B4 policy differs from operator-reviewed production
application and explicit production resume. Full protocol: experiments/README.md.

Live-model evidence is **incomplete**. DeepSeek-V4-Flash at the configured
third-party host passed one separate connectivity smoke call. Two bounded pilot
attempts failed with provider_unavailable after 1 and 2 attempted calls. Their
IDs are `c62bf7f9-78f0-4b3d-8ed5-996122ec36f2` and
`bb241eed-3584-4b64-aa15-1c2e2ea8bf54`. Each preserves 8 failed arms with no
numeric measurements; unknown token counts remain null. These exports also
passed offline verification. No closed-loop live-agent benchmark is claimed.

## Verification

- Full backend check: Ruff, format, mypy (40 files), **149 tests passed**.
- Studio: formatting, strict TypeScript, **12 unit cases**, production Next build.
- Running HTTP/WebSocket gateway: **5 integration cases passed**, including scoped
  CSV export and blocked experiment-execution writes.
- Actual BrowserAct/SDK check: four matching runtime ACKs, independent mock work
  completed, approval pending, protected effects zero, reload reconciled.
- Responsive experiment views checked at desktop, tablet and mobile widths;
  raw gateway downloads matched sealed evidence. See PHASE6_BROWSER_QA.md.
- Seven-page PDF rendered and visually checked; six body pages plus required
  limitations/dual-use/LLM/pre-existing-work appendix. Author metadata needs
  human confirmation. This is a preparation draft, not a submitted report.

## Reproduce and demonstrate

`make research`, `make research-verify EXPERIMENT_DIR=...`, and
`make demo-containment` are documented in experiments/README.md. Start the backend
on 18005, Studio on 3300, and use docs/DEMO_SCRIPT.md for the four-minute sequence.
A fresh demo host is needed for live control; saved ACKs are historical evidence.
The reproducibility ZIP includes source/locks, raw trials, failures, report,
figures and checksums; it excludes local credentials and the private database.

The next research contribution should be a preregistered closed-loop live-model
comparison, authoritative reconciliation under missing observations and graph
validation. Track that work separately during the actual sprint. Production
human/payment connectors, remote authentication, cancellation and autonomous
recovery remain outside this delivery.
