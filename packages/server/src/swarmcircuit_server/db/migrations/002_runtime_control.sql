-- Additive runtime authority and cooperative boundary context. Original 001 is frozen.
CREATE TABLE runtime_credentials (
  runtime_session_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  runtime_key TEXT NOT NULL,
  nonce_sha256 TEXT NOT NULL,
  token_sha256 TEXT NOT NULL UNIQUE,
  expires_at_ms INTEGER NOT NULL,
  UNIQUE(run_id,runtime_key,nonce_sha256),
  FOREIGN KEY(run_id,runtime_session_id) REFERENCES runtime_sessions(run_id,runtime_session_id)
) STRICT;

CREATE TABLE runtime_task_owners (
  run_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  runtime_session_id TEXT NOT NULL,
  PRIMARY KEY(run_id,task_id),
  FOREIGN KEY(run_id,task_id) REFERENCES tasks(run_id,task_id),
  FOREIGN KEY(run_id,runtime_session_id) REFERENCES runtime_sessions(run_id,runtime_session_id)
) STRICT;

CREATE TABLE runtime_checkpoints (
  checkpoint_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  runtime_session_id TEXT NOT NULL,
  checkpoint_key TEXT NOT NULL,
  label TEXT NOT NULL,
  reversible INTEGER NOT NULL CHECK(reversible=1),
  state TEXT NOT NULL CHECK(state IN ('available','parked','released','unknown')),
  generation INTEGER NOT NULL CHECK(generation>=1),
  saved_task_state TEXT NOT NULL,
  created_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL,
  UNIQUE(runtime_session_id,checkpoint_key),
  UNIQUE(task_id,generation),
  FOREIGN KEY(run_id,task_id) REFERENCES tasks(run_id,task_id),
  FOREIGN KEY(run_id,runtime_session_id) REFERENCES runtime_sessions(run_id,runtime_session_id)
) STRICT;
CREATE UNIQUE INDEX idx_checkpoint_active ON runtime_checkpoints(task_id)
  WHERE state IN ('available','parked','unknown');

CREATE TABLE control_command_context (
  command_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  checkpoint_id TEXT NOT NULL REFERENCES runtime_checkpoints(checkpoint_id),
  request_sha256 TEXT NOT NULL,
  prior_task_state TEXT NOT NULL,
  FOREIGN KEY(run_id,command_id) REFERENCES control_commands(run_id,command_id)
) STRICT;

CREATE TABLE runtime_approval_presentations (
  presentation_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  approval_id TEXT NOT NULL,
  runtime_session_id TEXT NOT NULL,
  origin_event_id TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('claimed','presented','unknown')),
  created_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL,
  UNIQUE(run_id,approval_id),
  FOREIGN KEY(run_id,approval_id) REFERENCES approvals(run_id,approval_id),
  FOREIGN KEY(run_id,runtime_session_id) REFERENCES runtime_sessions(run_id,runtime_session_id),
  FOREIGN KEY(run_id,origin_event_id) REFERENCES run_events(run_id,event_id)
) STRICT;

CREATE TABLE control_policy_requests (
  request_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES workflow_runs(run_id),
  idempotency_key TEXT NOT NULL,
  request_sha256 TEXT NOT NULL,
  result_json TEXT NOT NULL CHECK(json_valid(result_json)),
  created_at_ms INTEGER NOT NULL,
  UNIQUE(run_id,idempotency_key)
) STRICT;
