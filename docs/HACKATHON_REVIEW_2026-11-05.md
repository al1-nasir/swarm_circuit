# SwarmCircuit: independent hackathon reviewer assessment

Reviewed November 5, 2026 (Asia/Karachi). This is a simulated reviewer assessment,
not an official score or a prediction of placement. Three parallel reviews covered
research evidence, product story and official criteria; the primary reviewer
inspected the running application. No application source was changed, paid model
calls made, new controls applied, approvals resolved or external submission made.
The existing backend and production dashboard were started for inspection.

## Verdict

**Major revision needed before I would advocate for this as a winning submission.**
The project has substantial reusable engineering, but a first-time reviewer has
to work too hard to identify the user, problem, intervention and useful result.
The present demonstration establishes that the control protocol works. It does
not yet establish that intervention improves a meaningful AI-team task.

Earlier delivery reports emphasized working components and test counts. Those
are engineering milestones; they do not establish product usefulness, novelty or
hackathon competitiveness. The practical response is to narrow the claim and
complete one comprehensible case. Keep the existing visual direction during this
sprint and spend the time on purpose, evidence and an end-to-end result.

## What we actually built, in plain language

> SwarmCircuit helps a developer see why a team of AI workers is stuck, request a
> pause for the affected tasks, and inspect what the workers actually confirmed.

It connects to an existing workflow; it does not create an autonomous team for
you. Its controls require cooperating host code and explicit pause points. It
cannot stop arbitrary uninstrumented or malicious code.

| Part | What exists | What a reviewer still needs |
| --- | --- | --- |
| Python connection kit | Records tasks, dependencies, waits and host control boundaries | A small real integration they can understand and run |
| Inspection/control console | Workflow map, timeline, findings, approval/payment evidence and reviewed holds | One explanation of the shared cause, action and resulting useful progress |
| Experiment runner | Reproducible synthetic policy comparisons and evidence exports | Stronger task diversity, actual runtime evaluation and a justified research claim |

A pending human approval is often correct behavior. The problem worth studying
is unnecessary repeated demand, notification noise, or intervention that blocks
unrelated work while actors wait. Do not pitch every wait as a failure.

## Fit to the event

