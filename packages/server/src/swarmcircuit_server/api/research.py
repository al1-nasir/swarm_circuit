"""Research runner imports + read-only reproducibility endpoints. Never launches paid calls."""

import json
from typing import Any
from uuid import UUID

from fastapi import BackgroundTasks, Depends, FastAPI, Query, Request
from fastapi.responses import Response

from swarmcircuit_server.api.result_cache import ResultCache
from swarmcircuit_server.errors import Problem
from swarmcircuit_server.repository import decode_cursor, encode_cursor
from swarmcircuit_server.research import store


def install(app: FastAPI, read_auth: Any) -> None:
    cache = ResultCache()

    def operator(role: str = Depends(read_auth)) -> None:
        if role != "operator":
            raise Problem(
                403, "operator_required", "Research recording requires the operator credential"
            )

    @app.post(
        "/api/v1/experiments",
        status_code=201,
        dependencies=[Depends(operator)],
        operation_id="createResearchExperiment",
    )
    def create(request: Request, body: store.CreateExperiment) -> dict[str, Any]:
        return store.create(request.app.state.db, request.app.state.settings, body)

    @app.post(
        "/api/v1/experiments/{experiment_id}/trials",
        status_code=201,
        dependencies=[Depends(operator)],
        operation_id="recordResearchTrial",
    )
    def record(
        request: Request,
        experiment_id: UUID,
        body: store.TrialRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        eid = str(experiment_id)
        result = store.record_trial(request.app.state.db, request.app.state.settings, eid, body)
        background_tasks.add_task(
            cache.prepare_if_complete,
            request.app.state.db,
            request.app.state.settings.project_id,
            eid,
        )
        return result

    @app.get(
        "/api/v1/projects/{project_id}/experiments",
        dependencies=[Depends(read_auth)],
        operation_id="listResearchExperiments",
    )
    def experiments(
        request: Request,
        project_id: UUID,
        limit: int = Query(25, ge=1, le=50),
        cursor: str | None = None,
    ) -> dict[str, Any]:
        if str(project_id) != request.app.state.settings.project_id:
            raise Problem(404, "not_found", "Project not found")
        key = decode_cursor(cursor, 2)
        condition = " AND (created_at_ms,experiment_id)<(?,?)" if key else ""
        with request.app.state.db.read() as conn:
            rows = conn.execute(
                "SELECT experiment_id,created_at_ms FROM experiment_plans WHERE project_id=?"
                + condition
                + " ORDER BY created_at_ms DESC,experiment_id DESC LIMIT ?",
                (str(project_id), *(key or []), limit + 1),
            ).fetchall()
            return {
                "items": [
                    store.plan(conn, str(project_id), r["experiment_id"]) for r in rows[:limit]
                ],
                "next_cursor": encode_cursor(
                    [rows[limit - 1]["created_at_ms"], rows[limit - 1]["experiment_id"]]
                )
                if len(rows) > limit
                else None,
            }

    @app.get(
        "/api/v1/experiments/{experiment_id}/results",
        dependencies=[Depends(read_auth)],
        operation_id="getResearchResults",
    )
    def results(request: Request, experiment_id: UUID) -> dict[str, Any]:
        return cache.get(
            request.app.state.db, request.app.state.settings.project_id, str(experiment_id)
        )

    @app.get(
        "/api/v1/experiments/{experiment_id}/trials",
        dependencies=[Depends(read_auth)],
        operation_id="listResearchTrials",
    )
    def trials(
        request: Request,
        experiment_id: UUID,
        limit: int = Query(100, ge=1, le=200),
        cursor: str | None = None,
        scenario: str | None = Query(None, max_length=50),
        arm: str | None = Query(None, max_length=50),
    ) -> dict[str, Any]:
        key = decode_cursor(cursor, 2)
        eid = str(experiment_id)
        clauses, args = ["t.experiment_id=?"], [eid]
        if key:
            clauses.append("(t.seed,t.trial_id)>(?,?)")
            args.extend(key)
        for column, value in (("scenario_key", scenario), ("policy_arm", arm)):
            if value is not None:
                clauses.append(f"t.{column}=?")
                args.append(value)
        with request.app.state.db.read() as conn:
            store.plan(conn, request.app.state.settings.project_id, eid)
            rows = [
                dict(r)
                for r in conn.execute(
                    (
                        "SELECT "
                        "t.*,a.source_kind,a.artifact_sha256,a.input_sha256,a.failure_code "
                        "FROM experiment_trials t JOIN research_trial_artifacts a ON "
                        "a.trial_id=t.trial_id WHERE "
                    )
                    + " AND ".join(clauses)
                    + " ORDER BY t.seed,t.trial_id LIMIT ?",
                    (*args, limit + 1),
                )
            ]
            for r in rows:
                r["model_config"] = json.loads(r.pop("model_config_json"))
            return {
                "items": rows[:limit],
                "next_cursor": encode_cursor([rows[limit - 1]["seed"], rows[limit - 1]["trial_id"]])
                if len(rows) > limit
                else None,
            }

    @app.get(
        "/api/v1/experiments/{experiment_id}/export.csv",
        dependencies=[Depends(read_auth)],
        operation_id="exportResearchCSV",
    )
    def csv(request: Request, experiment_id: UUID) -> Response:
        with request.app.state.db.read() as conn:
            content = store.export_csv(
                conn, request.app.state.settings.project_id, str(experiment_id)
            )
        return Response(
            content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="experiment-{experiment_id}.csv"',
                "Cache-Control": "no-store",
            },
        )

    @app.get(
        "/api/v1/experiments/{experiment_id}/trials/{trial_id}/{artifact}",
        dependencies=[Depends(read_auth)],
        operation_id="getResearchArtifact",
    )
    def artifact(request: Request, experiment_id: UUID, trial_id: UUID, artifact: str) -> Response:
        columns = {
            "truth.jsonl": "truth_jsonl",
            "observations.jsonl": "observations_jsonl",
            "proposals.json": "proposals_json",
        }
        if artifact not in columns:
            raise Problem(404, "not_found", "Artifact not found")
        with request.app.state.db.read() as conn:
            store.plan(conn, request.app.state.settings.project_id, str(experiment_id))
            row = conn.execute(
                (
                    "SELECT a.* FROM research_trial_artifacts a JOIN experiment_trials t "
                    "ON t.trial_id=a.trial_id WHERE t.experiment_id=? AND t.trial_id=?"
                ),
                (str(experiment_id), str(trial_id)),
            ).fetchone()
            if not row:
                raise Problem(404, "not_found", "Trial not found in this experiment")
            content = row[columns[artifact]]
            if content is None:
                raise Problem(404, "not_found", "No model proposal tape for a synthetic trial")
        return Response(
            content + "\n",
            media_type="application/json" if artifact.endswith(".json") else "application/x-ndjson",
            headers={
                "Content-Disposition": f'attachment; filename="{trial_id}-{artifact}"',
                "Cache-Control": "no-store",
            },
        )
