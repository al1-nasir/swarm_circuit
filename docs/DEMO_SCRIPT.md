# Four-minute demo script

Preparation version: November 5, 2026. The source, demo and current synthetic
results predate the event. Do not present them as new weekend contributions.
No video or submission is claimed by this file.

## Prepare before recording

```bash
make server PORT=18005
# After building Studio, another terminal:
SWARM_API_URL=http://127.0.0.1:18005 make studio STUDIO_PORT=3300
# Fresh actual SDK checkpoints, another terminal:
SWARM_API_URL=http://127.0.0.1:18005 make demo-containment
```

The bounded demo prints a fresh run URL. Use it immediately; do not demonstrate
active containment against an expired host. Keep `.env` and terminal credentials
out of the recording. Current results are at
`http://127.0.0.1:3300/experiments/0ada95ca-a10a-4835-ade4-31c088c2e031`.
The normal runner can recreate these results under a new experiment UUID.

## 0:00-0:35 - Problem and authority

Open the fresh workflow graph. Explain: four tasks share a pending mock dataset
approval; the public-reference branch is independent. Trace ancestry is not
control authority. Everything shown is labeled simulated. SwarmCircuit observes
coordination failure and requests cooperative holds at declared SDK boundaries.

## 0:35-1:35 - Reviewed intervention

Go to Approvals → Review containment. Enter a reason. Preview targets. Show the
four selected checkpoints and two outside-branch tasks. Explain that target
versions, checkpoint IDs and runtime epochs are bound to the preview hash.
Request four holds. Wait for all four “Applied · runtime ACK” outcomes. Queued
commands do not count as applied. Show pending approval and completed public
branch in the graph. Reload: the original policy request reconciles from durable
history. The demo never grants approval or executes a protected effect.

## 1:35-2:40 - Fair comparison

Open Experiments → Coordination policy pilot. Show 2160 completed, 0 failed,
0 missing: thirty matched seeds, nine scenarios, eight arms. Select “Repeated
requests on a shared gate” and coordination requests. Dedup averages 62.73,
backpressure 17.27, ready queue 6.00. Show paired intervals and guard-check metric:
dedup already removes most checks. This is not a dollar or runtime benchmark.
Select permitted completion: the retry cap loses completion; fewer requests alone
are not success. The ready queue is the stronger prevention baseline.

## 2:40-3:20 - Show the failure, not just the win

Choose incorrect dependency → independent completed: graph-based backpressure
and ready queue both lose the independent branch. Choose omitted approval update:
completion falls to 20% under observation-dependent policies. Explain the need for
authoritative reconciliation and graph validation. Zero unsafe starts is enforced
by common guards in the simulator, not proof of real-world safety.

## 3:20-4:00 - Evidence and honest next step

Open Trials: inspect seed/arm, raw truth and observation downloads. Open Protocol:
show fixed parameters/source hashes, then CSV export. Mention the failed live
DeepSeek pilot explicitly: no completed live-model benchmark. Conclude with the
narrow result: backpressure helps on this synthetic retrying workload, scheduling
can do better, and graph/telemetry errors threaten liveness. The next event-period
experiment should test closed-loop actors and recovery on independently reviewed
graphs. Show the PDF draft and reproducibility bundle; they are not submitted.

## If a live step fails

Read the canonical error. Refresh/recheck the same request; do not repeatedly
submit with fresh keys. If the runtime has expired, start a fresh bounded demo.
Use saved evidence only as historical evidence, never pretend it is a live ACK.
If the provider is unavailable, show failed trials rather than switching silently
to synthetic outcomes. Submission, author/affiliation confirmation and a final
human review remain separate user actions.
