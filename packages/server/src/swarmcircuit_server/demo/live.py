"""Closed-loop writer/reviewer handoffs over explicitly synthetic CSV facts."""

import json
import sqlite3
import threading
from typing import TYPE_CHECKING, Any

from swarmcircuit_server.db.store import now_ms
from swarmcircuit_server.demo.agents import LiveFailure, check_draft, draft_document
from swarmcircuit_server.demo.fixtures import PUBLIC_FINDINGS, analysis_text, analyze
from swarmcircuit_server.demo.service import artifact, note

if TYPE_CHECKING:
    from swarmcircuit_server.demo.service import DemoManager


def evidence_document(
    facts: dict[str, Any],
    initial_errors: list[str],
    review: dict[str, Any],
    final_errors: list[str],
    repaired: bool,
) -> str:
    result = {
        "independently_computed_csv_facts": facts,
        "original_draft_check_errors": initial_errors,
        "reviewer_verdict": review.get("verdict"),
        "reviewer_issues": review.get("issues", []),
        "repair_used": repaired,
        "final_typed_claim_errors": final_errors,
    }
    return (
        "# Agent handoff checks\n\n"
        "The source-data checker recomputes CSV facts outside the reporting model. "
        "It checks only the supported typed quantities and limitation labels, not arbitrary "
        "model rationale. Writer and reviewer use the same configured provider; separate "
        "roles are not independent model families.\n\n"
        + (
            "The repair received deterministic fact checks, without a second model review.\n\n"
            if repaired
            else "The original draft received a separate model review and typed fact checks.\n\n"
        )
        + "```json\n"
        + json.dumps(result, indent=2)
        + "\n```\n"
    )


def checked_brief(facts: dict[str, Any], repaired: bool) -> str:
    return (
        "# Checked quarterly sales brief\n\n"
        "## Supported result\n\n"
        f"Revenue grew {facts['revenue_growth_percent']}% between the first and last "
        f"quarters, from {facts['first_quarter_revenue']} to "
        f"{facts['last_quarter_revenue']} sample units.\n\n"
        f"The source contains {facts['quarters']} quarters and "
        f"{facts['customer_quarters']} customer-quarters.\n\n"
        "## Limits\n\n"
        "Revenue is not profit: no cost data is present. Customer-quarters sum quarterly "
        "counts and do not measure unique customers. Four quarters do not establish a "
        "forecast or seasonality.\n\n"
        "## How this handoff was checked\n\n"
        + (
            "The writer repaired its draft using the actual review and source-check feedback. "
            "The repaired typed facts passed an independent CSV check; no second model "
            "review was performed.\n\n"
            if repaired
            else "A separate reviewer accepted the writer's actual structured draft. Its typed "
            "facts also passed an independent CSV check before publication.\n\n"
        )
        + "This document renders the supported checked claims. Free-form agent rationale "
        "is retained separately as unverified evidence. The two roles use the same provider. "
        "Local synthetic data; no real company data, production tools or general safety "
        "guarantee.\n"
    )


