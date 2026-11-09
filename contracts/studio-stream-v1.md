# Studio read-only stream v1

`POST /api/v1/runs/{run_id}/stream-tickets` requires a scoped SDK/operator bearer
credential and returns `ticket`, `expires_at_ms`, `protocol`, `run_id`. A ticket
expires after 60 seconds, is single-use, and is invalidated by server restart.

Upgrade `GET /api/v1/ws/runs/{run_id}?after=<sequence>` with subprotocols
`["swarmcircuit.v1", "<ticket>"]`. Only `swarmcircuit.v1` is echoed. Missing/invalid
credentials, wrong run, replay or invalid cursor reject. Tickets never go in URLs.
The Studio Node server performs this exchange privately and relays only frames to
its exact-origin `/studio-ws/{run_id}` browser connection. The browser has no token.
Both relay and backend reject client messages (close 1008); this socket cannot
submit controls, approve, acknowledge, execute or replay a payment.

Server JSON frames:

```json
{"type":"snapshot_required","run_id":"<uuid>","cursor":42,"projection_version":67}
{"type":"notifications","run_id":"<uuid>","cursor":43,"projection_version":68,"notifications":[{"sequence":43,"notification_id":"<uuid>","run_id":"<uuid>","topic":"<persisted topic>","entity_id":"<uuid>","created_at_ms":1,"projection_version":68,"payload":{"snapshot_required":true}}]}
{"type":"heartbeat","run_id":"<uuid>","cursor":43}
```

Cursor is a durable monotonic per-run outbox sequence. A missing/future cursor or
retention gap sends `snapshot_required` at the current head. Notifications are
invalidation deltas, up to 100 per batch and five batches per second. No arbitrary
outbox payload is forwarded. Refetch canonical REST after invalidation/resync;
`projection_version` counts source events and trace spans, not a universal control
revision. Empty replay windows send no change frames; heartbeat is every ten
seconds. Retain the last processed cursor for reconnect and deduplicate IDs.
Database failure closes 1011. There is no exactly-once delivery guarantee.

Control submission remains the existing REST operator protocol; see
`control-v1.openapi.yaml`. The run command-history and sanitized source-evidence
reads are in `studio-v1.openapi.yaml`. Commands take effect only through validated
runtime ACKs. See `docs/decisions/0005-studio.md` for deployment/trust boundaries.
