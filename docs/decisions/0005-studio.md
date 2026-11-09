# 0005 — Local Studio, canonical controls and read-only streaming

Date: November 2, 2026. Status: implemented, pre-event preparation.

## Scope and reconciliation

Phase 5 implements the supplied Studio flow with Next.js/TypeScript/Tailwind and
React Flow: workflows, task/agent graph, timeline, incidents/source evidence,
payment/approval visibility, reviewed hold/resume and reconnect. Existing SDK,
controller, detector and payment semantics remain authoritative. No graph drag
changes orchestration; inferred edges never grant control authority. There is no
payment approve/retry action, cancellation or automatic recovery. Experiments
explicitly await Phase 6 measurements. Original DOCX, SQL and OpenAPI bytes remain
frozen; only additive migration 004 and supplementary documentation are introduced.

## Local credential gateway

A custom Node server loads root `.env` privately and binds 127.0.0.1. Browser reads
use allowlisted same-origin routes scoped to one configured project. The only
forwarded write is the existing operator control submission. Runtime credentials,
ACK, broker callbacks, ingestion and backpressure application are not proxied.
Operator writes require an exact local Origin and loopback Host; cross-site fetches
and DNS-rebinding hosts reject. Read-only mode blocks before contacting upstream.
The upstream URL must itself be loopback. Responses are no-store and frame embedding
is disabled. Tokens, reasons and tickets are excluded from browser storage/bundles.
Intent storage contains only stable request/run/task IDs, kind and creation time.

This is a trusted single-user local workspace. Anyone able to access this local
browser/service has that workspace's configured read/operator role. Origin guards
are not user authentication. Remote deployment, multi-user authorization and
hostile local-process isolation require a separate design. Dependency versions are
locked; there are no CDN fonts. Production must use `node server.mjs`, not Next's
stock server. Explicit page routes avoid claiming the socket relay URL as an App
Router catch-all route. This also means no static export/standalone deployment.

## Durable stream and canonical snapshots

Migration 004 adds `ui_stream_heads` and `ui_stream_notifications` (41 tables total).
A trigger assigns monotonically increasing per-run sequence numbers atomically
with each existing outbox insertion. Backfill orders prior records by timestamp
and ID. Heads survive notification retention; deleted cursors/gaps cause resync.
Root and packaged migrations are digest checked. No domain state is changed by
notification delivery.

The Node relay mints a run-scoped one-use 60-second ticket using the SDK read role.
The backend accepts it as the second WebSocket subprotocol, echoes only
`swarmcircuit.v1`, and invalidates outstanding tickets on restart. Long-lived tokens
never enter URLs. The browser connects same-origin without receiving even the ticket.
The relay checks Origin and accepts no browser mutation messages. Backend streaming
also closes on a client message. Used-ticket storage is bounded and expiry-pruned.

Outbox invalidations are batched at most five times per second, up to 100 records.
They contain IDs/topics/sequence and a snapshot-required marker, not arbitrary
outbox payloads. The client refetches REST, deduplicates sequence numbers and ignores
stale run generations. A missing/future/retained-gap cursor requests a fresh snapshot.
Ten-second heartbeats and periodic REST refresh disclose loss and support recovery.
Last successful data remains visible during outages; controls require a connected,
fresh snapshot. Selection/deep-links survive reconnect. This is an invalidation
stream, not exactly-once delivery or an atomic multi-route REST snapshot.

## Reviewed effects and uncertainty

The inspector shows eligibility, checkpoint owner, task version and fencing epoch.
A native modal reviews the exact target, explicit downstream impact and required
reason. It traps focus, supports Escape and restores focus. Changed context invalidates
the review. Backend checks remain definitive even after client revalidation.
Queued/dispatched are requests; applied requires canonical history with a matching
runtime session/epoch ACK. A lost response retains the original idempotency key and
reconciles durable command history; it never silently submits a new key. Historical
ACKs remain history after runtime expiry and do not claim a currently parked task.
Observe mode, unavailable/expired boundaries and disconnected views disable controls.

## Bounded rendering and evidence

Run search/filter/summary is explicitly limited to loaded pages. Timeline rendering
uses a bounded window, keyboard selection, ID deduplication and exact BigInt ns
arithmetic. User-loaded mutable command/payment/approval pages refresh as a window.
The canvas caps nodes/edges and offers a full loaded-node list. Cycle-safe layout
wraps long chains visually without changing dependency semantics. Tablet/mobile
layouts hide the inspector until selected; phones default to the list.

Incident source links resolve a run-scoped event/span lookup and show only already
sanitized metadata, source/ingest time and trust class. Simulation runs/receipts,
SDK observations, self reports and derived diagnoses retain distinct labels. A
resolved detector signature is not task success or human authorization. Exact
payment decimals are preserved; structural delivery is not semantic truth.

## Validation and sources

See [Phase 5 delivery](../PHASE5_DELIVERY.md) for actual test and browser results.
No load benchmark or accessibility certification is claimed. Local implementation
consulted current official documentation for [Next installation](https://nextjs.org/docs/app/getting-started/installation),
[Next custom server](https://nextjs.org/docs/app/guides/custom-server),
[React Flow](https://reactflow.dev/learn) and
[Tailwind with Next](https://tailwindcss.com/docs/installation/framework-guides/nextjs).
React Flow's stylesheet is imported after Tailwind; custom-server limitations are
retained rather than implying stock deployment support.
