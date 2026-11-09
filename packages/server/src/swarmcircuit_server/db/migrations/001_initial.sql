-- SwarmCircuit Backend Schema v1.0 | SQLite 3.38+ (JSON functions required)
-- All IDs are application-generated UUID strings. All *_ms timestamps are UTC Unix epoch milliseconds.
-- Span timestamps use original OTLP Unix nanoseconds; never convert them to floating-point seconds.
-- Execute PRAGMA foreign_keys=ON on EVERY connection before beginning transactions.
-- WAL and busy_timeout are connection/deployment configuration, not transactional migrations.

CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  applied_at_ms INTEGER NOT NULL
) STRICT;

CREATE TABLE projects (
  project_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  environment TEXT NOT NULL DEFAULT 'local',
  created_at_ms INTEGER NOT NULL,
  settings_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(settings_json))
) STRICT;

CREATE TABLE telemetry_sources (
  source_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  source_key TEXT NOT NULL,
  source_kind TEXT NOT NULL CHECK(source_kind IN ('sdk','otlp','collector','gatekeep402','simulator','runtime')),
  display_name TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
  created_at_ms INTEGER NOT NULL,
  UNIQUE(project_id,source_key),
  UNIQUE(project_id,source_id)
) STRICT;

CREATE TABLE workflow_runs (
  run_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  external_run_key TEXT,
  name TEXT NOT NULL,
  mode TEXT NOT NULL CHECK(mode IN ('observe','control')),
  status TEXT NOT NULL DEFAULT 'created' CHECK(status IN ('created','running','waiting','stalled','recovering','completed','failed','cancelled')),
  experiment_seed INTEGER,
  root_trace_id TEXT,
  started_at_ms INTEGER,
  ended_at_ms INTEGER,
  created_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
  UNIQUE(project_id,external_run_key),
  UNIQUE(run_id,project_id),
  CHECK(ended_at_ms IS NULL OR started_at_ms IS NOT NULL)
) STRICT;

CREATE TABLE agents (
  agent_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  external_agent_key TEXT NOT NULL,
  display_name TEXT NOT NULL,
  role TEXT,
  framework TEXT,
  created_at_ms INTEGER NOT NULL,
  UNIQUE(project_id,external_agent_key),
  UNIQUE(project_id,agent_id)
) STRICT;

