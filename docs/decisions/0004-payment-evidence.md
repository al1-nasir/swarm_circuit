# Phase 4: optional payment evidence and simulation authority

Prepared November 2, 2026. Implements SC-023–024. Original specifications, SQL,
and OpenAPI remain unchanged; additive migration 003 adds two tables (39 total).
No signer, wallet, blockchain RPC, payment retry endpoint, budget or task mandate
is introduced.

## Verified upstream boundary

The optional SDK `payments` extra pins the published
[GateKeep402 0.2.1](https://pypi.org/project/gatekeep402/0.2.1/) and
[openlibx402-client/core 0.1.1](https://pypi.org/project/openlibx402-client/0.1.1/).
The public repository's pyproject still identifies 0.2.0 and omits the openlib
imports; published 0.2.1 declares them. Its installed `gate.py`, `delivery.py`,
`source_guard.py` and `integrations/openlibx402.py` were compared byte-for-byte
with public commit `e2fcf128e3ab197216add14a0870d43752a99229` and match.
Registry artifact hashes and transitive versions are in `uv.lock`.

The actual source signatures take precedence over illustrative README snippets:
`TrustGate(ledger, policy=None)`, `evaluate(payment_request, ...)`,
`DeliveryCheck.verify(payment_request, response)`, and the native client's
`on_ask(verified_request, task_context)` callback. The
[native client](https://github.com/al1-nasir/gatekeep402/blob/e2fcf128e3ab197216add14a0870d43752a99229/gatekeep402/integrations/openlibx402.py)
preserves SourceGuard → TrustGate → native ASK callback → underlying payment →
DeliveryCheck → TrustLedger. The underlying client is passed unchanged so the
native `X402AutoClient.auto_retry=False` protection remains effective.

The observer composes gate/delivery delegates and returns their original results
or exceptions. It neither patches upstream code nor replaces the ASK handler.
Telemetry failure sets `telemetry_degraded` and cannot turn DENY into ALLOW.
The base SDK and backend import without optional payment packages. Development
bootstrap installs extras to exercise native integration tests; consumers opt in.

GateKeep402's external registry reader is configured/mock signal infrastructure,
not verified live on-chain reputation. DeliveryCheck is a structural heuristic,
not a semantic content evaluator, refund mechanism or settlement verifier. Native
library protection is not a global wallet budget or a general action firewall.

## Observation protocol and privacy

Authenticated SDK lifecycle ingestion now allowlists three event shapes:

- `payment.gate_decided`: intent/task, domain hostname, exact positive decimal
  amount string, developer asset label, network, ALLOW/ASK/DENY, optional score,
  policy digest, integration version and full action-scope digest.
- `payment.attempt_submitted`: intent/attempt identifiers. The host connector
  invokes `observer.submitted()` at its effect boundary. Submission is uncertain.
- `payment.delivery_checked`: intent/attempt IDs, structural boolean and a fixed
  structural success/failure code. No native free-text delivery reason is stored.

The scope digest binds principal, purpose, native resource, recipient, asset,
network, exact amount, request ID, intent ID and policy settings. Native resource,
recipient, asset and request identifiers are hashed before scope assembly. Only
the canonical scope digest reaches approval/payment persistence. Payment metadata
labels are host-provided; they are not independently verified authorization facts.

Requests and signed payloads remain with the original integration. No payment
header, authorization, wallet key, raw content, full URL/query or delivery-error
text is emitted. Unknown payload fields are dropped before persistence/replay
comparison. The upstream private TrustLedger has its own unchanged storage
behavior; SwarmCircuit does not rewrite or export it.

All adapter events remain `sdk_observation` from the SDK source. A declared
integration/version is not independent source verification. ASK first records
its pending approval before the payment gate event; this must occur before the
task enters a cooperative checkpoint. Unrecognized privileged events such as
`payment.settled`, `payment.mock_settled` or `approval.resolved` submitted through
the SDK remain metadata-only and cannot mutate authority state.

Intent descriptors and scopes are stable; changed scope under the same identity
rejects. Multiple gate observations retain immutable history. Any DENY is
absorbing for future control, even if a later SDK report says ALLOW. A late DENY
cannot erase a separately confirmed historical payment.

Submission/delivery observations create at most one attempt per logical intent,
with `settlement_unknown` and `self_report`. Further attempt identities reject
pending reconciliation. This is storage/control protection, not interception of
an arbitrary host wallet call. Repeated external effects remain the connector's
responsibility; the adapter adds no automatic retry or exactly-once guarantee.

## Separate mock authority

`SWARM_MOCK_BROKER_ENABLED=false` is the default. When enabled, it requires a
random credential distinct from SDK/operator secrets. `make init-mock` creates
ignored mode-0600 `.env.mock` without changing `.env`; `make server-mock` explicitly
loads it. Existing files and credentials are preserved. Normal service operation
does not require the broker or optional payment packages.

Run creation accepts additive `simulation: true`, retained in run metadata and
SDK lost-create-response reconciliation. It defaults to false and cannot be
changed by a lifecycle event. Broker callbacks reject non-simulation runs,
unknown/cross-project entities, wrong scopes and SDK/operator/runtime credentials.
Knowing a run ID or sending a simulator trust label conveys no authority.

The simulation broker endpoints require a stable `Idempotency-Key`:

- `POST /api/v1/mock/runs/{run_id}/approvals/{approval_id}/resolution` accepts
  exact `action_fingerprint` and approved/denied. It labels actor `simulator`,
  source `mock-broker-v1`, and event trust `simulation_truth`. Approval cannot
  override DENY or retroactively authorize an already submitted/unknown effect.
- `POST /api/v1/mock/runs/{run_id}/payment-attempts/{attempt_id}/settlement`
  accepts exact `scope_fingerprint` and a unique `mock:` receipt reference. It
  requires a known attempt and gate, no DENY, and an exact prior broker approval
  for ASK. It records `receipt_trust=simulator_truth`, then marks settled through
  the original SQL receipt guard. It does not submit or replay a payment.

Identical callback replay returns the stored response. Changed payloads reject;
terminal approvals and already confirmed attempts cannot be mutated under a new
key. A receipt reference cannot be reused for another effect. Audit, callback
idempotency context, authority state and outbox commit atomically. Disk failure
rolls all of them back. No production human identity, cryptographic receipt
verifier or live settlement connector is claimed by this mock authority.

## Control, incidents and visibility

Pending/denied/unverified approvals and uncertain payments continue to block
checkpoint leave/resume. A simulated ASK becomes eligible only when its exact
approval has the broker callback, matching scope and resolution event. It remains
blocked after any DENY. Live/non-simulation ASK remains conservative until a
separate real authority connector is designed. No controller command resolves an
approval, supplies a receipt, or automatically resumes work.

Gate/approval checks run again at effect ACK and leave. A DENY after resume
dispatch rejects the applied ACK and preserves the hold. Only after the root
completes can its explicit dependent become resume-eligible. Applied command
history and runtime ACK semantics from Phase 3 are unchanged.

`GET /api/v1/runs/{run_id}/approvals` returns groups, request/disposition counts
and resolution provenance. `GET .../payments` returns observations, gate history,
attempts, receipt trust, structural delivery checks, simulation labels and current
control blocking. Both use stable root cursors, limit 50/default and 200/max.
Nested payment lists are capped at 100; total gate count and `has_deny` disclose
older blocking decisions. Read payloads are extensible objects in the additive
`contracts/payments-v1.openapi.yaml`; the original target contract stays frozen.

Evidence-linked `policy_warning` incidents distinguish unconfirmed settlement
from structural delivery failure. A trusted mock receipt resolves the former;
it does not erase a failed structural check or undo settlement. A later valid
delivery check can resolve that signature while retaining old evidence. Same
millisecond checks use persisted ingestion order rather than random UUID order.
An ordinary ASK or DENY alone is expected safety behavior and creates no new
failure diagnosis. The existing detector policy snapshot adds the payment-rule
version to its digest; original detector key families remain compatible.

## Demonstration and remaining scope

The new scenario executes the actual published SourceGuard, TrustGate, ASK,
DeliveryCheck and TrustLedger over an explicitly separate in-memory mock
transport. It creates no keypair, signature, wallet or network payment. Its
stable native ID reconciles one simulated effect. Broker callbacks run over
HTTP using their own secret. Causal Backpressure holds the root and dependent;
the independent branch completes; explicit approved/resume/receipt/root-complete
transitions then permit one dependent execution. DENY moves no mock funds.

The local SQLite database is not a cryptographic audit log. Broker authority is
only as trustworthy as its isolated simulation operator. No live blockchain
finality, production payment execution, human authentication, global spending
limits or task mandate is implemented. GateKeep402 is pre-existing work; this
adapter/broker and tests are new pre-event preparation. Comparative research
remains Phase 6; the next product slice is Phase 5 Studio.
