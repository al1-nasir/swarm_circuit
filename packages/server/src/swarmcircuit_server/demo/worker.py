"""Actual SDK workers, with optional bounded live handoffs and real runtime ACKs."""

import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from swarmcircuit_server.db.store import now_ms
from swarmcircuit_server.demo.fixtures import PUBLIC_FINDINGS, analysis_text, analyze, final_text
from swarmcircuit_server.demo.live import perform_live_step
from swarmcircuit_server.demo.service import ACTIVE, TITLE, artifact, note, require

if TYPE_CHECKING:
    from swarmcircuit_server.demo.service import DemoManager


def run_workflow(manager: "DemoManager", demo_id: str, stop: threading.Event) -> None:
    import httpx
    from swarmcircuit import ControlError, SwarmCircuit

    db, config = manager.db, manager.settings
    with db.read() as conn:
        live_mode = require(conn, config.project_id, demo_id)["execution_mode"] == "live"
    with (
        httpx.Client(timeout=2, trust_env=False) as client,
        SwarmCircuit(
            config.project_id, config.sdk_token, manager.origin, client=client, attempts=1
        ) as sdk,
        sdk.run(
            TITLE, mode="control", simulation=True, external_run_key="guided:" + demo_id
        ) as run,
    ):

        def register(conn: sqlite3.Connection) -> None:
            require(conn, config.project_id, demo_id)
            conn.execute(
                "UPDATE guided_demo_sessions SET run_id=?,updated_at_ms=? WHERE demo_id=?",
                (run.run_id, now_ms(), demo_id),
            )
            conn.execute(
                "UPDATE workflow_runs SET metadata_json=? WHERE run_id=?",
                (
                    json.dumps(
                        {
                            "simulation": True,
                            "guided_demo": True,
                            "guided_demo_id": demo_id,
                            "execution_mode": "live" if live_mode else "fixture",
                        }
                    ),
                    run.run_id,
                ),
            )

        db.write(register)
        tasks = {}
        for role, title in [
            ("plan", "Plan the sales brief"),
            ("public", "Write public-source findings"),
            ("access", "Read the approved sample dataset"),
            ("analysis", "Write the agent draft" if live_mode else "Calculate sales growth"),
            ("validation", "Review the agent draft" if live_mode else "Check the calculations"),
            (
                "brief",
                "Publish the checked sales brief" if live_mode else "Write the final sales brief",
            ),
        ]:
            if stop.is_set():
                db.write(
                    lambda c: manager._terminal(
                        c, demo_id, "interrupted", "The local worker was stopped."
                    )
                )
                return
            tasks[role] = run.task(title, agent="guided-" + role)
        tasks["public"].depends_on(tasks["plan"])
        tasks["access"].depends_on(tasks["plan"])
        tasks["analysis"].depends_on(tasks["access"])
        tasks["validation"].depends_on(tasks["analysis"] if live_mode else tasks["access"])
        tasks["brief"].depends_on(tasks["analysis"])
        tasks["brief"].depends_on(tasks["validation"])
        tasks["brief"].depends_on(tasks["public"])
        db.write(
            lambda c: c.execute(
                "UPDATE guided_demo_sessions SET task_ids_json=? WHERE demo_id=?",
                (json.dumps({r: t.task_id for r, t in tasks.items()}), demo_id),
            )
        )
        with tasks["plan"]:
            pass
        scope = {
            "principal": "guided-sales-analyst",
            "purpose": "read synthetic quarterly sales CSV",
            "resource": "mock:guided-dataset:" + demo_id,
            "counterparty": "local.fixture",
            "permission_scope": "read",
            "policy_revision": "guided-v1",
        }
        # One authority decision gates the shared access root. Its explicit
        # descendants wait at SDK checkpoints without issuing duplicate requests.
        with tasks["access"]:
            approval_id = tasks["access"].wait_for_approval(scope)

        def ready(conn: sqlite3.Connection) -> None:
            conn.execute(
                (
                    "UPDATE guided_demo_sessions SET "
                    "approval_id=?,state='waiting',updated_at_ms=? "
                    "WHERE demo_id=?"
                ),
                (approval_id, now_ms(), demo_id),
            )
            note(
                conn,
                demo_id,
                "waiting",
                (
                    "Four dependent tasks are waiting quietly for "
                    "dataset permission. Public research runs "
                    "independently."
                ),
            )

        db.write(ready)

        def public_work() -> None:
            with tasks["public"]:
                # Independent timing: not conditioned on a hold, ACK or permission decision.
                time.sleep(1)
                db.write(
                    lambda c: artifact(
                        c, demo_id, "public-findings", "Public-source findings", PUBLIC_FINDINGS
                    )
                )
            db.write(
                lambda c: note(
                    c,
                    demo_id,
                    "public.completed",
                    (
                        "Public-source findings are ready. No dataset "
                        "permission or pause command was needed."
                    ),
                )
            )

        with run.runtime("guided-fixture-worker", poll_interval=0.2) as runtime:

            def protected_work(role: str) -> None:
                task = tasks[role]
                try:
                    runtime.checkpoint(task, action="before_" + role, timeout=610)
                    if stop.is_set():
                        return
                    with task:
                        if live_mode:
                            perform_live_step(manager, demo_id, task.task_id, role, stop)
                            task.waiting = False
                            task.mark_completed()
                            return

                        def effect(conn: sqlite3.Connection) -> None:
                            demo = require(conn, config.project_id, demo_id)
                            ap = conn.execute(
                                (
                                    "SELECT state,verified_resolution_source FROM "
                                    "approvals WHERE approval_id=? AND run_id=?"
                                ),
                                (demo["approval_id"], run.run_id),
                            ).fetchone()
                            if (
                                demo["permission"] != "approved"
                                or demo["state"] not in ACTIVE
                                or not ap
                                or ap[0] != "approved"
                                or not ap[1]
                            ):
                                raise RuntimeError("Fixture authority did not authorize the effect")
                            result = analyze()
                            if role == "validation" and (
                                result["revenue_growth_percent"] != "39.15"
                                or result["quarters"] != 4
                            ):
                                raise RuntimeError("Fixture calculation validation failed")
                            conn.execute(
                                "INSERT INTO guided_demo_effects VALUES (?,?,?,'approved',?)",
                                (demo_id, role, now_ms(), json.dumps(result)),
                            )
                            if role == "analysis":
                                artifact(
                                    conn,
                                    demo_id,
                                    "dataset-analysis",
                                    "Dataset analysis",
                                    analysis_text(result),
                                )
                            elif role == "brief":
                                if not conn.execute(
                                    (
                                        "SELECT 1 FROM guided_demo_artifacts WHERE "
                                        "demo_id=? AND slug='public-findings'"
                                    ),
                                    (demo_id,),
                                ).fetchone():
                                    raise RuntimeError("Public output is not ready")
                                artifact(
                                    conn,
                                    demo_id,
                                    "final-brief",
                                    "Final sales brief",
                                    final_text(result),
                                )
                            note(
                                conn,
                                demo_id,
                                role + ".completed",
                                {
                                    "access": "Approved fixture dataset read once.",
                                    "analysis": (
                                        "Sales growth was calculated from the synthetic CSV."
                                    ),
                                    "validation": (
                                        "The fixture calculations passed their "
                                        "independent expected-value check."
                                    ),
                                    "brief": "The final sales brief is ready to read and download.",
                                }[role],
                            )

                        db.write(effect)
                        task.waiting = False
                        task.mark_completed()
                except ControlError:
                    if stop.is_set() or runtime.stopping.is_set():
                        return
                    # An unavailable boundary is not a healthy permission wait.
                    # Let the coordinator stop sibling checkpoints and record failure.
                    raise

            with ThreadPoolExecutor(max_workers=5, thread_name_prefix="guided-task") as pool:
                futures = [
                    pool.submit(protected_work, r)
                    for r in ("access", "analysis", "validation", "brief")
                ]
                public = pool.submit(public_work)
                try:
                    while not stop.wait(0.2):
                        for f in futures + [public]:
                            if f.done():
                                f.result()
                        with db.read() as conn:
                            state = require(conn, config.project_id, demo_id)
                        if state["permission"] == "denied":
                            # Public work is unrelated and can complete on its own schedule.
                            public.result(timeout=5)
                            db.write(
                                lambda c: manager._terminal(
                                    c,
                                    demo_id,
                                    "denied",
                                    (
                                        "Dataset access was denied. Protected work did "
                                        "not execute; public findings remain "
                                        "available."
                                    ),
                                )
                            )
                            break
                        if all(t.completed for t in tasks.values()):
                            break
                        if now_ms() >= state["expires_at_ms"]:
                            db.write(
                                lambda c: manager._terminal(
                                    c,
                                    demo_id,
                                    "expired",
                                    (
                                        "The ten-minute local worker expired. Outputs "
                                        "are retained; start a fresh workflow to "
                                        "continue."
                                    ),
                                )
                            )
                            break
                    else:
                        db.write(
                            lambda c: manager._terminal(
                                c,
                                demo_id,
                                "interrupted",
                                "The local worker stopped. Existing outputs are retained.",
                            )
                        )
                finally:
                    stop.set()
                    runtime.stopping.set()
                for f in futures + [public]:
                    f.result(timeout=8)
    # RunContext emits workflow.completed while exiting. Publish the walkthrough
    # result only after that final lifecycle event has also been acknowledged.
    if sdk.telemetry_degraded:
        raise RuntimeError("Guided workflow telemetry was not acknowledged")
    if all(t.completed for t in tasks.values()):
        db.write(
            lambda c: manager._terminal(
                c,
                demo_id,
                "completed",
                "All six tasks completed. The sales brief and its source outputs are available.",
            )
        )