CREATE TABLE run_agents (
  run_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  joined_at_ms INTEGER NOT NULL,
  last_seen_at_ms INTEGER,
  PRIMARY KEY(run_id,agent_id),
  FOREIGN KEY(run_id,project_id) REFERENCES workflow_runs(run_id,project_id) ON DELETE CASCADE,
  FOREIGN KEY(project_id,agent_id) REFERENCES agents(project_id,agent_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE tasks (
  task_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
  external_task_key TEXT NOT NULL,
  assigned_agent_id TEXT,
  title TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'work',
  state TEXT NOT NULL DEFAULT 'created' CHECK(state IN ('created','ready','running','waiting_for_human','held','recovering','completed','failed','cancelled')),
  state_version INTEGER NOT NULL DEFAULT 0 CHECK(state_version >= 0),
  deadline_at_ms INTEGER,
  started_at_ms INTEGER,
  ended_at_ms INTEGER,
  created_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
  UNIQUE(run_id,external_task_key),
  UNIQUE(run_id,task_id),
  FOREIGN KEY(run_id,assigned_agent_id) REFERENCES run_agents(run_id,agent_id)
) STRICT;

CREATE TABLE task_dependencies (
  dependency_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
  blocked_task_id TEXT NOT NULL,
  prerequisite_task_id TEXT NOT NULL,
  relation_kind TEXT NOT NULL DEFAULT 'waits_for' CHECK(relation_kind IN ('waits_for','depends_on')),
  is_explicit INTEGER NOT NULL CHECK(is_explicit IN (0,1)),
  evidence_event_id TEXT, -- back-referenced to event_log by app after source insertion
  recorded_at_ms INTEGER NOT NULL,
  UNIQUE(run_id,blocked_task_id,prerequisite_task_id,relation_kind),
  FOREIGN KEY(run_id,blocked_task_id) REFERENCES tasks(run_id,task_id) ON DELETE CASCADE,
  FOREIGN KEY(run_id,prerequisite_task_id) REFERENCES tasks(run_id,task_id) ON DELETE CASCADE,
  CHECK(blocked_task_id <> prerequisite_task_id)
) STRICT;

CREATE TABLE task_attempts (
  attempt_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  attempt_no INTEGER NOT NULL CHECK(attempt_no >= 1),
  state TEXT NOT NULL CHECK(state IN ('started','succeeded','failed','cancelled','unknown')),
  retry_reason TEXT,
  idempotency_key TEXT,
  started_at_ms INTEGER NOT NULL,
  ended_at_ms INTEGER,
  UNIQUE(task_id,attempt_no),
  UNIQUE(run_id,idempotency_key),
  FOREIGN KEY(run_id,task_id) REFERENCES tasks(run_id,task_id) ON DELETE CASCADE
) STRICT;

CREATE TABLE approvals (
  approval_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
  canonical_approval_key TEXT NOT NULL,
  action_fingerprint TEXT NOT NULL,
  related_task_id TEXT,
  state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','approved','denied','expired','cancelled')),
  requested_at_ms INTEGER NOT NULL,
  resolved_at_ms INTEGER,
  verified_resolution_source TEXT,
  resolution_actor TEXT,
  resolution_event_id TEXT,
  UNIQUE(run_id,canonical_approval_key),
  UNIQUE(run_id,approval_id),
  FOREIGN KEY(run_id,related_task_id) REFERENCES tasks(run_id,task_id),
  CHECK((state='pending' AND resolved_at_ms IS NULL) OR (state<>'pending' AND resolved_at_ms IS NOT NULL))
) STRICT;

CREATE TABLE approval_requests (
  request_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  approval_id TEXT NOT NULL,
  requester_task_id TEXT,
  request_key TEXT NOT NULL,
  disposition TEXT NOT NULL CHECK(disposition IN ('presented','coalesced','rejected')),
  requested_at_ms INTEGER NOT NULL,
  UNIQUE(run_id,request_key),
  FOREIGN KEY(run_id,approval_id) REFERENCES approvals(run_id,approval_id) ON DELETE CASCADE,
  FOREIGN KEY(run_id,requester_task_id) REFERENCES tasks(run_id,task_id)
) STRICT;

-- OTel span store: metadata-only normalized fields, redacted attributes, exact nanosecond timestamps.
CREATE TABLE trace_spans (
  span_row_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
  project_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  trace_id TEXT NOT NULL CHECK(length(trace_id)=32),
  span_id TEXT NOT NULL CHECK(length(span_id)=16),
  parent_span_id TEXT CHECK(parent_span_id IS NULL OR length(parent_span_id)=16),
  name TEXT NOT NULL,
  span_kind TEXT,
  status_code TEXT,
  start_unix_ns INTEGER NOT NULL,
  end_unix_ns INTEGER,
  agent_id TEXT,
  task_id TEXT,
  attributes_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(attributes_json)),
  received_at_ms INTEGER NOT NULL,
  UNIQUE(run_id,trace_id,span_id),
  UNIQUE(run_id,span_row_id),
  FOREIGN KEY(run_id,project_id) REFERENCES workflow_runs(run_id,project_id),
  FOREIGN KEY(project_id,source_id) REFERENCES telemetry_sources(project_id,source_id),
  FOREIGN KEY(run_id,task_id) REFERENCES tasks(run_id,task_id),
  FOREIGN KEY(run_id,agent_id) REFERENCES run_agents(run_id,agent_id),
  CHECK(end_unix_ns IS NULL OR end_unix_ns >= start_unix_ns)
) STRICT;

CREATE TABLE span_links (
  link_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  source_span_row_id TEXT NOT NULL,
  target_trace_id TEXT NOT NULL CHECK(length(target_trace_id)=32),
  target_span_id TEXT NOT NULL CHECK(length(target_span_id)=16),
  attributes_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(attributes_json)),
  FOREIGN KEY(run_id,source_span_row_id) REFERENCES trace_spans(run_id,span_row_id) ON DELETE CASCADE
) STRICT;

