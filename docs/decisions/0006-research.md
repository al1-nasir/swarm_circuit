# 0006 - Research evidence and reviewed dependency containment

Date: November 5, 2026. Status: implemented, pre-sprint preparation.

Research runs are bounded deterministic algorithm simulations. Immutable plans,
trial identities, append-only sealed artifact rows and checksums make evidence
replayable. The original contracts and migrations remain unchanged; migration
005 adds one evidence table, bringing the schema to 42 tables. The supplementary
research OpenAPI describes implemented routes without rewriting the target spec.

Research operator APIs record bounded simulations; paid providers are accessible
only through the explicitly invoked CLI. Read APIs are project-scoped and do not
expose credentials. Studio can read experiments, results, paginated trials and
allowlisted evidence files, but cannot create studies or submit trials. The
bootstrap aggregation caches by trial count and invalidates on import. Initial
result aggregation has a bounded 120-second gateway deadline; routine gateway
requests retain the 15-second deadline.

Matched scenarios/seeds share the same world input hash and recorded proposal
tape across policies. Tool/host truth is distinct from delivered observations.
Failures have no imputed numeric outcomes. Intervals use matched seeds, not tool
calls as independent samples. Strong comparisons and unfavorable cases remain.
Model workload replay has explicit open-loop limits, and incomplete provider
workloads are failed rather than silently replaced with synthetic actors.

Group application binds an optional expected-preview SHA to root, closure,
target versions, checkpoint identities, runtime fencing epochs, skips and bound.
Studio always supplies this hash; legacy clients remain compatible without it.
A stale review rejects before a write. Existing transaction-time eligibility,
operator/runtime authority separation and matching ACK semantics remain intact.
The browser persists only intent IDs and the original idempotency key, reconciles
durable policy history on reload, and never automatically retries a write with a
new key. It does not resolve approvals or resume groups automatically.

This remains a trusted single-user loopback workspace with cooperative host
hooks, not a remotely deployable authentication boundary or hostile-process
sandbox. No external authority/payment integration, publication or registration
is claimed by this phase. All Nov 5 work is pre-sprint preparation.
