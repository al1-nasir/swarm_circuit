-- Phase 4 context and explicitly simulated authority. Original migrations are preserved.
CREATE TABLE payment_observation_context (
  payment_intent_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  scope_fingerprint TEXT NOT NULL,
  descriptor_sha256 TEXT NOT NULL,
  integration_version TEXT NOT NULL,
  FOREIGN KEY(run_id,payment_intent_id) REFERENCES payment_intents(run_id,payment_intent_id)
) STRICT;

CREATE TABLE mock_authority_callbacks (
  callback_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES workflow_runs(run_id),
  idempotency_key TEXT NOT NULL,
  callback_kind TEXT NOT NULL CHECK(callback_kind IN ('approval','settlement')),
  request_sha256 TEXT NOT NULL,
  approval_id TEXT UNIQUE,
  payment_attempt_id TEXT UNIQUE,
  receipt_reference TEXT UNIQUE,
  event_id TEXT NOT NULL UNIQUE,
  response_json TEXT NOT NULL CHECK(json_valid(response_json)),
  created_at_ms INTEGER NOT NULL,
  UNIQUE(run_id,idempotency_key),
  FOREIGN KEY(run_id,approval_id) REFERENCES approvals(run_id,approval_id),
  FOREIGN KEY(payment_attempt_id) REFERENCES payment_attempts(payment_attempt_id),
  FOREIGN KEY(run_id,event_id) REFERENCES run_events(run_id,event_id)
) STRICT;
CREATE TRIGGER mock_callbacks_no_update BEFORE UPDATE ON mock_authority_callbacks
BEGIN SELECT RAISE(ABORT,'mock callbacks are immutable'); END;