-- Run events are ingested facts/reports, not automatic ground truth. Treat as append-only at API layer.
CREATE TABLE run_events (
  event_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
  project_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  source_event_key TEXT NOT NULL,
  event_kind TEXT NOT NULL,
  trust_class TEXT NOT NULL CHECK(trust_class IN ('self_report','sdk_observation','service_receipt','simulation_truth','derived')),
  agent_id TEXT,
  task_id TEXT,
  span_row_id TEXT,
  approval_id TEXT,
  occurred_at_ms INTEGER NOT NULL,
  ingested_at_ms INTEGER NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(payload_json)),
  UNIQUE(source_id,source_event_key),
  UNIQUE(run_id,event_id),
  FOREIGN KEY(run_id,project_id) REFERENCES workflow_runs(run_id,project_id),
  FOREIGN KEY(project_id,source_id) REFERENCES telemetry_sources(project_id,source_id),
  FOREIGN KEY(run_id,agent_id) REFERENCES run_agents(run_id,agent_id),
  FOREIGN KEY(run_id,task_id) REFERENCES tasks(run_id,task_id),
  FOREIGN KEY(run_id,span_row_id) REFERENCES trace_spans(run_id,span_row_id),
  FOREIGN KEY(run_id,approval_id) REFERENCES approvals(run_id,approval_id)
) STRICT;

CREATE TABLE agent_messages (
  message_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
  from_agent_id TEXT NOT NULL,
  to_agent_id TEXT NOT NULL,
  task_id TEXT,
  message_kind TEXT NOT NULL DEFAULT 'handoff',
  content_sha256 TEXT,
  content_preview_redacted TEXT, -- NULL by default, explicit opt-in only
  token_count INTEGER CHECK(token_count IS NULL OR token_count >= 0),
  occurred_at_ms INTEGER NOT NULL,
  evidence_event_id TEXT REFERENCES run_events(event_id),
  FOREIGN KEY(run_id,from_agent_id) REFERENCES run_agents(run_id,agent_id),
  FOREIGN KEY(run_id,to_agent_id) REFERENCES run_agents(run_id,agent_id),
  FOREIGN KEY(run_id,task_id) REFERENCES tasks(run_id,task_id)
) STRICT;

-- UI projection: graph relationships here MUST NOT be used as authorization evidence.
CREATE TABLE graph_nodes (
  node_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
  node_kind TEXT NOT NULL CHECK(node_kind IN ('agent','task','approval','tool','resource')),
  entity_ref_id TEXT NOT NULL,
  display_label TEXT NOT NULL,
  projection_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(projection_json)),
  updated_at_ms INTEGER NOT NULL,
  UNIQUE(run_id,node_kind,entity_ref_id),
  UNIQUE(run_id,node_id)
) STRICT;

CREATE TABLE graph_edges (
  edge_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
  source_node_id TEXT NOT NULL,
  target_node_id TEXT NOT NULL,
  relation_kind TEXT NOT NULL CHECK(relation_kind IN ('delegates_to','depends_on','messages_to','uses_tool','waits_for','retry_of','triggers')),
  evidence_kind TEXT NOT NULL CHECK(evidence_kind IN ('explicit','inferred')),
  confidence REAL CHECK(confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  evidence_event_id TEXT REFERENCES run_events(event_id),
  created_at_ms INTEGER NOT NULL,
  FOREIGN KEY(run_id,source_node_id) REFERENCES graph_nodes(run_id,node_id) ON DELETE CASCADE,
  FOREIGN KEY(run_id,target_node_id) REFERENCES graph_nodes(run_id,node_id) ON DELETE CASCADE,
  CHECK(source_node_id <> target_node_id)
) STRICT;

CREATE TABLE incidents (
  incident_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
  detector_key TEXT NOT NULL,
  fingerprint TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('approval_storm','retry_amplification','task_stall','dependency_cycle','cascade','policy_warning')),
  severity TEXT NOT NULL CHECK(severity IN ('info','warning','critical')),
  state TEXT NOT NULL DEFAULT 'open' CHECK(state IN ('open','acknowledged','resolved','suppressed')),
  title TEXT NOT NULL,
  evidence_summary TEXT NOT NULL,
  opened_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL,
  resolved_at_ms INTEGER,
  UNIQUE(run_id,detector_key,fingerprint),
  UNIQUE(run_id,incident_id)
) STRICT;

CREATE TABLE incident_evidence (
  evidence_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  incident_id TEXT NOT NULL,
  event_id TEXT,
  span_row_id TEXT,
  note TEXT,
  FOREIGN KEY(run_id,incident_id) REFERENCES incidents(run_id,incident_id) ON DELETE CASCADE,
  FOREIGN KEY(event_id) REFERENCES run_events(event_id),
  FOREIGN KEY(run_id,span_row_id) REFERENCES trace_spans(run_id,span_row_id),
  CHECK(event_id IS NOT NULL OR span_row_id IS NOT NULL)
) STRICT;

