-- Guided local-fixture workflows and persisted completed experiment aggregates.
CREATE TABLE guided_demo_sessions (
  demo_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id),
  run_id TEXT UNIQUE REFERENCES workflow_runs(run_id),
  idempotency_key TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('starting','waiting','running','completed','denied','expired','interrupted','failed')),
  permission TEXT NOT NULL DEFAULT 'pending' CHECK(permission IN ('pending','approved','denied')),
  approval_id TEXT REFERENCES approvals(approval_id),
  task_ids_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(task_ids_json)),
  created_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL,
  expires_at_ms INTEGER NOT NULL,
  failure_code TEXT,
  UNIQUE(project_id,idempotency_key)
) STRICT;
CREATE UNIQUE INDEX guided_demo_one_active ON guided_demo_sessions(project_id)
WHERE state IN ('starting','waiting','running');
CREATE TABLE guided_demo_actions (
  action_id INTEGER PRIMARY KEY AUTOINCREMENT,
  demo_id TEXT NOT NULL REFERENCES guided_demo_sessions(demo_id),
  at_ms INTEGER NOT NULL,
  kind TEXT NOT NULL,
  message TEXT NOT NULL,
  idempotency_key TEXT,
  request_sha256 TEXT,
  UNIQUE(demo_id,idempotency_key)
) STRICT;
CREATE TABLE guided_demo_artifacts (
  demo_id TEXT NOT NULL REFERENCES guided_demo_sessions(demo_id),
  slug TEXT NOT NULL CHECK(slug IN ('public-findings','dataset-analysis','final-brief')),
  title TEXT NOT NULL,
  media_type TEXT NOT NULL CHECK(media_type='text/markdown'),
  content TEXT NOT NULL CHECK(length(content)<=50000),
  sha256 TEXT NOT NULL,
  created_at_ms INTEGER NOT NULL,
  PRIMARY KEY(demo_id,slug)
) STRICT;
CREATE TABLE guided_demo_effects (
  demo_id TEXT NOT NULL REFERENCES guided_demo_sessions(demo_id),
  role TEXT NOT NULL,
  at_ms INTEGER NOT NULL,
  permission TEXT NOT NULL CHECK(permission='approved'),
  result_json TEXT NOT NULL CHECK(json_valid(result_json)),
  PRIMARY KEY(demo_id,role)
) STRICT;
CREATE TRIGGER guided_demo_effects_no_update BEFORE UPDATE ON guided_demo_effects
BEGIN SELECT RAISE(ABORT,'append-only demo effect'); END;
CREATE TRIGGER guided_demo_effects_no_delete BEFORE DELETE ON guided_demo_effects
BEGIN SELECT RAISE(ABORT,'append-only demo effect'); END;
CREATE TABLE research_result_cache (
  experiment_id TEXT PRIMARY KEY REFERENCES experiment_plans(experiment_id),
  trial_count INTEGER NOT NULL,
  result_json TEXT NOT NULL CHECK(json_valid(result_json)),
  created_at_ms INTEGER NOT NULL
) STRICT;