def perform_live_step(
    manager: "DemoManager",
    demo_id: str,
    task_id: str,
    role: str,
    stop: threading.Event,
) -> None:
    """Network calls occur between writer transactions; publication rechecks authority."""
    db = manager.db

    def guard(conn: sqlite3.Connection) -> None:
        if stop.is_set():
            raise LiveFailure("interrupted")
        manager.check_live_authority(conn, demo_id, task_id)

    with db.read() as conn:
        guard(conn)
    # This computation is independent of the model's reported values, and only
    # happens after sample authority and the real SDK checkpoint allowed work.
    facts = analyze()

    def record_effect(conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT INTO guided_demo_effects VALUES (?,?,?,'approved',?)",
            (demo_id, role, now_ms(), json.dumps(facts)),
        )

    if role == "access":

        def access(conn: sqlite3.Connection) -> None:
            guard(conn)
            record_effect(conn)
            note(conn, demo_id, "access.completed", "Approved sample CSV facts are available.")

        db.write(access)
        return

    if role == "analysis":
        reply = manager.model_call(
            demo_id,
            task_id,
            "writer",
            {"computed_csv_facts": facts, "public_notes": PUBLIC_FINDINGS},
            stop,
        )
        errors = check_draft(reply.value, analyze())

        def draft(conn: sqlite3.Connection) -> None:
            guard(conn)
            conn.execute(
                "INSERT INTO guided_demo_handoffs(demo_id,status,revision,writer_json,"
                "validation_json,updated_at_ms) VALUES (?,'draft',1,?,?,?)",
                (demo_id, json.dumps(reply.value), json.dumps({"writer_errors": errors}), now_ms()),
            )
            artifact(
                conn,
                demo_id,
                "agent-draft",
                "Writer's original draft",
                draft_document("Writer's original draft", reply.value),
            )
            artifact(
                conn,
                demo_id,
                "dataset-analysis",
                "Source CSV calculations",
                analysis_text(facts).replace(
                    "no live company data or model-generated analysis",
                    "source calculations are deterministic; model claims are retained separately",
                ),
            )
            record_effect(conn)
            note(
                conn,
                demo_id,
                "analysis.completed",
                "The actual writer draft is saved; the review step can inspect it.",
            )

        db.write(draft)
        return

    with db.read() as conn:
        row = conn.execute(
            "SELECT * FROM guided_demo_handoffs WHERE demo_id=?", (demo_id,)
        ).fetchone()
        if row is None:
            raise LiveFailure("handoff_rejected")
        handoff = dict(row)
    original = json.loads(handoff["writer_json"])
    initial_errors = check_draft(original, facts)
    if role == "validation":
        reply = manager.model_call(
            demo_id,
            task_id,
            "reviewer",
            {
                "computed_csv_facts": facts,
                "actual_writer_draft": original,
                "independent_source_check_errors": initial_errors,
            },
            stop,
        )
        accepted = (
            reply.value["verdict"] == "accept" and not reply.value["issues"] and not initial_errors
        )

        def review(conn: sqlite3.Connection) -> None:
            guard(conn)
            conn.execute(
                "UPDATE guided_demo_handoffs SET status=?,review_json=?,updated_at_ms=? "
                "WHERE demo_id=?",
                ("accepted" if accepted else "draft", json.dumps(reply.value), now_ms(), demo_id),
            )
            artifact(
                conn,
                demo_id,
                "agent-review",
                "Reviewer's actual feedback",
                draft_document("Reviewer's feedback", reply.value),
            )
            record_effect(conn)
            note(
                conn,
                demo_id,
                "validation.completed",
                "The reviewer accepted the draft and its source checks passed."
                if accepted
                else "The handoff needs repair using the actual review and source-check feedback.",
            )

        db.write(review)
        return

    if role != "brief" or not handoff["review_json"]:
        raise LiveFailure("handoff_rejected")
    review_value = json.loads(handoff["review_json"])
    repaired = bool(initial_errors or review_value["verdict"] != "accept" or review_value["issues"])
    candidate = original
    if repaired:
        candidate = manager.model_call(
            demo_id,
            task_id,
            "repair",
            {
                "computed_csv_facts": facts,
                "actual_writer_draft": original,
                "actual_reviewer_feedback": review_value,
                "independent_source_check_errors": initial_errors,
            },
            stop,
        ).value
    final_facts = analyze()
    final_errors = check_draft(candidate, final_facts)

    def publish(conn: sqlite3.Connection) -> None:
        guard(conn)
        if not conn.execute(
            "SELECT 1 FROM guided_demo_artifacts WHERE demo_id=? AND slug='public-findings'",
            (demo_id,),
        ).fetchone():
            raise LiveFailure("handoff_rejected")
        conn.execute(
            "UPDATE guided_demo_handoffs SET status=?,revision=?,repair_json=?,"
            "validation_json=?,updated_at_ms=? WHERE demo_id=?",
            (
                "rejected" if final_errors else "repaired" if repaired else "accepted",
                2 if repaired else 1,
                json.dumps(candidate) if repaired else None,
                json.dumps({"writer_errors": initial_errors, "final_errors": final_errors}),
                now_ms(),
                demo_id,
            ),
        )
        if repaired:
            artifact(
                conn,
                demo_id,
                "agent-repair",
                "Writer's repaired draft",
                draft_document("Writer's repaired draft", candidate),
            )
        artifact(
            conn,
            demo_id,
            "handoff-evidence",
            "Source checks and review outcome",
            evidence_document(final_facts, initial_errors, review_value, final_errors, repaired),
        )
        if final_errors:
            note(
                conn,
                demo_id,
                "handoff.rejected",
                "The repaired handoff did not match source data. No final brief was published.",
            )
            return
        artifact(
            conn,
            demo_id,
            "final-brief",
            "Checked sales brief",
            checked_brief(final_facts, repaired),
        )
        record_effect(conn)
        note(
            conn,
            demo_id,
            "brief.completed",
            "The checked brief is ready; original agent outputs and source checks are retained.",
        )

    db.write(publish)
    if final_errors:
        raise LiveFailure("handoff_rejected")