CREATE TABLE control_policies (
  policy_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  policy_key TEXT NOT NULL,
  revision INTEGER NOT NULL CHECK(revision >= 1),
  policy_kind TEXT NOT NULL,
  config_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(config_json)),
  auto_apply INTEGER NOT NULL DEFAULT 0 CHECK(auto_apply IN (0,1)),
  created_at_ms INTEGER NOT NULL,
  UNIQUE(project_id,policy_key,revision)
) STRICT;

CREATE TABLE runtime_sessions (
  runtime_session_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
  runtime_key TEXT NOT NULL,
  actor_subject TEXT NOT NULL,
  capabilities_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(capabilities_json)),
  fencing_epoch INTEGER NOT NULL DEFAULT 1 CHECK(fencing_epoch >= 1),
  state TEXT NOT NULL DEFAULT 'connected' CHECK(state IN ('connected','disconnected','expired')),
  connected_at_ms INTEGER NOT NULL,
  last_heartbeat_ms INTEGER NOT NULL,
  UNIQUE(run_id,runtime_key,fencing_epoch),
  UNIQUE(run_id,runtime_session_id)
) STRICT;

CREATE TABLE control_commands (
  command_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
  runtime_session_id TEXT NOT NULL,
  incident_id TEXT,
  task_id TEXT,
  approval_id TEXT,
  command_kind TEXT NOT NULL CHECK(command_kind IN ('hold_task','resume_task','cancel_task','coalesce_approval')),
  idempotency_key TEXT NOT NULL,
  required_capability TEXT NOT NULL,
  expected_task_version INTEGER CHECK(expected_task_version IS NULL OR expected_task_version >= 0),
  session_fencing_epoch INTEGER NOT NULL CHECK(session_fencing_epoch >= 1),
  state TEXT NOT NULL DEFAULT 'queued' CHECK(state IN ('queued','dispatched','applied','rejected','timed_out','unknown')),
  initiated_by TEXT NOT NULL CHECK(initiated_by IN ('operator','policy','experiment')),
  request_reason TEXT NOT NULL,
  created_at_ms INTEGER NOT NULL,
  dispatched_at_ms INTEGER,
  completed_at_ms INTEGER,
  UNIQUE(run_id,idempotency_key),
  UNIQUE(run_id,command_id),
  FOREIGN KEY(run_id,runtime_session_id) REFERENCES runtime_sessions(run_id,runtime_session_id),
  FOREIGN KEY(run_id,incident_id) REFERENCES incidents(run_id,incident_id),
  FOREIGN KEY(run_id,task_id) REFERENCES tasks(run_id,task_id),
  FOREIGN KEY(run_id,approval_id) REFERENCES approvals(run_id,approval_id),
  CHECK(task_id IS NOT NULL OR approval_id IS NOT NULL)
) STRICT;

CREATE TABLE control_acknowledgements (
  acknowledgement_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  command_id TEXT NOT NULL,
  runtime_session_id TEXT NOT NULL,
  session_fencing_epoch INTEGER NOT NULL,
  ack_key TEXT NOT NULL,
  result TEXT NOT NULL CHECK(result IN ('applied','rejected','failed')),
  result_detail TEXT,
  received_at_ms INTEGER NOT NULL,
  UNIQUE(runtime_session_id,ack_key),
  FOREIGN KEY(run_id,command_id) REFERENCES control_commands(run_id,command_id),
  FOREIGN KEY(run_id,runtime_session_id) REFERENCES runtime_sessions(run_id,runtime_session_id)
) STRICT;

-- Payment domain: GateKeep402 is an optional adapter, never the core run identity.
CREATE TABLE payment_intents (
  payment_intent_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
  task_id TEXT,
  approval_id TEXT,
  intent_key TEXT NOT NULL,
  domain TEXT NOT NULL,
  resource_label TEXT,
  chain_network TEXT,
  asset_code TEXT NOT NULL,
  amount_decimal TEXT NOT NULL, -- exact decimal string; validate with Python Decimal
  state TEXT NOT NULL CHECK(state IN ('proposed','gated','authorized','submitted','settled','failed','unknown','denied')),
  created_at_ms INTEGER NOT NULL,
  UNIQUE(run_id,intent_key),
  UNIQUE(run_id,payment_intent_id),
  FOREIGN KEY(run_id,task_id) REFERENCES tasks(run_id,task_id),
  FOREIGN KEY(run_id,approval_id) REFERENCES approvals(run_id,approval_id)
) STRICT;