This event judges a research report. The official dimensions are **Impact
Potential & Innovation**, **Execution Quality**, and **Presentation & Clarity**,
each scored 1–5. Track 4, Multi-Agent Oversight and Control, is the closest fit.
Earlier work must be disclosed; only weekend work is judged. Existing November 5
code and results are preparation, as the repository already states. The deadline
is November 8, 23:59 AoE: **Monday November 9, 16:59 Pakistan time**.
[Official event criteria](https://apartresearch.com/sprints/swarm-alignment-2026#guidelines).

| Dimension | My assessment | What would materially improve it |
| --- | --- | --- |
| Impact/innovation | Plausible problem; specific research contribution remains weak | Identify and test one coordination failure and a defensible remedy |
| Execution | Careful protocol/evidence foundation; practical benefit unproven | A measured actual workflow, useful output and fair baselines |
| Clarity | Main weakness: too many identities and technical terms | One human story, one outcome, one main result figure |

These are qualitative judgments, not fabricated official numerical scores.
A dashboard alone is established territory: Langfuse documents agent graphs,
LangGraph documents human-in-the-loop interruption/resume, and AgentOps documents
session observability. A specific evaluated group-level failure and intervention
would be a better distinction than a feature inventory.
[Langfuse](https://langfuse.com/docs/observability/features/agent-graphs),
[LangGraph](https://github.com/langchain-ai/docs/blob/main/src/oss/langchain/human-in-the-loop.mdx),
[AgentOps](https://docs.agentops.ai/v2/introduction).

Past Apart winners such as
[Omission Attacks](https://apartresearch.com/sprints/projects/omission-attacks-when-doing-nothing-is-the-attack-0y1v)
and [Noticing the escapes](https://apartresearch.com/sprints/projects/noticing-the-escapes-who-spots-a-runaway-agent-and-how-long-does-it-take-pne8)
provide useful examples of a narrow failure question and inspectable evidence.
Their published reviews also ask for validation and restrained claims. This is
an illustrative pattern, not evidence of a universal recipe for winning.

## Findings that most threaten the submission

### 1. The live demonstration does not show what the intervention improves

All four protected workers are already waiting at approval-guarded checkpoints.
The independent task is only completed after a hold appears in the command
history. That is valid engineering sequencing, but it cannot establish that the
hold reduced waste or caused healthy work to keep moving. The printed zero-effect
and pending-approval fields are constants, rather than independent measurements.

Evidence: [demo setup](/home/ali-nasir/PycharmProjects/swarm_circuit/examples/containment_demo.py:54),
[independent task sequencing](/home/ali-nasir/PycharmProjects/swarm_circuit/examples/containment_demo.py:110),
[printed fields](/home/ali-nasir/PycharmProjects/swarm_circuit/examples/containment_demo.py:125).

The actual SDK checkpoint already waits for approval and prerequisites. Include
**SDK guards alone, without a hold request** as a runtime baseline. If that
baseline already eliminates repeated attempts, a separate backpressure hold has
not demonstrated additional benefit. Do not introduce artificial busy loops just
to make the intervention appear necessary. This simulator-versus-runtime gap is
itself an important finding to resolve.

**Change:** Show repeated blocked requests before intervention, measured reduction
afterward, genuinely independently scheduled work and a useful output file.
Read permission state and actual effects from a separate local mock tool/authority
ledger. Include an authorized recovery case. Preserve the pending/denied cases
where no protected action should execute. A request or ACK is not the final user
outcome.

### 2. The strongest comparison challenges the central controller story

Actual repeated-gate seed means:

| Approach | Coordination requests | Guard checks | Permitted completion |
| --- | ---: | ---: | ---: |
| Ignore identical repeats (B3) | 62.73 | 12.30 | 100% |
| Pause the affected dependency branch (B4) | 17.27 | 11.80 | 100% |
| Wait until prerequisites are ready (queue) | 6.00 | 6.00 | 100% |

Across all nine current scenarios, the queue uses fewer mean requests in eight,
ties in normal execution, and matches B4 completion. Both fail on the deliberately
incorrect graph. Do not remove the queue or imply B4 is generally superior.

The proposed exception, “we can pause externally scheduled agents but cannot
install a queue,” is not established. Both mechanisms currently receive the same
graph/state and withhold work at the same cooperative boundary. A real deployment
constraint would need evidence. Do not artificially deprive a baseline of state
or capabilities to create a win.

Evidence: [stored results](/home/ali-nasir/PycharmProjects/swarm_circuit/artifacts/research/0ada95ca-a10a-4835-ade4-31c088c2e031/results.json).

**Change:** Make the research about when observation-dependent coordination loses
progress and which repair restores it. Let a simple queue remain the best method
if that is what the evidence shows.

### 3. The headline scale and safety metrics need careful explanation

The 2,160 trials repeat one six-node graph across nine handcrafted conditions,
thirty seeds and eight policies. They are not 2,160 distinct real-world AI tasks.
The seeds quantify variation within that designed environment.

Unsafe starts are prevented by the common tool guard. Completed/running tasks are
skipped, preventing duplicate effects. These are worthwhile invariant checks,
but they do not distinguish the policies or demonstrate adversarial safety.
Request counts exclude proposals suppressed before policy admission, and the
1/3/10 modeled-work weights are accounting assumptions. No measured token-price,
dollar or production-throughput reduction follows from them.

Evidence: [admission and request recording](/home/ali-nasir/PycharmProjects/swarm_circuit/packages/server/src/swarmcircuit_server/research/simulator.py:208),
[guarded effect boundary](/home/ali-nasir/PycharmProjects/swarm_circuit/packages/server/src/swarmcircuit_server/research/simulator.py:231),
[metrics](/home/ali-nasir/PycharmProjects/swarm_circuit/packages/server/src/swarmcircuit_server/research/metrics.py:41).

There is also a communication trap: permitted-completion divides by five goals
when approval arrives, but only one goal while approval remains pending. A mostly
blocked workflow can therefore show 100%. Show total goal progress (for example,
1/5), correctly waiting/refused tasks, and eligible work completed separately.
Keep the existing metric for research, with its explicit denominator.

### 4. No completed substantive live AI-team case exists yet

Both live-model pilots failed. Even successful execution of the current model
path would ask stateless node personas for attempt/wait JSON and replay those
choices with fixed counterfactual feedback. It would not produce a meaningful
research brief or test adaptive team behavior under each intervention.
[Provider prompt](/home/ali-nasir/PycharmProjects/swarm_circuit/packages/server/src/swarmcircuit_server/research/provider.py:60).

**Change:** Complete one small closed-loop workflow with actual tool/state
feedback and an independently checked deliverable. Treat provider availability
and third-party model identity as things to verify. Additional model runs help
establish AI relevance but are not an official submission requirement; a handful
of runs also does not establish generality. If this remains systems/testbed
research, state that scope honestly.

### 5. Simulated performance is not measured performance of the UI control

Simulation B4 acts immediately and clears parking on a delivered gate change.
The production path requires review, command delivery, a matching host ACK and
explicit resume. Operator delay and actual SDK behavior are absent from the
simulation result. The UI action cannot inherit the simulated 72.5% request
reduction as a measured product claim.
[Simulation gate updates](/home/ali-nasir/PycharmProjects/swarm_circuit/packages/server/src/swarmcircuit_server/research/simulator.py:35),
[production behavior](/home/ali-nasir/PycharmProjects/swarm_circuit/README.md:225).

**Change:** Measure the actual runtime intervention and recovery; keep algorithm
simulation results as a clearly separate controlled experiment.

### 6. Repairing stale observations is a better next experiment than adding pages

A lost approval update causes B3/B4/queue to complete only public work (20% of
five permitted goals). An incorrect dependency causes B4 and the queue to prevent
public from completing. These are concrete failures worth investigating.

A fresh authoritative query can recover a missed notification if the source is
correct. Querying the same semantically wrong graph cannot establish that an edge
is wrong. Distinguish missed updates/version drift from wrong specifications;
the latter needs independent evidence or human correction. Never let the repair
read hidden simulator truth.

Also test explicit denied-state behavior. Existing B4 clears parking on a denial
update and only suppresses while pending: it averages 95.87 requests in the denial
case, versus backoff 36.13 and queue 24.73. A denial should not be silently
reinterpreted as approval or a reason to restart futile demand.

## Suggested research contribution

**Question:** When coordination depends on incomplete observations, which
reconciliation strategies restore authorized work while preserving unrelated
progress?

**Candidate experiment:** Evaluate a conservative authoritative-state refresh
strategy against SDK guards alone, existing scoped pause, backoff, queue and a polling-capable
queue. Include a whole-workflow pause if the pitch emphasizes keeping unrelated
work moving. Give all methods equal state access, polling budgets and intervention
capabilities. Count reconciliation overhead. A repaired queue may win: that is
an acceptable result, not a reason to weaken the comparison.

Use several genuinely different task graphs and fault settings, including clean
human waiting, delayed/missing updates, disconnection and incorrect dependencies.
Fix protocol, prompts, budgets and success criteria before the main event-period
run. Reserve some fault configurations for final evaluation. Track each failure
and incomplete episode explicitly. Report uncertainty at the episode/seed level.

This is a proposed research direction requiring literature comparison and results;
it is not a claim that polling or graph validation is novel by itself.

## One demo a reviewer can understand

A small AI analyst team writes a brief. Public-source research can continue, but
analysis of a protected mock CSV requires permission. Several workers repeatedly
request the blocked resource. The reviewer sees one shared cause, which tasks
are affected, and the observed cost of repetition. A reviewed pause suppresses
the affected demand. The public branch produces its own useful file on its own
schedule. A separate local authority later approves the mock resource; an
explicit reviewed recovery lets the team finish the brief. Denial stays blocked.

The screen should answer these questions without opening a protocol inspector:

1. What happened? “Four tasks are waiting for dataset access.”
2. Why does it matter? Show measured repeated requests or interruptions.
3. What can I do? “Review affected tasks.”
4. What remains productive? Public research, with an actual output link.
5. Did it work? Before/after counts, host confirmation, useful output and recovery.

Keep pending human approval visually separate from unnecessary retrying. Clearly
label local mocks, historical replay and live connected workers.

## Fresh screen-by-screen audit

All screenshots below were captured and opened during this review. No prior QA
screenshot was reused. Captured desktop viewport was approximately 1905×993;
full-page captures extend vertically. This is a reviewer walkthrough, not a
representative usability study or a complete accessibility assessment.

### Step 1 — Overview: functional inventory, weak first-time explanation

![Step 1 overview](/home/ali-nasir/PycharmProjects/swarm_circuit/artifacts/reviewer-audit-2026-11-05/01-overview.png)

The restrained visual system and consistent navigation are strengths. The screen
shows 19 recorded workflows, 7 running/6 waiting, zero open incidents and repeated
“Studio gateway verification” rows. Loaded-page limits are labeled honestly.
However, a judge sees diagnostics and an integration CTA before the user problem.
Historical run lifecycle is easy to mistake for connected workers. Keep diagnostic
runs available in a separate filter, curate a labeled demo and show liveness.

### Step 2 — Connect action: useful documentation, poor first demo

![Step 2 setup](/home/ali-nasir/PycharmProjects/swarm_circuit/artifacts/reviewer-audit-2026-11-05/02-setup.png)

The main action leads to SDK code, schema, OTLP and provenance detail. Those are
useful after the value is understood. Add an “Explore the demo” entry that shows
an understandable case, then offer setup to developers who want to connect code.

### Step 3 — Workflow map: readable structure, missing explanation

![Step 3 workflow map](/home/ali-nasir/PycharmProjects/swarm_circuit/artifacts/reviewer-audit-2026-11-05/03-workflow-map.png)

The explicit arrow direction, task labels and read-only orchestration label are
helpful. Four nodes say “hold status unknown.” The public task is complete. A
fresh snapshot timestamp does not tell a visitor that this is an old recorded
workflow with no live host. Add a prominent current/historical state and a
plain-language cause/affected-work summary. Retain the list alternative to the
canvas. Use the map to explain an incident, rather than make the visitor infer it.

### Step 4 — Approvals: precise historical evidence, difficult language

![Step 4 approvals](/home/ali-nasir/PycharmProjects/swarm_circuit/artifacts/reviewer-audit-2026-11-05/04-approvals.png)

The history shows four applied ACKs while the current graph says status unknown.
Both can be correct at different times. Explain “Pause confirmed at [time]; worker
is offline now.” “Canonical outcome,” “runtime ACK” and “epoch” should sit behind
Technical evidence; lead with human meaning. Preserve the distinction between
requested and host-confirmed actions. No new command was submitted in this review.

Source-level concern for a new browser: this group summary loads from a locally
stored intent/key. The Controls tab retains command history, but group-summary
discovery should not require the reviewer to inherit the demonstrator's browser
storage. Verify a clean-profile deep link before recording.
[Intent loading](/home/ali-nasir/PycharmProjects/swarm_circuit/apps/studio/components/containment.tsx:57).

### Step 5 — Comparison: strong transparency, missing first conclusion

![Step 5 actual comparison](/home/ali-nasir/PycharmProjects/swarm_circuit/artifacts/reviewer-audit-2026-11-05/05-comparison.png)

The data, confidence intervals, evidence scope and stronger comparison are visible.
The visitor still has to decode B3/B4, find a metric and derive the takeaway. Add
a plain-language result paragraph with an explanation and limitations; keep the
full analysis under it. This review measured **75,078 ms** for the first result
request after backend restart. That is one cold-load observation, not a repeated
latency benchmark. Persist completed aggregate results and precompute them before
opening the page; the reviewer should not wait while bootstrap estimates rerun.
[Current in-process cache](/home/ali-nasir/PycharmProjects/swarm_circuit/packages/server/src/swarmcircuit_server/api/research.py:83).

### Step 6 — Counterexample: potentially useful research, needs interpretation

![Step 6 graph error](/home/ali-nasir/PycharmProjects/swarm_circuit/artifacts/reviewer-audit-2026-11-05/06-counterexample.png)

The incorrect-graph case honestly shows zero independent completion for B4 and the
queue. Lead with: “The wrong dependency stopped work that should have continued.”
Explain how the proposed intervention detects or limits that risk, and preserve
the case where it cannot. A failure figure can make the work more credible.

### Accessibility observations and limits

Text accompanies status colors, native form controls have useful labels, and a
graph-list alternative exists. Small metadata, dense confidence intervals and
canvas labels may be difficult at zoom or on a projector. Check readable type,
native focus order, dialog focus/return and screen-reader names in the final demo.
Custom keyboard shortcuts are unnecessary; preserve ordinary native keyboard
access. This review did not test mobile reflow, assistive technology, contrast
ratios, every dialog state or full WCAG compliance.

## Priorities for the available days

| Date | Focus | Concrete acceptance check |
| --- | --- | --- |
| Nov 5 preparation | Freeze existing work; agree on one sentence, user and question | A person unfamiliar with the code can explain the purpose after 30 seconds |
| Nov 6 | One useful actual workflow and independent outcome measurement | Real output files; independent worker runs without waiting for a hold; pending/denied actions remain blocked |
| Nov 7 | Evaluate the candidate repair fairly on actual runtime + controlled faults | Strong queue/polling baseline retained; identical authority access; overhead and failures reported; no simulator-truth access |
| Nov 8 | Present the result and limitations; record optional demo after claims are settled | One main result figure and one failure figure; readable official-template paper; event-period work separated |

Provider reliability is a risk to this schedule. Start with one complete smoke
workflow before scaling. Do not spend the event repeatedly running an unavailable
provider or silently replace failed live episodes with synthetic outcomes.

Deprioritize new payment features, a workflow builder, more connector logos,
another full redesign, remote production infrastructure and more dashboard pages.
Keep the authority boundaries, evidence hashes, explicit uncertainty and failed
trials. For a later portfolio, add a concise README, short captioned demonstration,
a reproducible start command, a real integration and a clear account of the
engineering decisions you personally understand.

## Submission readiness checks

The owner can explain the problem and the finding without SDK vocabulary. The
research states what is new during the sprint. One actual workflow and its useful
output can be inspected. The strongest simple method is retained. Completion,
correct refusal, wasted requests and recovery are separate outcomes. Real model
usage is measured if a live-model claim is made. The limits of cooperative control
are explicit. The paper has required author/affiliation and appendix details, and
participant status is verified separately; it was not checked here.

## Evidence and review limits

The primary reviewer read actual results across all nine scenarios. An independent
reviewer replayed six sampled trial artifacts and checked the CSV checksum; those
checks passed. Existing test files and previous validation records were inspected;
the full backend suite was not rerun for this review. This is not a security audit
of deployment or an independent verification of a provider's model identity.

All four protected workers' historical ACKs were reviewed, but this run did not
repeat a live application or recovery. The precise behavior of inaccessible
external authorities was not tested. No use-case interviews were conducted.

Only new review documentation and capture artifacts were written. The primary
recommendation is **a narrow, useful workflow plus an honestly evaluated
coordination-failure remedy**. A larger feature inventory will not resolve the
current clarity and evidence gaps.
