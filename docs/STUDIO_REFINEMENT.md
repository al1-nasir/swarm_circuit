# Studio dashboard refinement — 4 November 2026

The approved revision uses graphite navigation (`#222521`), ivory work surfaces
(`#f4f3ee`, `#fffefa`), restrained borders and semantic colors only for evidence
states. It builds on the [reviewed Figma structure](../design/review-2026-11-04/RESEARCH_AND_HANDOFF.md)
with the user's subsequent two-color, asset and mouse-first navigation changes.

## Shipped behavior

- Open workflow document tabs remember up to eight workflows locally; they navigate,
  close and restore after reload. Workspace and workflow section navigation remain
  separate. No command palette or custom keyboard shortcuts are added.
- Run details contain task/agent counts, open findings, pending approvals and runtime
  context. These facts no longer compete with the graph or masquerade as actions.
- Graph, Timeline, Incidents, Approvals, Payments and Controls are separate sections.
  Task and agent projections, list search and the contextual inspector are retained.
- Task categories use official Phosphor duotone assets. Setup/integration areas use
  actual Python, OpenTelemetry and SQLite marks. Files and licenses are local in
  `apps/studio/public/assets`; their source and attribution are documented there.
- ELK calculates layered orthogonal paths in a dedicated browser worker. Rounded
  connectors run prerequisite to dependent for `depends_on`, without changing the
  declared relationship or its inspector evidence. Mouse pan, zoom, fit, a minimap
  for graphs over four nodes, and a complete loaded-node list support exploration.
  The canvas retains its 200-node/400-edge bound and synchronous layout fallback.
  A selected task opened by deep link is framed at a readable zoom.
- Payments use an aligned table with selected receipt/gate detail. Approvals have
  their own scope disclosure and external-authority evidence. Neither UI can pay,
  approve, release or retry an effect.
- Custom search/timeline key handlers and graph keyboard actions are removed.
  Standard browser focus and native button/link behavior remain available.

## Reliability and research decisions

1. The old trailing refresh debounce could be postponed continuously by a busy
   invalidation stream. A fixed 250 ms window now coalesces events without moving
   the first refresh deadline. Canonical REST snapshots still determine state.
2. The Node WebSocket relay caps pending output at 1 MiB. Slow consumers close with
   code 1013 and reconnect/resync instead of accumulating an unbounded buffer.
   This uses [`ws.bufferedAmount`](https://github.com/websockets/ws/blob/master/doc/ws.md).
3. SQLite's existing `Database.read()` already owns a read transaction. A new
   concurrent-commit regression verifies that stream head, version and rows share
   its snapshot. A redundant nested `BEGIN` found during validation was removed;
   there is no new schema or parallel writer. See [SQLite transactions](https://www.sqlite.org/lang_transaction.html).
4. [React Flow's ELK port example](https://reactflow.dev/examples/layout/elkjs-multiple-handles)
   supports the routing approach. Each node has fixed input/output ports and the
   heavy engine stays off the main rendering thread. Selection does not relayout
   topology, and user dragging falls back to local smooth-step edge drawing.

Visual references researched in the earlier handoff include Apple's tab guidance,
Linear's navigation hierarchy, n8n's node canvas, Excalidraw endpoint bindings,
Google Cloud execution details, HighLevel's canvas and Attio record inspection.
These patterns guide the information architecture; this is not a clone of their
private dashboards. Current technical sources informed the concrete changes above.

## Validation

- Backend: Ruff, format, mypy (32 source files), **130 tests passed**.
- Frontend: Prettier, TypeScript, **11 unit cases passed**, production webpack build.
- Real HTTP/WebSocket protocol checks: **4 passed**, covering credentials, scope,
  origin/route guards, durable invalidations and reconnect replay.
- BrowserAct on the production app: graph worker/routes, node/source inspection,
  timeline click selection, distinct approvals/payments, selected payment details,
  document tabs, run details, narrow-screen list layout and native review dialogs.
- Reversible simulation `c8268215-3b96-45e6-8b2e-a4bbd3bf14d3`: reviewed hold and
  resume both received matching runtime ACKs; independent task completed while held;
  mock action executed **once**; telemetry degradation was false. No payment ran.
- The final centered-dialog simulation `f88933d5-5e1b-49ed-b462-cee24ebfda72`
  independently repeated hold/resume with two matching ACKs and one mock action.
  Control-history lifecycle times are displayed in three aligned columns.
- Final visual evidence and viewport checks are recorded in [design-qa.md](../design-qa.md).

## Integration boundary

This remains a trusted local workspace with loopback services and server-held
credentials. A remotely deployed multi-user product still needs identity/session
management, authorization per user/project, deployment-specific origin configuration,
audit retention and measured load testing. No remote deployment, authentication
system, payment authority, or performance benchmark is claimed by this revision.
The original documents, frozen schema/contract artifacts and Phase 6 scope remain
unchanged. The earlier Phase 5 delivery report is historical; this report records
its subsequent UI refinement.
