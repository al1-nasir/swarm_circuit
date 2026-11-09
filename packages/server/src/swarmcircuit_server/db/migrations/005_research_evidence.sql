-- Additive research artifact seals. Original experiment tables and source contracts stay frozen.
CREATE TABLE research_trial_artifacts (
  trial_id TEXT PRIMARY KEY REFERENCES experiment_trials(trial_id) ON DELETE CASCADE,
  source_kind TEXT NOT NULL CHECK(source_kind IN ('synthetic','llm_workload_replay')),
  input_sha256 TEXT NOT NULL,
  artifact_sha256 TEXT NOT NULL,
  truth_jsonl TEXT NOT NULL,
  observations_jsonl TEXT NOT NULL,
  proposals_json TEXT CHECK(proposals_json IS NULL OR json_valid(proposals_json)),
  provenance_json TEXT NOT NULL CHECK(json_valid(provenance_json)),
  failure_code TEXT
) STRICT;
CREATE TRIGGER research_artifacts_no_update BEFORE UPDATE ON research_trial_artifacts
BEGIN SELECT RAISE(ABORT,'sealed research artifact'); END;
CREATE TRIGGER research_artifacts_no_delete BEFORE DELETE ON research_trial_artifacts
BEGIN SELECT RAISE(ABORT,'sealed research artifact'); END;
