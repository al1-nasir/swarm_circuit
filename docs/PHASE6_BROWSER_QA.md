# Phase 6 browser verification

November 5, 2026; pre-sprint engineering checks. BrowserAct 1.4.2 on the owned
`swarm-research-qa` Chrome session; CDP used only for viewport/screenshot/console
inspection. No external business action, approval decision or payment occurred.

- Experiments selection and direct UUID routes loaded real stored results.
- Synthetic study showed 2160 completed / 0 failed / 0 missing, 30 seeds,
  9 scenarios, 8 arms. Comparison filters changed scenario and metric; the
  incorrect-graph view retained zero independent completion for B4 and the queue.
- Trials tab, policy filter and Protocol tab worked. Pagination loaded all 240
  distinct trial/run rows without duplication and exhausted the cursor; stale filter responses are guarded. Protocol showed the actual
  source/protocol hashes and fixed parameters. Trial links point to the recorded
  Observe projections and evidence downloads, rather than inventing runtime ACKs.
- Actual gateway requests downloaded truth and observation JSONL (200); every
  line parsed. Exported synthetic CSV SHA matched the offline-verified manifest.
- Failed live-model study showed 0 completed / 8 failed / 0 missing with an
  explicit incomplete-evidence explanation. Failed trials had no numeric outcomes.
- At 1440×960, 1024×900 and 390×844 the experiment views had no document-wide
  horizontal overflow. Tables and navigation retain their own scroll containers.
  Mobile trial lists are long but paginated; no custom keyboard shortcuts added.
- Actual bounded SDK demo ff817850-735f-4485-b9be-4dbc9a2fd850: four eligible
  reversible checkpoints, two outside-branch nodes, recorded reason, exact
  preview hash, four matching applied runtime ACKs (epoch 1). Independent mock
  task completed, protected effects 0, shared approval remained pending.
- Reload reconciled the original policy request and four durable ACKs. Historical
  applied status is not a claim that the bounded demo host is still connected.
- Console inspection recorded no JavaScript exceptions. One expected GET 404
  occurred when reconciliation preceded initial policy commit; the original key
  was preserved and subsequent canonical history returned all four ACKs. The
  first cold experiment aggregation exceeded the former 15-second gateway limit;
  result aggregation now has its own bounded 120-second deadline and backend
  caching. Other gateway calls retain the 15-second limit.

Screenshots and structured check: `artifacts/research/qa/`. These are one-session
engineering evidence, not a usability study or replicated runtime benchmark.

After the production restart, fresh console capture showed zero error records.
Earlier expected unknown-outcome reconciliation is preserved separately.
