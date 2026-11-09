# SwarmCircuit Studio

Local Next.js, TypeScript and React Flow workspace for understanding and reviewing
existing Python workflows. Start with **Overview → Explore the guided demo** to
see a useful result before connecting your own code. Requires Node 22.18+ and npm.

From the repository root:

```bash
make bootstrap
make init-local
make server
# Another terminal:
make studio-install
make studio
# http://127.0.0.1:3000/demo
```

For alternate ports:

```bash
make server PORT=18005
# Another terminal:
SWARM_API_URL=http://127.0.0.1:18005 make studio STUDIO_PORT=3300
# http://127.0.0.1:3300/demo
```

`make server` configures `SWARM_DEMO_API_URL` to the actual backend port. When
starting Uvicorn directly on an alternate port, set that trusted loopback origin
explicitly; its default is `http://127.0.0.1:8000`. It is never derived from browser
headers. `SWARM_API_URL` independently configures Studio's gateway destination.
The custom Node server reads root `.env` privately and binds to loopback. No
`NEXT_PUBLIC_*` credential is used. Restart after changing environment settings.

## Guided walkthrough

The `/demo` page prepares a quarterly sales brief using local reference notes and
a synthetic CSV. The default offline mode uses real SDK workers and checkpoints,
with no model calls. Optional live mode has a writer produce structured claims,
a separate reviewer inspect the actual draft and source facts, and at most one
repair using that feedback. Live mode requires an explicit review and permits
at most three provider calls. Configure `SWARM_MODEL_BASE_URL`, `SWARM_MODEL_NAME`
and `SWARM_MODEL_API_KEY` privately on the server. Neither mode makes payments or
changes production permissions.

1. Start the walkthrough and read the public findings as they complete
   independently. Four dependent tasks wait quietly for sample dataset access.
2. Review sample access, supply a reason, then approve or deny. Only this
   walkthrough's mock dataset permission can change.
3. Approval lets the guarded branch analyze and validate the data, then publish
   the final brief. Denial retains the public findings and executes no protected
   steps. Read or download the actual output documents.
4. Open the workflow map for deeper inspection. If operator pauses were added,
   review and resume them explicitly; permission approval does not remove them.

Live validation depends on the writer task. Typed quantitative claims are checked
against recomputed sample data before publication; arbitrary rationale remains
unverified evidence. A repaired draft receives deterministic checks without a
second model review. Writer and reviewer use the same configured provider.
Draft, feedback, repair and check artifacts remain available, including failed
runs. Provider failure cannot silently become a successful offline output.

The [live handoff guide](../../docs/LIVE_HANDOFFS_2026-11-08.md) covers the current
flow, retained artifacts, API and source-check boundaries.

The walkthrough is bounded. A server restart records interruption rather than
pretending workers survived. Recorded results remain readable. It demonstrates
permission-aware workflow behavior, not comparative AI safety or model savings.

## Workspace and evidence

Overview counts cover the project, while workflow tables retain explicit
pagination and loaded-page search. Diagnostics are hidden by default and can be
included with a filter. Current connected control hosts are counted separately
from recorded running/waiting lifecycle states. A control host is not an agent
count. Workflow summaries show completed/total progress, permission dependencies,
current connectivity and a useful next action.

The same-origin gateway permits project-scoped reads, validated single-task
controls, preview-bound group pauses, and the isolated demo's start/permission
routes. The owned live-demo route can make the reviewed bounded model calls;
the gateway cannot launch research collection, resolve production approvals,
acknowledge a runtime or forward arbitrary upstream writes. Group history is
server-discovered and works without an inherited local intent. Queued/dispatched
requests remain unconfirmed until a matching host/session/epoch ACK. Uncertain
submissions retain their original idempotency key and reconcile without automatic
replacement writes. Browser storage contains intent identifiers and recently
opened workflow IDs/names, never credentials or recorded reasons.

Payments and ordinary approval decisions remain read-only. Only the explicitly
labeled walkthrough has a sample-permission decision. Artifacts use an allowlist
of output slugs and safe Markdown download headers. The read-only WebSocket relay
keeps short-lived backend tickets server-side; canonical REST snapshots determine
state.

The graph has a list alternative, explicit declared edges and a dedicated ELK
layout worker. Canvas limits remain 200 nodes/400 edges; the list retains loaded
nodes. Timelines are virtualized and older windows load on request. Small screens
default to the list. Custom graph/timeline navigation shortcuts remain removed;
ordinary native keyboard and focus behavior remains available.

Experiments retain the existing scenario/metric views, trial evidence and CSV
exports. Exact aggregates now persist across backend restarts and prepare after
completed recording, avoiding repeated cold bootstrap work. Failed trials remain
failed. Research paper work is outside this UI/backend delivery. Research model
collection remains a separate explicitly invoked CLI operation.

## Checks and production preview

```bash
make studio-check
# After building, with the backend running:
SWARM_API_URL=http://127.0.0.1:18005 STUDIO_PORT=3300 npm --prefix apps/studio start
# Opt-in protocol checks with both services running:
cd apps/studio
STUDIO_URL=http://127.0.0.1:3300 SWARM_API_URL=http://127.0.0.1:18005 npm run test:integration
```

`studio-check` runs Prettier, strict TypeScript, **18 Node unit cases** and the
production Next build. Integration checks exercise the live HTTP/WebSocket gateway
separately. See [the workspace improvement report](../../docs/WORKSPACE_IMPROVEMENTS_2026-11-06.md)
for backend validation, actual SDK walkthrough outcomes and browser evidence.
The later [reviewer repair pass](../../docs/REVIEWER_PASS_2026-11-06.md) covers the
single shared permission, direct resume controls and lost-response recovery.

This is a trusted single-user local workspace, not remote multi-user authentication
or isolation from malicious hosts. `SWARM_OPERATOR_TOKEN` enables reviewed writes;
`SWARM_STUDIO_READ_ONLY=true` disables them, including demo actions. Runtime
control depends on cooperative hooks before supported work. The custom server is
required for the socket relay; stock `next start`, static export and standalone
deployment are not supported. The prior
[Studio decision](../../docs/decisions/0005-studio.md) and
[research amendment](../../docs/decisions/0006-research.md) retain historical context.
