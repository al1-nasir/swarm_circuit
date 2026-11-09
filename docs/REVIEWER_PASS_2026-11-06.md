# Reviewer repair pass — November 6, 2026

The main walkthrough now has a complete, readable path from permission wait to
reviewed pause, explicit recovery and a useful output. This pass fixes workflow
failures and presentation gaps; it adds no broad product pages, paid model calls
or research paper.

## Findings and repairs

| Finding reproduced during review | Resulting behavior |
| --- | --- |
| A normal sample wait generated four identical permission requests and an approval-storm finding | One request gates the access task and its three declared dependents. The detector is unchanged. |
| A lost permission response could leave the browser unable to proceed | Explicit retry preserves the original key and canonical content. Only its digest is stored; the reason remains out of browser storage. After reload, the original reason must match before retry. |
| Paused tasks required finding controls inside individual graph inspectors | Pause history lists held tasks with reviewed resume actions. Prerequisites, authority, uncertain outcomes and current host eligibility still determine availability. |
| A dialog could remain open after its task or decision became ineligible | Control review checks current eligibility; resolved permission polling closes obsolete decision reviews. Backend validation remains authoritative. |
| Completed-run actions opened a graph rather than the actual brief | Owned demo relations provide direct output links and a return path from the graph/history. Host-supplied metadata cannot forge that relation. |
| Cancelled runs could become active again when late telemetry arrived | Cancellation and end time persist while late evidence is retained. Historical pending permission does not invite a new decision on an ended run. |
| An exited managed worker appeared connected until its heartbeat expired | Confirmed worker exit records canonical disconnection immediately. Completion is published only after the final SDK lifecycle acknowledgement. |
| Shutdown and failed checkpoints could leave misleading active demos | Shutdown prevents new starts; unexpected checkpoint failure ends the walkthrough promptly. Saved outputs and actual effects remain inspectable. |

The current primary action follows the task: review sample access first, review
operator pauses after permission is granted, then read the finished brief.
Recent dates and times now consistently use UTC.

## Walkthrough checked in the browser

1. **Overview — healthy.** Purpose and demo entry are visible. Recorded status is
   separate from current connections. Ended workflows with findings explain why
   they still need review.
2. **Start and permission wait — healthy.** One permission gates four tasks;
   public findings finish independently. Progress is 2/6, protected steps zero.
3. **Pause preview — healthy.** Four eligible tasks are reviewed, with two outside
   the branch. All four pause requests obtained matching runtime confirmations.
4. **Grant and resume — healthy.** Access approval preserved the pauses. The
   dataset task became eligible first, analysis and validation next, and the
   final brief only after its prerequisites completed. All four resumes were
   separately reviewed and confirmed.
5. **Read and download — healthy.** The run completed 6/6 tasks, with four
   protected steps, one access request and no findings. The downloaded brief's
   SHA-256 matched the saved artifact. Its checked sample result is 39.15% revenue
   growth, with limits stated in the document.
6. **Denial — healthy.** A fresh run retained public findings, executed zero
   protected steps and produced no restricted analysis or final brief.

The completed demo is `9d259cd1-83c3-4342-b0d0-2d6ee1f1ed78`; the denied demo is
`39dce1b8-3955-47f1-89c4-f4fd656079ad`. Both are owned local fixtures. An earlier
review run was interrupted during deployment; it remains honestly recorded as
interrupted, with its saved output retained.

### Permission review

![The next action is explicit](/home/ali-nasir/PycharmProjects/swarm_circuit/artifacts/reviewer-pass-2026-11-06/11-final-primary-action.png)

### Explicit recovery

![Only the eligible prerequisite can resume](/home/ali-nasir/PycharmProjects/swarm_circuit/artifacts/reviewer-pass-2026-11-06/08-final-resume-eligibility.png)

### Actual output

![Readable checked sales brief](/home/ali-nasir/PycharmProjects/swarm_circuit/artifacts/reviewer-pass-2026-11-06/09-final-sales-brief.png)

### Denied access

![Denied access retains public findings](/home/ali-nasir/PycharmProjects/swarm_circuit/artifacts/reviewer-pass-2026-11-06/12-final-denial.png)

The reader was also inspected at 390 pixels, without page-level horizontal
overflow. Named dialogs, labelled reasons and native focus behavior are retained.
These checks do not establish full accessibility compliance; assistive-technology
coverage and all fault combinations were not exercised through the browser.
Lost-response content binding has focused unit coverage, and runtime lifecycle,
guard, ACK and shutdown failures have backend regression coverage.

## Validation

- `make check`: Ruff, formatting, mypy and **170 backend tests passed**.
- Final summary wording: **6 focused workspace tests passed** afterward.
- Studio: formatting, strict TypeScript, **15 unit tests** and production build
  passed.
- **5 live HTTP/WebSocket gateway checks passed**, including credential
  isolation and write guards.
- Actual browser recovery: four pauses plus four resumes, each with a matching
  host/session/epoch acknowledgement; denied effects zero.
- The final services respond on local ports 3300 and 18005, schema 006.

Structured results, exact snapshots and the downloaded brief are in
[the evidence folder](/home/ali-nasir/PycharmProjects/swarm_circuit/artifacts/reviewer-pass-2026-11-06),
including
[verification-summary.json](/home/ali-nasir/PycharmProjects/swarm_circuit/artifacts/reviewer-pass-2026-11-06/verification-summary.json).

This remains a trusted local workspace with cooperative SDK control. It is not a
remote authentication product or a sandbox for arbitrary code. The walkthrough
has zero model calls and establishes no comparative cost or safety result.
Historical study artifacts and the paper remain unchanged.

Use the [judge walkthrough](JUDGE_WALKTHROUGH_2026-11-06.md) for a focused rehearsal,
the current official requirements, and the competitive evidence still missing.
