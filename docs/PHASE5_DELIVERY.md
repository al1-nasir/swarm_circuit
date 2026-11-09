# Phase 5 delivery — Studio

Implemented November 2, 2026; final browser verification and handoff completed
November 4, 2026. All work precedes the November 6–8 hackathon and is disclosed as
pre-event preparation. No comparative experimental results are claimed.

## Delivered behavior

- Local Next.js App Router/TypeScript/Tailwind Studio with React Flow task and
  agent projections, accessible node list, loaded-scope workflow filters and
  explicit cursor pagination. Graph movement changes layout only.
- Windowed timeline with keyboard selection, source/ingest timestamps, exact
  nanosecond strings and trace correlation. Incident inspector links persisted
  diagnoses to affected tasks and sanitized source evidence, preserving uncertainty.
- Read-only payment/approval views retain exact amounts, DENY guards, simulation
  labels, receipt provenance and structural delivery limits. There is no approval,
  settlement, payment execution or retry action in Studio.
- Reviewed hold/resume with a required reason, explicit task/checkpoint/version/
  epoch context, dependency impact and backend revalidation. Queued/dispatched
  remains pending. Applied requires a matching canonical runtime ACK. Uncertain
  submissions retain their original idempotency key and reconcile durable history.
- Server-side local credential gateway, fixed allowlist, exact-origin write/socket
  guards, read-only configuration, no-store API responses and frame protection.
  SDK/operator credentials and backend upgrade tickets do not reach the browser.
- Read-only WebSocket invalidations with durable per-run sequences, single-use
  expiring tickets, reconnect replay and canonical snapshot recovery on gaps.
  Last-good snapshots remain visible during outages; disconnected controls disable.
- Responsive shell, narrow-screen list-first view, dismissible inspector, keyboard
  modal behavior and reduced-motion styling. Experiments explicitly shows no
  measurements and disables CSV export until Phase 6.
- Additive migration 004 (41 tables total), version 0.5.0 Python distributions,
  locked frontend dependencies, Studio REST/socket supplements, setup guide,
  interactive mock checkpoint and frontend CI job.

Original DOCX specifications, original SQL and frozen OpenAPI remain unchanged.
See [decision 0005](decisions/0005-studio.md),
[Studio setup](../apps/studio/README.md),
[Studio REST supplement](../contracts/studio-v1.openapi.yaml) and
[socket protocol](../contracts/studio-stream-v1.md).

## Executed verification

| Check | Actual result |
| --- | --- |
| Final Python `make check` | **129 passed**; Ruff lint/format and mypy passed for 32 source files |
| New backend cases | Five cases cover ticket scope/replay/expiry, live/reconnect sequence replay, retention/future-cursor recovery, transaction rollback, read-only socket, scoped paginated commands and source evidence |
| Frontend `npm run check` | Formatting, strict TypeScript, **8 unit cases** and optimized production build passed, including the final source-inspector race fix |
| Unit behavior | Explicit dependency closure, cycle-safe layout, nanosecond precision, matching ACK labels, loaded-page refresh/cursors, gateway route/origin guards and read-only configuration |
| Production HTTP/WebSocket integration | **4 passed** against the actual Node gateway and FastAPI backend: credential isolation/scope, cross-site/privileged-write rejection, durable invalidation/reconnect and unrelated-origin upgrade rejection |
| Browser control flow | Actual review/hold/resume through Studio; both commands applied with matching runtime ACKs; independent branch completed while held; exactly one protected mock action; healthy telemetry |
| Browser evidence | Resolved incident → persisted source event; simulation approval → resolution source; source deep-link survives reload; span selected with Home/Enter and exact ns shown |
| Browser payment visibility | Historical simulated settlement/receipt and blocked DENY displayed; payment/approval actions remain read-only |
| Browser rendering | Task/agent projections, phone task list, tablet inspector and normal desktop graph inspected; checked document width equals scroll width in observed layouts |
| Experiments | No measurements, explicit Phase 6 explanation and disabled trial CSV export verified |
| Backend outage in browser | Stopped the verification backend: all six graph nodes and run identity remained visible; Reconnecting and disabled-control/resync explanation appeared |
| Browser console | No warnings/errors in the final production navigation session |
| Production headers | HTTP 200; nosniff, same-origin referrer policy, DENY framing and CSP frame-ancestors none verified |
| Browser asset scan | Both actual configured token values absent from `.next/static`; no secret values printed |
| Packaging | SDK/server 0.5.0 source/wheel builds passed; wheel imports outside checkout, packaged schema 004, all 41 tables, foreign keys, Studio routes and one-use tickets passed |
| Compatibility | Existing 124 backend cases retained; original contracts/root and packaged migration checks passed |

