# Phase 3 control protocol

November 2, 2026. Preserve original SQL/OpenAPI byte for byte. Apply a separate
002 migration and publish an additive control contract supplement. This implements
SC-018–022 through cooperative reversible checkpoints, never trace enforcement.

Registration uses the scoped SDK credential and a random stable client nonce.
Runtime calls use a separate expiring session credential; operator writes require
the operator credential. Credential hashes, nonce hashes, task ownership and
checkpoint/command context require new tables because the approved schema lacks
these fields. No secrets are stored in telemetry or returned by read APIs.

The SDK declares and enters a reversible checkpoint before execution. Hold ACKs
are valid only at that owned active boundary. A leave handshake atomically checks
pending commands and prerequisites before releasing it. Resume is subject to the
same checks and cannot resolve human approval or payment uncertainty. Capability,
task version, session epoch, boundary identity and TTL are checked at submission,
dispatch and ACK. There is no interrupt/rollback of in-flight work.

Registration nonce replay is idempotent while the session is current. New sessions
fence previous epochs for the same runtime key. On heartbeat loss, queued commands
expire without dispatch; dispatched commands become unknown. Restart invalidates
old connected sessions and active boundaries. Held/uncertain boundaries are never
silently adopted by a replacement runtime. ACK result `failed` is conservatively
unknown. Duplicate commands/ACKs have one effect; conflicting payloads reject.

Durable command GET, scoped session/checkpoint reads, enter/leave, and bounded
backpressure endpoints supplement the original contract. Cancellation and automatic
irreversible recovery are deferred. A separate SDK presentation boundary can
coalesce identical pending approval notifications; it cannot grant approval.

Backpressure computes explicit reverse dependency closure from a pending approval,
previews eligible active checkpoints, and applies at most the configured bound only
when the operator explicitly requests application. It does not invent approval,
resume unknown effects, or include independent branches. Auto-action is off.

Phase 4 will supply the optional GateKeep402 observer and separately trusted mock
approval broker. This phase exposes no generic approval-resolution API. Tests may
use separately labelled service fixtures to simulate an authoritative resolution.
Research comparisons remain Phase 6; these checks establish engineering behavior.

## Authority and evidence

The trusted host possesses the project SDK token. This is provisioning authority,
not an untrusted agent secret. Registration returns `sc_rt_` plus an HMAC-SHA256
of the versioned session UUID and caller nonce under that SDK token. Only its
SHA-256 digest and the nonce digest are stored. This permits lost-response replay
without storing plaintext credentials. The random nonce must remain private to
the host. Neither SDK nor operator credentials can ACK a runtime command; a
session token cannot submit an operator command or read arbitrary project data.
The single-project local credential model is not a multi-tenant identity provider.
Use TLS when placing the service beyond loopback.

The default credential TTL is 30 minutes and the lease is 15 seconds. Heartbeats
refresh only the lease. Expiry cannot be reversed by replaying registration. A new
nonce increments the epoch and invalidates old connected sessions for that runtime
key/run. Server restart invalidates connected sessions even if their TTL remains.
Session close stops SDK heartbeats; server expiry then records disconnection.

Authenticated runtime audit events use the existing `sdk_observation` trust class
and the separate `runtime` telemetry source kind. They attest to the cooperating
host's report; they do not independently prove external effects. Server command,
session and policy transitions use `derived`. Plain SDK lifecycle events cannot
overwrite task state while a nonreleased checkpoint exists. Original telemetry
and raw ACK details cannot manufacture approval, settlement or command success.
ACK free-text details are hashed for replay conflict detection and not retained.

## Boundary and failure semantics

A checkpoint is an execution barrier, not a durable promise to remain available
indefinitely. The SDK first enters it, polls commands and requests leave. Leave
revalidates prerequisites and guards atomically with command submission. A hold
that wins that race parks the caller; a leave that wins releases the point and a
later hold rejects. A pending prerequisite or human approval keeps the boundary
available. Hooks cannot interrupt actions already in flight. The optional SDK
`on_enter` callback supports coordination in the bounded local demo.

Task ownership is exclusive per run/task. Each boundary has a generation and
identity. Enqueue, dispatch and applied ACK check the live session/epoch,
capability, task version, owner and boundary. Resume also checks prerequisite
completion and verified approval/payment guards at all effect boundaries.
The task version and parked/available state change in the same transaction as
the matching ACK, command state, audit event and outbox. A persistence failure
rolls them all back. Maintenance commits expiry separately before requests so a
rejected stale request cannot roll back an expiry transition.

Default command deadline is 30 seconds. Undispatched expired commands become
`timed_out`; dispatched commands become `unknown`, blocking the boundary. A
failed ACK is also unknown. A rejected ACK reports no applied control effect.
Already applied ACKs remain historical after disconnect; their checkpoint/session
must be consulted for current uncertainty. There is no force-clear/adopt endpoint.
The host must stop affected work for external reconciliation; this phase does
not provide seamless process recovery or renew credentials around an active point.

The SDK invokes local effects only inside its blocking checkpoint and reconciles
lost ACK responses against durable command GET. Its command and notification
caches are in memory. There is no persisted host execution journal or claim of
exactly-once external work across process crashes. `ControlError` must not be
caught and ignored by the host. Irreversible hooks are rejected.

## Causal Backpressure and notification coalescing

The fixed `causal-backpressure-v1` policy traverses explicit reverse dependencies
from the pending approval's related task, including that root. It records eligible
owned active points and skipped reasons. Independent branches are excluded. An
operator requests application with a stable idempotency key. The default bound
is 20 eligible targets; exceeding it rejects the whole request before any child
command is inserted. No partial truncation is presented as complete containment.
Child holds and the parent request's policy/version/bound/target snapshot commit
atomically. This control policy snapshot is retained in `control_policy_requests`;
it does not reuse the detector-policy table or enable its auto-apply flag.

The parent's `applied: false` means it is a request, not runtime effect proof.
Each child's durable state records its own outcome; replays refresh those child
states. Existing unsupported or disconnected branches are explicitly skipped.
Auto-application, auto-resume and research baseline comparisons remain deferred.

Approval presentation claims are unique per run/approval. A stable original claim
can be replayed while claimed; other request events are marked coalesced. The SDK
marks its callback locally uncertain before invocation and never retries an
uncertain callback. Pending approval and original request evidence remain intact.
Notification coalescing does not remove a detector's historical request storm.

## Contract supplement and deferred behavior

`contracts/control-v1.openapi.yaml` is generated from implemented control routes
with `scripts/export_control_contract.py`. It adds checkpoint enter/get/leave,
sanitized session listing, durable command GET, policy preview/apply and approval
presentation endpoints that the frozen target contract did not specify. It
documents request/error models, core command responses and credential roles.
Some read/policy response payloads remain extensible objects in OpenAPI; their
fields and semantics are documented in the README and this decision.

Safety tightenings are explicit: `task_id` is mandatory for commands; registration
accepts only implemented hold/resume capabilities; nonce, keys and free-text input
have bounded lengths. Cancel and command-based `coalesce_approval` capabilities
from the target schema are rejected. Notification coalescing uses its separate
presentation boundary, never a generic authorization command. The target SQL and
OpenAPI remain byte-for-byte preserved; migration 002 adds six context tables.

No public approval resolution exists yet. An approved record needs an independent
verified source before release; SDK self-report is insufficient. Any historical
ASK/DENY payment gate, submitted attempt or uncertain outcome conservatively
blocks release. Phase 4 must define external reconciliation without replaying an
uncertain payment. GateKeep402 remains optional and separate; this phase installs
no payment signer, broker, global budget or task-mandate enforcement.
