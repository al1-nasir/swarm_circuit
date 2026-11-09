# SwarmCircuit console redesign — design review

Date: 2026-11-04. Scope: editable Figma proposal before application changes.

Design goal: make workflow state and dependency structure readable in a tab-heavy
operational console. Keep evidence/authority semantics intact. The current source
uses Inter and JetBrains Mono; retain those fonts, improve scale and contrast.

Review inventory: workflow canvas, selected-task inspector, payments table,
timeline and responsive list. Repeated node/tab/button elements use components;
semantic colors and spacing use tokens. No marketing rebrand or invented metrics.

Primary direction: neutral light console, restrained graphite type, one blue
selection accent; amber means waiting, green means observed completion, red means
failure/denial. Persistent workspace sidebar plus two distinct tab levels: open
run documents and run sections. No large statistic cards or default empty inspector.

Move task/agent totals to the graph view switch and Run details. Put runtime health
inside Run details and contextual controls. Put connection freshness in a thin
status bar. Display the pending approval in its tab and in the selected gate, not
as five competing header statistics. Split Payments and Approvals into peer tabs.

Graph direction: prerequisite → dependent (presentation convention). Preserve
backend relation kinds and evidence IDs. Show named ports and arrowheads; avoid
backward routing through nodes. Only a selected dependency needs a relation label.
No add-node or execute controls: SwarmCircuit observes declared orchestration.

Figma: https://www.figma.com/design/vu4V38F93GDNxAInQQM0be
File session: 9cf10aac-8102-4a7a-98a8-6a91daefa1ad

Acceptance: editable layers; all required sections represented; tab hierarchy
clear; source data/trust classes preserved; font family checked; no clipped text,
colliding connectors or complete-UI bitmap; inspect actual Figma renders before
handoff. This is a design proposal, not a production-implementation claim.
