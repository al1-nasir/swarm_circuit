# SwarmCircuit dashboard — design proposal

Prepared November 4, 2026. Design review only; the application UI has not been
changed. The existing server was started to inspect current workflow, payment
and timeline pages. Browser research used the requested BrowserAct CLI.

## Open the design

[Workflow overview in Figma](https://www.figma.com/design/vu4V38F93GDNxAInQQM0be?node-id=6-135).

| Editable review frame | Figma node | Review focus |
| --- | --- | --- |
| Workflow overview | [6:135](https://www.figma.com/design/vu4V38F93GDNxAInQQM0be?node-id=6-135) | Two tab levels; quiet run header; clear dependency direction |
| Selected task | [6:405](https://www.figma.com/design/vu4V38F93GDNxAInQQM0be?node-id=6-405) | Contextual inspector, dependency context, unavailable-control reason |
| Payment evidence | [6:716](https://www.figma.com/design/vu4V38F93GDNxAInQQM0be?node-id=6-716) | Scannable table, exact amount, selected receipt/delivery detail |
| Timeline/source | [6:974](https://www.figma.com/design/vu4V38F93GDNxAInQQM0be?node-id=6-974) | Event hierarchy and source provenance, contextual metadata |
| Phone task list | [6:1254](https://www.figma.com/design/vu4V38F93GDNxAInQQM0be?node-id=6-1254) | List-first view and compact section navigation |

The frames are editable text, vectors, component instances and auto-layout
containers, with semantic token bindings. They are static design compositions,
not a running product or a wired Figma prototype. Inter and JetBrains Mono match
the existing project. Desktop frames are 1440×960; phone is 390×844. A reusable
four-state task component is on the same page, below the review screens.

The current Starter plan permits one variable mode. This proposal implements
Light only; no Dark-mode completeness is claimed.

## What changes

Two tab levels have distinct jobs. Open workflow runs live in document tabs above
the run identity. Graph, Timeline, Incidents, Approvals, Payments and Controls are
peer sections below it. The persistent sidebar navigates the workspace. Task/agent
projection belongs inside the graph toolbar, not beside the section tabs.

The header keeps the run name, one observed-state label, mode and simulation
metadata. Task/agent totals live in the projection switch and Run details.
Runtime ownership/health belongs in Run details and the selected task. Connection
freshness belongs in a small status bar. Zero open findings does not compete with
a pending approval. Counts on the section tabs describe records, not severity.

The default graph uses all available space until a task is selected. Dependency
arrows follow prerequisite → dependent as a presentation convention; the underlying
relation kind and evidence do not change. The independent branch is visibly
separate from the approval-gated path. Port handles indicate declared relationships,
not editable orchestration. Show a relationship label on selection/hover rather
than repeating it on every wire. Preserve keyboard-accessible list navigation.

Payments use aligned columns for destination, exact amount, decision, outcome,
provenance and owning task. Selection opens detail; it does not expose approve,
retry or settlement actions. Approvals become their own peer view rather than a
second large card below payments. Control history remains durable requests and
validated ACK evidence; button placement must not imply an already applied effect.

## Research and adaptation

| Primary reference | Observed guidance / pattern | Proposed use |
| --- | --- | --- |
| [Linear: 2026 interface refresh](https://linear.app/now/behind-the-latest-design-refresh) | Reduced icon emphasis, quieter dividers, compact tabs and consistent hierarchy | Neutral chrome, one selected accent, fewer competing status treatments |
| [Linear: redesign process](https://linear.app/now/how-we-redesigned-the-linear-ui) | Cohesive sidebar/header layers and explicit behavior definitions | Separate workspace navigation, document tabs and section tabs |
| [Apple: tab bars](https://developer.apple.com/design/human-interface-guidelines/tab-bars) | Tabs navigate peer destinations; toolbars contain actions; labels remain available | Stable section navigation, controls outside the tab strip, labelled empty states |
| [n8n: nodes](https://docs.n8n.io/build/understand-workflows/workflow-components/work-with-nodes) and [n8n product canvas](https://n8n.io/) | Recognizable node units, ports, canvas controls and node-specific details | Compact task identity, restrained connectors and a selected-node inspector |
| [Excalidraw: arrow bindings](https://docs.excalidraw.com/docs/@excalidraw/excalidraw/api/excalidraw-element-skeleton) | Explicit source/target bindings and optional arrow labels | Endpoint clarity and selective relation labels; no hand-drawn styling required |
| [Google Cloud execution results](https://docs.cloud.google.com/workflows/docs/access-execution-results) | Execution identity, summary/steps/logs navigation and inspectable outcomes | Separate run context from graph, timeline and evidence views |
| [HighLevel workflow builder](https://ideas.gohighlevel.com/changelog/workflow-new-workflow-builder-labs) | Infinite canvas, zoom, fit-to-screen and minimap | Essential navigation controls; minimap conditional on graph size |
| [Attio record pages](https://attio.com/help/reference/managing-your-data/records/create-and-view-records) | Record tabs plus selected-record previews next to a table | Payment selection and contextual inspection without leaving the current view |
| [Adaption Labs](https://adaptionlabs.ai/) | Light surfaces, restrained text hierarchy and generous separation, observed on public homepage | Tonal restraint; the marketing page is not evidence of an authenticated dashboard |

Screenshots of Linear, n8n, Excalidraw and Adaption were captured locally. Google,
HighLevel and Attio references were official documentation, not authenticated
product audits. These are design recommendations informed by the sources, not
claims of affiliation or pixel-for-pixel reproduction.

## Current-product audit

1. Workflow — functional, visually crowded. The status/count row duplicates the
   empty inspector summary. Small labels and long reverse-routed dependencies
   make the primary graph harder to read. Evidence: `01-current-workflow.png`.
2. Payments — functional, weak scanning hierarchy. Tall intent cards repeat
   badges and qualification text; the approval section falls beneath them. Exact
   values and trust distinctions must remain visible in the redesign. Evidence:
   `02-current-payments.png`.
3. Timeline — functional, low reading density. Repeated evidence pills, small
   text, table dividers and the default empty inspector consume attention.
   Evidence: `03-current-timeline.png`.

Accepted captures were opened and inspected. These observations do not establish
accessibility compliance; keyboard, focus, screen-reader and zoom testing belong
to implementation verification.

## Production implementation proposal after visual approval

Keep the existing Next.js, React, TypeScript and React Flow application. The UI
redesign does not justify replacing the backend, changing evidence classes or
rewriting the cooperative controller.

Use React Flow for the rendering/selection surface. Evaluate ELK layered layout
in a worker for deterministic ranks, explicit ports and orthogonal routes. React
Flow separates rendering from layout and documents the available layout engines:
[official layout guidance](https://reactflow.dev/learn/layouting/layouting).
Stable domain IDs must remain separate from layout positions. Do not re-fit or
re-layout on every heartbeat; preserve the user's viewport and selected task.
Test forks, merges, cycles, long labels and disconnected components. Use an
accessible list and bounded rendering for large workflows. A tidy six-node mock
is not evidence of production layout performance.

Use React Aria's unstyled Tabs as the proposed behavior foundation, styled with
console tokens. It supplies semantic relationships and keyboard behavior:
[React Aria Tabs](https://react-aria.adobe.com/Tabs). Follow the
[W3C tab pattern](https://www.w3.org/WAI/ARIA/apg/patterns/tabs/) for arrow keys,
Home/End, focus and activation. Prefer manual activation for tabs that fetch
non-preloaded data. Document tabs additionally need close/focus recovery and
stable per-run selection. On narrow screens, preserve all run sections through
horizontal scrolling or a labelled section picker; the current phone design
shows the initial visible portion, not a requirement to remove other sections.

Generate or maintain typed clients against the **implemented** additive contracts,
not unsupported endpoints in the frozen future target. Retain the local credential
gateway; never put SDK/operator tokens in browser storage. Keep request cancellation,
stale-generation rejection, last-good snapshots, explicit errors and canonical
resync. Changes to a selected record should preserve its scroll/focus context.

A production integration needs deployment-appropriate user identity, project/role
access checks and an authority connector. Figma styling and browser origin checks
do not supply multi-user authentication. Hold/resume still requires checkpoint
eligibility, expected version, stable idempotency key and matching runtime ACK.
Queued/dispatched and uncertain outcomes must stay distinct from applied. Financial
and approval authority do not become UI conveniences.

Implementation acceptance should include unit checks for graph projection and
selection, keyboard tab/focus behavior, actual large-graph layout measurements,
read-only/operator modes, disconnect/resync, payment decimal/provenance display,
control reconciliation and screenshot comparison at relevant breakpoints. Keep
schema and protocol regression checks from the existing project.

## Verification and remaining limits

The five initial compositions were rendered and visually inspected. Structural
readback found 263, 298, 245, 267 and 112 descendants respectively, including 15,
19, 9, 12 and 6 component instances. No review frame contains an image-filled node
or complete-UI raster. Text families were explicitly checked: Inter and JetBrains
Mono on desktop, Inter on phone.

A targeted refinement then changed chrome from #D9D9D9 to the lighter library
secondary surface (#F5F5F5), softened dividers, removed inactive tab underlines,
colored the active tab blue, normalized button typography and increased connector
contrast. The mutation succeeded and returned affected IDs. The Starter MCP quota
then blocked further edits and screenshot export. The PNG previews are the
**inspected earlier pass**, before this final refinement; they are not a verified
render of the latest file. The Figma file holds the updated design.

Additional approval, control-history and incident frames plus prototype tab links
were planned but were not created. An automatic approval review rejected an
attempt that embedded a raw local telemetry payload. That payload was not sent.
The replacement script uses clearly fictional design fixtures and was blocked
by the Figma plan quota before execution. No rejected upload was retried through
an indirect route. There is no need to upload raw event/command payloads for a
design review. Browser sign-in/remote assist was not completed, and no BrowserAct
account or subscription was created.

Application source, backend behavior and dependency manifests are unchanged by
this design task. Review the design direction before implementation. The temporary
verification servers and owned BrowserAct sessions are stopped after capture.
