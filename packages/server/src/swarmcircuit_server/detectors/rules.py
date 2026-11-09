"""Deterministic SDK-evidence rules, evaluated against an explicit clock."""

import hashlib
import json
import sqlite3
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class DetectorPolicy:
    version: str = "phase2-v1"
    payment_evidence_version: str = "phase4-v1"
    approval_window_ms: int = 30_000
    approval_duplicate_threshold: int = 3
    retry_window_ms: int = 60_000
    retry_ratio_threshold: float = 1.0
    stall_timeout_ms: int = 60_000

    def __post_init__(self) -> None:
        if (
            min(
                self.approval_window_ms,
                self.approval_duplicate_threshold,
                self.retry_window_ms,
                self.stall_timeout_ms,
            )
            <= 0
        ):
            raise ValueError("Detector windows and count thresholds must be positive")
        if not 0 <= self.retry_ratio_threshold < float("inf"):
            raise ValueError("Retry threshold must be finite and nonnegative")

    @property
    def digest(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class Finding:
    kind: str
    fingerprint: str
    title: str
    event_ids: tuple[str, ...]
    task_ids: tuple[str, ...]
    metrics: dict[str, Any]
    uncertainty: str
    first_observed_at_ms: int
    last_observed_at_ms: int
    severity: str = "warning"


class Snapshot:
    def __init__(self, conn: sqlite3.Connection, run_id: str, as_of_ms: int) -> None:
        self.as_of_ms = as_of_ms
        self.tasks = {
            r["task_id"]: dict(r)
            for r in conn.execute(
                "SELECT * FROM tasks WHERE run_id=?",
                (run_id,),
            )
        }
        self.events = {
            r["event_id"]: dict(r)
            for r in conn.execute(
                "SELECT rowid AS ingestion_order,* FROM run_events "
                "WHERE run_id=? AND trust_class='sdk_observation' "
                "AND occurred_at_ms<=? AND event_kind IN ('task.created','task.started',"
                "'task.progress','task.completed','task.failed','task.waiting_for_approval',"
                "'task.dependency_added','task.retry_requested','approval.requested',"
                "'payment.gate_decided','payment.attempt_submitted','payment.delivery_checked')",
                (run_id, as_of_ms),
            )
        }
        self.approvals = {
            r["approval_id"]: dict(r)
            for r in conn.execute(
                "SELECT * FROM approvals WHERE run_id=? AND state='pending'",
                (run_id,),
            )
        }
        self.dependencies = []
        self.payment_warnings: list[dict[str, Any]] = []
        for intent in conn.execute("SELECT * FROM payment_intents WHERE run_id=?", (run_id,)):
            related = [
                e
                for e in self.events.values()
                if e["event_kind"].startswith("payment.")
                and json.loads(e["payload_json"]).get("payment_intent_id")
                == intent["payment_intent_id"]
            ]
            if intent["state"] in {"unknown", "submitted"}:
                effects = [e for e in related if e["event_kind"] != "payment.gate_decided"]
                if effects:
                    self.payment_warnings.append(
                        {
                            "intent_id": intent["payment_intent_id"],
                            "task_id": intent["task_id"],
                            "warning": "settlement_unknown",
                            "events": [e["event_id"] for e in effects],
                        }
                    )
            checks = [e for e in related if e["event_kind"] == "payment.delivery_checked"]
            if checks:
                latest = max(checks, key=lambda e: (e["occurred_at_ms"], e["ingestion_order"]))
                if not json.loads(latest["payload_json"])["structural_ok"]:
                    self.payment_warnings.append(
                        {
                            "intent_id": intent["payment_intent_id"],
                            "task_id": intent["task_id"],
                            "warning": "structural_delivery_failure",
                            "events": [latest["event_id"]],
                        }
                    )
        for row in conn.execute(
            "SELECT * FROM task_dependencies WHERE run_id=? AND is_explicit=1",
            (run_id,),
        ):
            e = self.events.get(row["evidence_event_id"])
            if not e or e["event_kind"] != "task.dependency_added":
                continue
            payload = json.loads(e["payload_json"])
            if (
                e["task_id"] == row["blocked_task_id"]
                and payload.get("prerequisite_task_id") == row["prerequisite_task_id"]
                and payload.get("relation_kind") == row["relation_kind"]
            ):
                self.dependencies.append(dict(row))

    def recent(self, kind: str, window_ms: int) -> list[dict[str, Any]]:
        return sorted(
            (
                e
                for e in self.events.values()
                if e["event_kind"] == kind
                and self.as_of_ms - window_ms < e["occurred_at_ms"] <= self.as_of_ms
            ),
            key=lambda e: (e["occurred_at_ms"], e["event_id"]),
        )

    def finding(
        self,
        kind: str,
        identity: str,
        title: str,
        event_ids: list[str],
        task_ids: list[str],
        metrics: dict[str, Any],
        uncertainty: str,
    ) -> Finding:
        ids = tuple(sorted(set(event_ids)))
        if not ids:
            raise ValueError("A finding requires source evidence")
        times = [self.events[eid]["occurred_at_ms"] for eid in ids]
        fingerprint = hashlib.sha256(identity.encode()).hexdigest()
        return Finding(
            kind,
            fingerprint,
            title,
            ids,
            tuple(sorted(set(task_ids))),
            metrics,
            uncertainty,
            min(times),
            max(times),
        )


def reverse_closure(roots: set[str], dependencies: list[dict[str, Any]]) -> set[str]:
    reverse: dict[str, set[str]] = defaultdict(set)
    for d in dependencies:
        reverse[d["prerequisite_task_id"]].add(d["blocked_task_id"])
    seen, pending = set(roots), list(roots)
    while pending:
        for child in reverse.get(pending.pop(), set()):
            if child not in seen:
                seen.add(child)
                pending.append(child)
    return seen


def strongly_connected(nodes: set[str], edges: list[tuple[str, str]]) -> list[set[str]]:
    """Iterative Kosaraju; no recursion limit or external graph dependency."""
    forward: dict[str, set[str]] = defaultdict(set)
    reverse: dict[str, set[str]] = defaultdict(set)
    for source, target in edges:
        forward[source].add(target)
        reverse[target].add(source)
    seen: set[str] = set()
    order = []
    for start in sorted(nodes):
        if start in seen:
            continue
        stack = [(start, False)]
        while stack:
            node, exiting = stack.pop()
            if exiting:
                order.append(node)
            elif node not in seen:
                seen.add(node)
                stack.append((node, True))
                stack.extend(
                    (child, False)
                    for child in sorted(forward[node], reverse=True)
                    if child not in seen
                )
    seen.clear()
    groups = []
    for start in reversed(order):
        if start in seen:
            continue
        group, pending = set(), [start]
        while pending:
            node = pending.pop()
            if node in seen:
                continue
            seen.add(node)
            group.add(node)
            pending.extend(sorted(reverse[node] - seen))
        groups.append(group)
    return groups


def detect(snapshot: Snapshot, policy: DetectorPolicy) -> list[Finding]:
    findings = []
    approval_events: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in snapshot.recent("approval.requested", policy.approval_window_ms):
        if e["approval_id"] in snapshot.approvals:
            approval_events[e["approval_id"]].append(e)
    for approval_id, events in sorted(approval_events.items()):
        duplicates = len(events) - 1
        if duplicates >= policy.approval_duplicate_threshold:
            findings.append(
                snapshot.finding(
                    "approval_storm",
                    approval_id,
                    "Repeated requests for one pending approval",
                    [e["event_id"] for e in events],
                    [e["task_id"] for e in events if e["task_id"]],
                    {
                        "approval_id": approval_id,
                        "request_count": len(events),
                        "duplicate_requests": duplicates,
                        "denominator": 1,
                        "window_ms": policy.approval_window_ms,
                        "duplicate_threshold": policy.approval_duplicate_threshold,
                    },
                    "Repeated SDK requests are observed; reviewer notifications and "
                    "malicious intent "
                    "are not established. A pending human approval is expected safety behavior.",
                )
            )

    retries = snapshot.recent("task.retry_requested", policy.retry_window_ms)
    logical_actions = {(e["task_id"], json.loads(e["payload_json"])["retry_of"]) for e in retries}
    if logical_actions and len(retries) / len(logical_actions) > policy.retry_ratio_threshold:
        findings.append(
            snapshot.finding(
                "retry_amplification",
                "run",
                "Excess requested retries per logical action",
                [e["event_id"] for e in retries],
                [e["task_id"] for e in retries],
                {
                    "retry_requests": len(retries),
                    "distinct_logical_actions": len(logical_actions),
                    "denominator": len(logical_actions),
                    "amplification": len(retries) / len(logical_actions),
                    "ratio_threshold": policy.retry_ratio_threshold,
                    "window_ms": policy.retry_window_ms,
                    "basis": "requested_retries_per_task_and_retry_of",
                },
                "These are host-requested retries, not confirmed executions or external effects. "
                "One initial logical action is assumed for each distinct "
                "(task_id, retry_of) lineage.",
            )
        )

    human_roots = {
        tid for tid, task in snapshot.tasks.items() if task["state"] == "waiting_for_human"
    }
    human_blocked = reverse_closure(human_roots, snapshot.dependencies)
    for tid, task in sorted(snapshot.tasks.items()):
        if task["state"] not in {"running", "ready", "recovering"} or tid in human_blocked:
            continue
        progress = [
            e
            for e in snapshot.events.values()
            if e["task_id"] == tid and e["event_kind"] in {"task.started", "task.progress"}
        ]
        if not progress:
            continue
        last = max(progress, key=lambda e: (e["occurred_at_ms"], e["event_id"]))
        trigger = max(task["deadline_at_ms"] or 0, last["occurred_at_ms"] + policy.stall_timeout_ms)
        if snapshot.as_of_ms >= trigger:
            creation = [
                e["event_id"]
                for e in snapshot.events.values()
                if e["task_id"] == tid and e["event_kind"] == "task.created"
            ]
            findings.append(
                snapshot.finding(
                    "task_stall",
                    tid,
                    "Task has no reported progress past its deadline",
                    creation + [last["event_id"]],
                    [tid],
                    {
                        "last_progress_at_ms": last["occurred_at_ms"],
                        "trigger_at_ms": trigger,
                        "declared_deadline_at_ms": task["deadline_at_ms"],
                        "no_progress_threshold_ms": policy.stall_timeout_ms,
                    },
                    "Missing SDK progress can indicate a stalled task, telemetry loss, "
                    "or a disconnected host. It does not prove runtime failure. "
                    "Human waits and their dependents are excluded.",
                )
            )

    unfinished = {
        tid
        for tid, task in snapshot.tasks.items()
        if task["state"] in {"created", "ready", "running", "recovering"}
    }
    dependencies = [
        d
        for d in snapshot.dependencies
        if d["blocked_task_id"] in unfinished and d["prerequisite_task_id"] in unfinished
    ]
    components = strongly_connected(
        unfinished, [(d["blocked_task_id"], d["prerequisite_task_id"]) for d in dependencies]
    )
    for group in components:
        if len(group) > 1:
            evidence = [
                d["evidence_event_id"]
                for d in dependencies
                if d["blocked_task_id"] in group and d["prerequisite_task_id"] in group
            ]
            findings.append(
                snapshot.finding(
                    "dependency_cycle",
                    ":".join(sorted(group)),
                    "Suspected circular task dependency",
                    evidence,
                    list(group),
                    {"task_count": len(group), "explicit_edge_count": len(evidence)},
                    "SDK-declared prerequisites form a cycle among unfinished tasks. This is a "
                    "suspected circular wait, not verified runtime deadlock. "
                    "Message/span cycles are ignored.",
                )
            )

    for approval_id, approval in sorted(snapshot.approvals.items()):
        root = approval["related_task_id"]
        if root is None:
            continue
        closure = reverse_closure({root}, snapshot.dependencies)
        affected = [e for e in retries if e["task_id"] in closure]
        tasks = {e["task_id"] for e in affected}
        actions = {(e["task_id"], json.loads(e["payload_json"])["retry_of"]) for e in affected}
        origin = [
            e["event_id"]
            for e in snapshot.events.values()
            if e["event_kind"] == "approval.requested"
            and e["approval_id"] == approval_id
            and e["task_id"] == root
        ]
        if (
            len(tasks) >= 2
            and actions
            and origin
            and len(affected) / len(actions) > policy.retry_ratio_threshold
        ):
            # Include the explicit paths to the shared blocker, not unrelated branches.
            paths = [
                d
                for d in snapshot.dependencies
                if d["blocked_task_id"] in closure and d["prerequisite_task_id"] in closure
            ]
            needed = set(tasks)
            changed = True
            while changed:
                before = len(needed)
                needed.update(
                    d["prerequisite_task_id"] for d in paths if d["blocked_task_id"] in needed
                )
                changed = len(needed) != before
            path_evidence = [
                d["evidence_event_id"]
                for d in paths
                if d["blocked_task_id"] in needed and d["prerequisite_task_id"] in needed
            ]
            findings.append(
                snapshot.finding(
                    "cascade",
                    approval_id,
                    "Retry amplification across a shared blocked dependency",
                    origin + [e["event_id"] for e in affected] + path_evidence,
                    sorted(needed),
                    {
                        "approval_id": approval_id,
                        "root_task_id": root,
                        "retrying_task_count": len(tasks),
                        "retry_requests": len(affected),
                        "denominator": len(actions),
                        "amplification": len(affected) / len(actions),
                        "ratio_threshold": policy.retry_ratio_threshold,
                        "window_ms": policy.retry_window_ms,
                    },
                    "Declared dependency paths connect retrying tasks to a pending gate. "
                    "This supports a coordination-cascade hypothesis, "
                    "not independently verified causation or failure.",
                )
            )
    for warning in snapshot.payment_warnings:
        findings.append(
            snapshot.finding(
                "policy_warning",
                f"payment:{warning['warning']}:{warning['intent_id']}",
                "Payment settlement is unconfirmed"
                if warning["warning"] == "settlement_unknown"
                else "Host reported a structural delivery failure",
                warning["events"],
                [warning["task_id"]] if warning["task_id"] else [],
                {
                    "payment_intent_id": warning["intent_id"],
                    "warning": warning["warning"],
                    "payment_evidence_version": policy.payment_evidence_version,
                },
                "GateKeep402 observations are host evidence. Delivery checks are structural, "
                "not semantic quality or settlement verification. A receipt cannot undo a payment "
                "or its recorded delivery failure. Mock receipts establish simulation truth only.",
            )
        )
    return sorted(findings, key=lambda f: (f.kind, f.fingerprint))