CREATE TABLE payment_gate_decisions (
  gate_decision_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  payment_intent_id TEXT NOT NULL,
  decision TEXT NOT NULL CHECK(decision IN ('allow','ask','deny')),
  trust_score REAL CHECK(trust_score IS NULL OR (trust_score>=0 AND trust_score<=1)),
  policy_revision TEXT,
  evidence_event_id TEXT REFERENCES run_events(event_id),
  decided_at_ms INTEGER NOT NULL,
  FOREIGN KEY(run_id,payment_intent_id) REFERENCES payment_intents(run_id,payment_intent_id) ON DELETE CASCADE
) STRICT;

CREATE TABLE payment_attempts (
  payment_attempt_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  payment_intent_id TEXT NOT NULL,
  attempt_no INTEGER NOT NULL CHECK(attempt_no >= 1),
  idempotency_key TEXT NOT NULL,
  phase TEXT NOT NULL CHECK(phase IN ('authorized','submitted','settlement_unknown','settled_confirmed','failed')),
  receipt_reference TEXT, -- identifier only; no private wallet data
  receipt_trust TEXT NOT NULL DEFAULT 'none' CHECK(receipt_trust IN ('none','self_report','service_verified','simulator_truth')),
  submitted_at_ms INTEGER,
  confirmed_at_ms INTEGER,
  UNIQUE(payment_intent_id,attempt_no),
  UNIQUE(run_id,idempotency_key),
  FOREIGN KEY(run_id,payment_intent_id) REFERENCES payment_intents(run_id,payment_intent_id) ON DELETE CASCADE,
  CHECK(phase<>'settled_confirmed' OR (confirmed_at_ms IS NOT NULL AND receipt_trust IN ('service_verified','simulator_truth')))
) STRICT;

CREATE TABLE delivery_verifications (
  delivery_verification_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
  payment_attempt_id TEXT NOT NULL REFERENCES payment_attempts(payment_attempt_id),
  structural_ok INTEGER NOT NULL CHECK(structural_ok IN (0,1)),
  reason_code TEXT NOT NULL,
  checked_at_ms INTEGER NOT NULL,
  evidence_event_id TEXT REFERENCES run_events(event_id)
) STRICT;

CREATE TABLE experiment_plans (
  experiment_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  protocol_version TEXT NOT NULL,
  protocol_sha256 TEXT,
  specification_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(specification_json)),
  created_at_ms INTEGER NOT NULL
) STRICT;

CREATE TABLE experiment_trials (
  trial_id TEXT PRIMARY KEY,
  experiment_id TEXT NOT NULL REFERENCES experiment_plans(experiment_id) ON DELETE CASCADE,
  run_id TEXT NOT NULL UNIQUE REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
  scenario_key TEXT NOT NULL,
  policy_arm TEXT NOT NULL,
  seed INTEGER NOT NULL,
  implementation_sha TEXT NOT NULL,
  model_config_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(model_config_json)),
  state TEXT NOT NULL CHECK(state IN ('pending','running','completed','failed')),
  started_at_ms INTEGER,
  finished_at_ms INTEGER,
  UNIQUE(experiment_id,scenario_key,policy_arm,seed)
) STRICT;

CREATE TABLE experiment_measurements (
  measurement_id TEXT PRIMARY KEY,
  trial_id TEXT NOT NULL REFERENCES experiment_trials(trial_id) ON DELETE CASCADE,
  metric_key TEXT NOT NULL,
  metric_value REAL NOT NULL,
  unit TEXT NOT NULL,
  denominator REAL,
  computed_at_ms INTEGER NOT NULL,
  UNIQUE(trial_id,metric_key),
  CHECK(denominator IS NULL OR denominator>0)
) STRICT;

-- At-least-once notifications; do not use these as proof that a control applied.
CREATE TABLE ui_outbox (
  notification_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
  topic TEXT NOT NULL,
  entity_id TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(payload_json)),
  created_at_ms INTEGER NOT NULL,
  published_at_ms INTEGER,
  attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0)
) STRICT;

