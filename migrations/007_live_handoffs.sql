-- Optional bounded live-agent handoffs. Existing walkthroughs remain fixtures.
ALTER TABLE guided_demo_sessions ADD COLUMN execution_mode TEXT NOT NULL DEFAULT 'fixture'
  CHECK(execution_mode IN ('fixture','live'));
ALTER TABLE guided_demo_sessions ADD COLUMN start_payload_sha256 TEXT NOT NULL DEFAULT '';
ALTER TABLE guided_demo_sessions ADD COLUMN model_name TEXT NOT NULL DEFAULT '';
ALTER TABLE guided_demo_sessions ADD COLUMN provider_host TEXT NOT NULL DEFAULT '';

-- Widen the output allowlist without losing fixture artifacts or their guards.
-- No table references artifacts, so the copy and rename remain inside this
-- migration's transaction with foreign-key enforcement enabled throughout.
CREATE TABLE guided_demo_artifacts_v007 (
  demo_id TEXT NOT NULL REFERENCES guided_demo_sessions(demo_id),
  slug TEXT NOT NULL CHECK(slug IN (
    'public-findings','dataset-analysis','final-brief',
    'agent-draft','agent-review','agent-repair','handoff-evidence'
  )),
  title TEXT NOT NULL,
  media_type TEXT NOT NULL CHECK(media_type='text/markdown'),
  content TEXT NOT NULL CHECK(length(content)<=50000),
  sha256 TEXT NOT NULL,
  created_at_ms INTEGER NOT NULL,
  PRIMARY KEY(demo_id,slug)
) STRICT;
INSERT INTO guided_demo_artifacts_v007(
  demo_id,slug,title,media_type,content,sha256,created_at_ms
) SELECT demo_id,slug,title,media_type,content,sha256,created_at_ms
FROM guided_demo_artifacts;
DROP TABLE guided_demo_artifacts;
ALTER TABLE guided_demo_artifacts_v007 RENAME TO guided_demo_artifacts;

-- Persist an attempt before provider I/O; its final receipt may update that row.
-- Uncertain provider outcomes remain visible rather than authorizing a new call.
CREATE TABLE guided_demo_model_calls (
  demo_id TEXT NOT NULL REFERENCES guided_demo_sessions(demo_id),
  call_index INTEGER NOT NULL CHECK(call_index BETWEEN 1 AND 3),
  phase TEXT NOT NULL CHECK(phase IN ('writer','reviewer','repair')),
  started_at_ms INTEGER NOT NULL,
  completed_at_ms INTEGER,
  state TEXT NOT NULL CHECK(state IN ('started','succeeded','failed','unknown')),
  error_code TEXT,
  input_tokens INTEGER CHECK(input_tokens IS NULL OR input_tokens>=0),
  output_tokens INTEGER CHECK(output_tokens IS NULL OR output_tokens>=0),
  request_sha256 TEXT NOT NULL,
  response_sha256 TEXT,
  response_model TEXT,
  PRIMARY KEY(demo_id,call_index)
) STRICT;
CREATE TRIGGER guided_demo_model_calls_no_delete BEFORE DELETE ON guided_demo_model_calls
BEGIN SELECT RAISE(ABORT,'retained model call attempt'); END;

-- Original draft, reviewer feedback and repair are separate retained columns.
CREATE TABLE guided_demo_handoffs (
  demo_id TEXT PRIMARY KEY REFERENCES guided_demo_sessions(demo_id),
  status TEXT NOT NULL CHECK(status IN ('draft','accepted','repaired','rejected')),
  revision INTEGER NOT NULL CHECK(revision>=1),
  writer_json TEXT NOT NULL CHECK(json_valid(writer_json)),
  review_json TEXT CHECK(review_json IS NULL OR json_valid(review_json)),
  repair_json TEXT CHECK(repair_json IS NULL OR json_valid(repair_json)),
  validation_json TEXT NOT NULL CHECK(json_valid(validation_json)),
  updated_at_ms INTEGER NOT NULL
) STRICT;