Local checks used Python 3.12.3, uv 0.13.6 and Node 22.23.4. Browser QA used the
in-app browser. Responsive viewport overrides were exercised; its rendered CSS
width differed from requested dimensions in some captures, so these checks are
functional responsive observations rather than a pixel-exact device certification.
An interrupted preview session was restarted and final production navigation was
verified. No performance benchmark, remote CI execution, accessibility certification
or multi-browser coverage is claimed. The added CI job runs frontend checks on
Node 24; the existing Python matrix remains 3.11/3.12.

## Recorded engineering evidence

The interactive Studio run was `91d3e79e-6dad-4f27-866c-b2ed3a3ea6d6`.
Protected task: `95026d88-c1a7-4088-9721-f67ef6dcf8ec`.
Hold: `cb42388f-deb9-475d-884c-e7674862bc53`.
Resume: `88d87502-c5fc-4c84-a53d-17d8ecfddaf4`.
Both commands retain one matching applied ACK. The example reported
`mock_action_executions=1`, `independent_completed=true` and
`telemetry_degraded=false`. Runtime expiry later disables new controls without
erasing historical ACKs. Human coordination delayed this engineering demo long
enough for a stall signature; it subsequently resolved. This is not a benefit trial.

The explicitly simulated Observe regression was
`1f164ac6-56ff-43cc-8c53-564622929712`: six tasks, six agents, five explicit
dependencies, pending approval and completed independent branch. Approval-storm,
retry-amplification and cascade signatures were observed and later resolved as
windows expired. The UI preserves their evidence and resolution reasons.

The payment view reused Phase 4 run `5bb36eed-233c-4170-baf1-62cb87b8bcd0`.
Reading its stored mock receipt did not enable the broker or execute a payment.
New protocol tests create clearly labelled simulation verification runs.

Screenshots are local ignored artifacts under `artifacts/`: `studio-final.jpg`,
`studio-control-history.jpg`, `studio-desktop.jpg`, `studio-tablet.jpg` and
`studio-mobile.jpg`. Earlier overridden-viewport captures may be clipped by the
preview surface; `studio-final.jpg` captures the normal browser surface. Source
events, ACKs and callbacks remain in the ignored SQLite database; no credentials
or live-payment claims are included in these artifacts.

## Run and verify

```bash
make bootstrap
make init-local
make studio-install
make server
# Separate terminal:
make studio
# http://127.0.0.1:3000
# Optional reversible mock checkpoint, while both services run:
make demo-studio
```

For an occupied backend port use `make server PORT=18005` and
`SWARM_API_URL=http://127.0.0.1:18005 make studio STUDIO_PORT=3300`.
`SWARM_STUDIO_READ_ONLY=true` disables operator submissions. The custom Node
server reads root `.env` privately. Restart it after changing configuration.

```bash
make check
make studio-check
make studio-contract
# Production preview after the frontend build:
npm --prefix apps/studio start
# Optional protocol tests against running services:
cd apps/studio
STUDIO_URL=http://127.0.0.1:3000 npm run test:integration
```

The owned loopback verification servers are stopped at handoff. Run the commands
above to reopen the dashboard; the database and source are retained.

## Limits and next phase

This is a local single-worker MVP with trusted cooperative SDK hosts. The gateway
uses the local workspace's configured role; it is not a multi-user identity or
remote production authorization service. Control cannot stop arbitrary code that
has passed its supported checkpoint, and runtime ACKs depend on honest hosts.
No global exactly-once execution, external-effect firewall or cryptographic audit
log is claimed. Long histories require explicit pagination; the canvas is capped
at 200 nodes/400 edges with a full loaded-node list alternative. Automated retention
and live human/payment authority connectors remain outside this phase.

Next is Phase 6: matched-seed baselines, independent simulation outcome records,
raw trial data, uncertainty and scientific evaluation. No fabricated chart or
comparative claim has been added ahead of that work.