-- Indices for the main workload: run listing, timeline, graph, incident queue, approvals, and command poll.
CREATE INDEX idx_runs_project_status ON workflow_runs(project_id,status,updated_at_ms DESC);
CREATE INDEX idx_tasks_run_state ON tasks(run_id,state,updated_at_ms DESC);
CREATE INDEX idx_tasks_agent ON tasks(run_id,assigned_agent_id,state);
CREATE INDEX idx_attempts_task_time ON task_attempts(task_id,started_at_ms DESC);
CREATE INDEX idx_dep_prereq ON task_dependencies(run_id,prerequisite_task_id);
CREATE INDEX idx_approvals_pending ON approvals(run_id,requested_at_ms DESC) WHERE state='pending';
CREATE INDEX idx_approval_requests_approval ON approval_requests(approval_id,requested_at_ms);
CREATE INDEX idx_spans_waterfall ON trace_spans(run_id,start_unix_ns,span_id);
CREATE INDEX idx_spans_trace ON trace_spans(trace_id,span_id);
CREATE INDEX idx_events_timeline ON run_events(run_id,occurred_at_ms,event_id);
CREATE INDEX idx_events_kind ON run_events(run_id,event_kind,occurred_at_ms);
CREATE INDEX idx_messages_pair ON agent_messages(run_id,from_agent_id,to_agent_id,occurred_at_ms);
CREATE INDEX idx_graph_edges_run ON graph_edges(run_id,relation_kind);
CREATE INDEX idx_incidents_queue ON incidents(run_id,state,severity,updated_at_ms DESC);
CREATE INDEX idx_incident_evidence_event ON incident_evidence(event_id);
CREATE INDEX idx_runtime_heartbeat ON runtime_sessions(run_id,state,last_heartbeat_ms);
CREATE INDEX idx_commands_poll ON control_commands(runtime_session_id,state,created_at_ms);
CREATE INDEX idx_commands_incident ON control_commands(run_id,incident_id,created_at_ms);
CREATE INDEX idx_payment_intents_run ON payment_intents(run_id,state,created_at_ms);
CREATE INDEX idx_payment_attempts_intent ON payment_attempts(payment_intent_id,attempt_no);
CREATE INDEX idx_trial_group ON experiment_trials(experiment_id,scenario_key,policy_arm);
CREATE INDEX idx_outbox_pending ON ui_outbox(created_at_ms) WHERE published_at_ms IS NULL;

-- Prevent updates to ingested provenance events. Deletion is intentionally supported for explicit retention purges.
CREATE TRIGGER run_events_no_update BEFORE UPDATE ON run_events
BEGIN SELECT RAISE(ABORT,'run_events are immutable; append a correcting event'); END;
CREATE TRIGGER control_ack_no_update BEFORE UPDATE ON control_acknowledgements
BEGIN SELECT RAISE(ABORT,'control acknowledgements are immutable'); END;
CREATE TRIGGER payment_gate_no_update BEFORE UPDATE ON payment_gate_decisions
BEGIN SELECT RAISE(ABORT,'gate decisions are immutable'); END;

-- Guard against claiming a runtime action was applied before an authenticated ack was persisted.
-- Authenticated actor/session validation must occur in the FastAPI control endpoint first.
CREATE TRIGGER control_applied_requires_ack BEFORE UPDATE OF state ON control_commands
WHEN NEW.state='applied' AND NOT EXISTS (
  SELECT 1 FROM control_acknowledgements a
  WHERE a.command_id=NEW.command_id AND a.run_id=NEW.run_id
    AND a.runtime_session_id=NEW.runtime_session_id
    AND a.session_fencing_epoch=NEW.session_fencing_epoch AND a.result='applied'
)
BEGIN SELECT RAISE(ABORT,'cannot mark command applied without matching runtime acknowledgement'); END;

-- State 'settled' must be grounded in independently verified/simulated evidence, not a model assertion.
CREATE TRIGGER payment_settled_requires_receipt BEFORE UPDATE OF state ON payment_intents
WHEN NEW.state='settled' AND NOT EXISTS (
  SELECT 1 FROM payment_attempts p WHERE p.payment_intent_id=NEW.payment_intent_id
    AND p.run_id=NEW.run_id AND p.phase='settled_confirmed'
    AND p.receipt_trust IN ('service_verified','simulator_truth')
)
BEGIN SELECT RAISE(ABORT,'cannot mark settled without trusted receipt'); END;
