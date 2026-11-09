"""Durable incident reconciliation and recoverable, single-process scheduling."""

import json
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import asdict
from threading import Event, Thread
from typing import Any
from uuid import UUID, uuid5

from swarmcircuit_server.db.store import Database, now_ms
from swarmcircuit_server.detectors.rules import DetectorPolicy, Snapshot, detect
from swarmcircuit_server.errors import Problem
from swarmcircuit_server.ingest.events import dump, outbox

log = logging.getLogger("swarmcircuit.detectors")


def initialize(conn: sqlite3.Connection, project_id: str, policy: DetectorPolicy) -> str:
    source_id = str(uuid5(UUID(project_id), "local:detectors"))
    conn.execute(
        "INSERT INTO telemetry_sources(source_id,project_id,source_key,source_kind,display_name,"
        "created_at_ms) VALUES (?,?,?,'collector','Local derived detector evidence',?) "
        "ON CONFLICT(project_id,source_key) DO NOTHING",
        (source_id, project_id, "local:detectors", now_ms()),
    )
    policy_id = str(uuid5(UUID(project_id), f"detector-policy:{policy.digest}"))
    if not conn.execute(
        "SELECT 1 FROM control_policies WHERE policy_id=?", (policy_id,)
    ).fetchone():
        revision = conn.execute(
            "SELECT COALESCE(MAX(revision),0)+1 FROM control_policies "
            "WHERE project_id=? AND policy_key='phase2-detectors'",
            (project_id,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO control_policies(policy_id,project_id,policy_key,revision,policy_kind,"
            "config_json,auto_apply,created_at_ms) "
            "VALUES (?,?,'phase2-detectors',?,'detection',?,0,?)",
            (policy_id, project_id, revision, dump(asdict(policy)), now_ms()),
        )
    return policy_id


def _audit(
    conn: sqlite3.Connection,
    run_id: str,
    project_id: str,
    incident_id: str,
    topic: str,
    summary: dict[str, Any],
    timestamp: int,
) -> None:
    revision = summary["revision"]
    eid = str(uuid5(UUID(incident_id), f"revision:{revision}"))
    conn.execute(
        "INSERT INTO run_events(event_id,run_id,project_id,source_id,source_event_key,event_kind,"
        "trust_class,occurred_at_ms,ingested_at_ms,payload_json) "
        "VALUES (?,?,?,?,?,?,'derived',?,?,?)",
        (
            eid,
            run_id,
            project_id,
            str(uuid5(UUID(project_id), "local:detectors")),
            f"incident:{incident_id}:{revision}",
            topic,
            timestamp,
            now_ms(),
            dump(
                {
                    "incident_id": incident_id,
                    "revision": revision,
                    "condition_active": summary["condition_active"],
                    "resolution_reason": summary.get("resolution_reason"),
                    "evidence_event_ids": summary["current_evidence_event_ids"],
                    "policy_id": summary["policy_id"],
                }
            ),
        ),
    )
    outbox(conn, run_id, topic, incident_id)


def reconcile(
    conn: sqlite3.Connection, project_id: str, run_id: str, as_of_ms: int, policy: DetectorPolicy
) -> int:
    """One atomic incident/evidence/audit/outbox transaction. Source ingestion is separate."""
    if not conn.execute(
        "SELECT 1 FROM workflow_runs WHERE project_id=? AND run_id=?", (project_id, run_id)
    ).fetchone():
        raise Problem(404, "not_found", "Run not found in this project")
    watermark = conn.execute(
        "SELECT MAX(updated_at_ms) FROM incidents WHERE run_id=? "
        "AND detector_key LIKE 'phase2-v1:%'",
        (run_id,),
    ).fetchone()[0]
    if watermark is not None and as_of_ms < watermark:
        return 0
    snapshot = Snapshot(conn, run_id, as_of_ms)
    findings = detect(snapshot, policy)
    policy_id = initialize(conn, project_id, policy)
    previous = {
        r["incident_id"]: dict(r)
        for r in conn.execute(
            "SELECT * FROM incidents WHERE run_id=? AND detector_key LIKE 'phase2-v1:%'",
            (run_id,),
        )
    }
    active = set()
    changes = 0
    for finding in findings:
        detector_key = f"{policy.version}:{finding.kind}"
        fingerprint = f"{policy.digest}:{finding.fingerprint}"
        iid = str(uuid5(UUID(run_id), f"{detector_key}:{fingerprint}"))
        active.add(iid)
        old = previous.get(iid)
        old_summary = json.loads(old["evidence_summary"]) if old else {}
        if old_summary.get("evaluated_at_ms", -1) > as_of_ms:
            continue
        summary = {
            "detector_version": policy.version,
            "policy_id": policy_id,
            "policy_sha256": policy.digest,
            "policy": asdict(policy),
            "affected_task_ids": list(finding.task_ids),
            "current_evidence_event_ids": list(finding.event_ids),
            "metrics": finding.metrics,
            "uncertainty": finding.uncertainty,
            "evidence_kind": "explicit",
            "condition_active": True,
            "first_observed_at_ms": min(
                old_summary.get("first_observed_at_ms", as_of_ms), finding.first_observed_at_ms
            ),
            "last_observed_at_ms": max(
                old_summary.get("last_observed_at_ms", 0), finding.last_observed_at_ms
            ),
        }
        old_comparable = {
            k: v
            for k, v in old_summary.items()
            if k not in {"evaluated_at_ms", "revision", "resolution_reason"}
        }
        if old and old_comparable == summary and old["state"] != "resolved":
            continue
        summary.update(evaluated_at_ms=as_of_ms, revision=old_summary.get("revision", 0) + 1)
        if old is None:
            state, topic = "open", "incident.opened"
            conn.execute(
                "INSERT INTO incidents(incident_id,run_id,detector_key,fingerprint,kind,severity,"
                "state,title,evidence_summary,opened_at_ms,updated_at_ms) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    iid,
                    run_id,
                    detector_key,
                    fingerprint,
                    finding.kind,
                    finding.severity,
                    state,
                    finding.title,
                    dump(summary),
                    as_of_ms,
                    as_of_ms,
                ),
            )
        else:
            state = "open" if old["state"] == "resolved" else old["state"]
            topic = "incident.reopened" if old["state"] == "resolved" else "incident.updated"
            conn.execute(
                "UPDATE incidents SET state=?,evidence_summary=?,updated_at_ms=?,"
                "resolved_at_ms=NULL "
                "WHERE incident_id=?",
                (state, dump(summary), as_of_ms, iid),
            )
        for event_id in finding.event_ids:
            conn.execute(
                "INSERT INTO incident_evidence(evidence_id,run_id,incident_id,event_id,note) "
                "VALUES (?,?,?,?,'SDK observation; not external-effect verification') "
                "ON CONFLICT(evidence_id) DO NOTHING",
                (str(uuid5(UUID(iid), event_id)), run_id, iid, event_id),
            )
        _audit(conn, run_id, project_id, iid, topic, summary, as_of_ms)
        changes += 1
    for iid, old in previous.items():
        if iid in active:
            continue
        summary = json.loads(old["evidence_summary"])
        if not summary["condition_active"] or summary["evaluated_at_ms"] > as_of_ms:
            continue
        # Resolution concerns the observed signature, never the underlying payment/task outcome.
        reason = (
            "policy_replaced"
            if summary["policy_sha256"] != policy.digest
            else "condition_no_longer_observed"
        )
        summary.update(
            condition_active=False,
            resolution_reason=reason,
            evaluated_at_ms=as_of_ms,
            revision=summary["revision"] + 1,
        )
        state = "suppressed" if old["state"] == "suppressed" else "resolved"
        conn.execute(
            "UPDATE incidents SET state=?,evidence_summary=?,updated_at_ms=?,resolved_at_ms=? "
            "WHERE incident_id=?",
            (state, dump(summary), as_of_ms, as_of_ms if state == "resolved" else None, iid),
        )
        _audit(
            conn,
            run_id,
            project_id,
            iid,
            "incident.resolved" if state == "resolved" else "incident.updated",
            summary,
            as_of_ms,
        )
        changes += 1
    return changes


class DetectionService:
    def __init__(
        self,
        db: Database,
        project_id: str,
        policy: DetectorPolicy,
        interval_seconds: float = 1,
        clock: Callable[[], int] = now_ms,
    ) -> None:
        self.db, self.project_id, self.policy = db, project_id, policy
        self.interval_seconds, self.clock = interval_seconds, clock
        self.stopping = Event()
        self.thread: Thread | None = None
        self.healthy = True
        self.db.write(lambda conn: initialize(conn, project_id, policy))

    def scan_run(self, run_id: str, as_of_ms: int | None = None) -> int:
        at = self.clock() if as_of_ms is None else as_of_ms
        return self.db.write(lambda conn: reconcile(conn, self.project_id, run_id, at, self.policy))

    def after_ingest(self, run_id: str) -> None:
        try:
            self.scan_run(run_id)
        except Exception:
            self.healthy = False
            log.warning("detector_scan_failed", extra={"run_id": run_id})

    def scan_once(self, as_of_ms: int | None = None) -> None:
        """Keyset-page runs; one short writer transaction per run, retry failures next pass."""
        at = self.clock() if as_of_ms is None else as_of_ms
        cursor = ""
        failed = False
        while not self.stopping.is_set():
            with self.db.read() as conn:
                rows = conn.execute(
                    "SELECT run_id FROM workflow_runs WHERE project_id=? AND run_id>? "
                    "ORDER BY run_id LIMIT 100",
                    (self.project_id, cursor),
                ).fetchall()
            if not rows:
                break
            for row in rows:
                if self.stopping.is_set():
                    return
                try:
                    self.scan_run(row["run_id"], at)
                except Exception:
                    failed = True
                    log.warning("detector_scan_failed", extra={"run_id": row["run_id"]})
            cursor = rows[-1]["run_id"]
        self.healthy = not failed

    def start(self) -> None:
        if self.interval_seconds > 0:
            self.thread = Thread(target=self._loop, name="swarm-detectors", daemon=True)
            self.thread.start()

    def _loop(self) -> None:
        while not self.stopping.wait(self.interval_seconds):
            try:
                self.scan_once()
            except Exception:
                self.healthy = False
                log.warning("detector_pass_failed")

    def stop(self) -> None:
        self.stopping.set()
        if self.thread is not None:
            self.thread.join()


def list_incidents(conn: sqlite3.Connection, run_id: str) -> dict[str, Any]:
    items = []
    for row in conn.execute(
        "SELECT * FROM incidents WHERE run_id=? ORDER BY opened_at_ms DESC,incident_id",
        (run_id,),
    ):
        item = dict(row)
        summary = json.loads(item.pop("evidence_summary"))
        item.update(summary)
        item["evidence_event_ids"] = [
            r[0]
            for r in conn.execute(
                "SELECT event_id FROM incident_evidence WHERE incident_id=? AND run_id=? "
                "AND event_id IS NOT NULL ORDER BY event_id",
                (row["incident_id"], run_id),
            )
        ]
        item.update(
            evidence_span_ids=[],
            can_control=False,
            suggested_control=None,
            can_control_reason="Observe-only Phase 2; no runtime checkpoints or authority",
            trust_class="derived",
        )
        items.append(item)
    return {"items": items}
