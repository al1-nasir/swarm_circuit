export interface Page<T> {
  items: T[];
  next_cursor?: string | null;
}
export interface Config {
  projectId: string;
  operator: boolean;
  configured: boolean;
  backend: string;
}
export interface Run {
  run_id: string;
  name: string;
  mode: "observe" | "control";
  status: string;
  created_at_ms: number;
  updated_at_ms: number;
  started_at_ms: number | null;
  agent_count?: number;
  open_incident_count: number;
  metadata: {
    simulation?: boolean;
    research?: boolean;
    guided_demo?: boolean;
    demo_id?: string;
    diagnostic?: boolean;
  };
}
export interface Control {
  hold_task: boolean;
  resume_task: boolean;
  reason: string;
  runtime_session_id?: string;
  checkpoint_id?: string;
  fencing_epoch?: number;
  boundary_state?: string;
}
export interface GraphNode {
  id: string;
  node_kind: "task" | "agent";
  label: string;
  state?: string;
  state_version?: number;
  agent_id?: string;
  role?: string;
  incident_ids?: string[];
  control?: Control;
  trust_class?: string;
  evidence_kind: string;
}
export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  relation_kind: string;
  evidence_kind: string;
  evidence_event_id?: string;
}
export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  projection_version: number;
  coverage: string;
}
export interface Evidence {
  id: string;
  item_type: "event" | "span";
  label: string;
  event_kind?: string;
  occurred_at_ms: number;
  ingested_at_ms?: number;
  task_id?: string;
  agent_id?: string;
  approval_id?: string;
  trust_class: string;
  payload?: Record<string, unknown>;
  attributes?: Record<string, unknown>;
  trace_id?: string;
  span_id?: string;
  start_unix_ns?: string;
  end_unix_ns?: string | null;
  status_code?: string;
}
export interface Incident {
  incident_id: string;
  title: string;
  kind: string;
  severity: string;
  state: string;
  opened_at_ms: number;
  updated_at_ms: number;
  affected_task_ids: string[];
  evidence_event_ids: string[];
  current_evidence_event_ids: string[];
  uncertainty: string;
  metrics: Record<string, unknown>;
  detector_version: string;
  policy_sha256: string;
  resolution_reason?: string;
  trust_class: string;
}
export interface Approval {
  approval_id: string;
  action_fingerprint: string;
  related_task_id?: string;
  state: string;
  request_count: number;
  request_counts: Record<string, number>;
  simulation: boolean;
  resolution_trust: string;
  verified_resolution_source?: string;
  resolution_event_id?: string;
  resolution_actor?: string;
}
export interface Payment {
  payment_intent_id: string;
  task_id: string;
  approval_id?: string;
  domain: string;
  amount_decimal: string;
  asset_code: string;
  chain_network: string;
  state: string;
  simulation: boolean;
  state_evidence: string;
  control_blocked: boolean;
  uncertainty: string;
  gate_decision_count: number;
  has_deny: boolean;
  gate_decisions: {
    gate_decision_id: string;
    decision: string;
    evidence_event_id: string;
    trust_score?: number;
  }[];
  attempts: {
    payment_attempt_id: string;
    phase: string;
    receipt_trust: string;
    receipt_reference?: string;
    delivery_checks: {
      structural_ok: number;
      reason_code: string;
      evidence_event_id: string;
    }[];
  }[];
}
export interface Runtime {
  runtime_session_id: string;
  runtime_key: string;
  state: string;
  fencing_epoch: number;
  capabilities: string[];
  last_heartbeat_ms: number;
  checkpoints: {
    checkpoint_id: string;
    task_id: string;
    state: string;
    label: string;
  }[];
}
export interface Command {
  command_id: string;
  task_id: string;
  runtime_session_id: string;
  session_fencing_epoch: number;
  command_kind: "hold_task" | "resume_task";
  state: string;
  request_reason: string;
  expected_task_version: number;
  idempotency_key: string;
  checkpoint_id: string;
  created_at_ms: number;
  dispatched_at_ms?: number | null;
  completed_at_ms?: number | null;
  acknowledgements: {
    result: string;
    runtime_session_id: string;
    session_fencing_epoch: number;
    received_at_ms: number;
  }[];
}
export interface Snapshot {
  run: Run;
  taskGraph: Graph;
  agentGraph: Graph;
  timeline: Page<Evidence>;
  incidents: Incident[];
  approvals: Page<Approval>;
  payments: Page<Payment>;
  runtimes: Runtime[];
  commands: Page<Command>;
}
export interface Intent {
  key: string;
  runId: string;
  taskId: string;
  kind: string;
  createdAt: number;
}
