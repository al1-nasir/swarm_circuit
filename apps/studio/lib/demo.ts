export type DemoState =
  | "starting"
  | "waiting"
  | "running"
  | "completed"
  | "denied"
  | "expired"
  | "interrupted"
  | "failed";
export type DemoArtifact = {
  slug: string;
  title: string;
  media_type: string;
  sha256: string;
  created_at_ms: number;
};
export type DemoDecision = "approved" | "denied";
export type DemoMode = "fixture" | "live";
export type DemoStartIntent = { key: string; body?: string };
export type DemoCapabilities = {
  fixture: boolean;
  live: {
    available: boolean;
    configured_model: string | null;
    provider_host: string | null;
    call_limit: number;
    reason: string | null;
  };
};
export type DemoModel = {
  configured_model: string | null;
  provider_host: string | null;
  provider_reported_model: string | null;
  call_limit: number;
  calls: number;
  input_tokens: number | null;
  output_tokens: number | null;
  repair_used: boolean;
  review_status: "not_started" | "draft" | "accepted" | "repaired" | "rejected";
};
export function demoStartBody(mode: DemoMode) {
  return mode === "live" ? '{"mode":"live"}' : "{}";
}
export function demoRestoreStartBody(intent: DemoStartIntent) {
  // Older saved intents predate live mode and always submitted an empty body.
  if (intent.body === undefined) return "{}";
  return ["{}", '{"mode":"live"}'].includes(intent.body) ? intent.body : null;
}
export function demoReviewLabel(
  model: Pick<DemoModel, "review_status">,
  terminal = false,
) {
  if (terminal && model.review_status === "not_started")
    return "No checked model draft was produced";
  if (terminal && model.review_status === "draft")
    return "Draft retained; the handoff did not finish";
  return {
    not_started: "Waiting for the writer",
    draft: "Draft saved; review pending",
    accepted: "Reviewer accepted; typed facts checked",
    repaired: "Repair passed typed fact checks; no second model review",
    rejected: "Handoff rejected; no checked brief published",
  }[model.review_status];
}
export function demoFailureLabel(code: string | null | undefined) {
  return (
    (
      {
        live_unconfigured:
          "The live provider is not configured on this server.",
        provider_unavailable:
          "The model provider did not complete this request.",
        provider_timeout: "The model provider exceeded the request time limit.",
        invalid_model_output:
          "The agent response did not match the required output format.",
        model_budget_exhausted: "The three-call model limit was reached.",
        handoff_rejected: "The agent handoff did not pass its factual checks.",
        interrupted: "The local worker stopped before completing the handoff.",
        worker_unavailable:
          "The local worker stopped before completing the walkthrough.",
      } as Record<string, string>
    )[code || ""] ||
    "The walkthrough stopped before its result could be confirmed."
  );
}
export type DemoDecisionIntent = {
  key: string;
  decision: DemoDecision;
  requestSha256?: string;
};
export function demoDecisionBody(decision: DemoDecision, reason: string) {
  return JSON.stringify({ decision, reason: reason.trim() });
}
export async function demoDecisionHash(body: string) {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(body),
  );
  return Array.from(new Uint8Array(digest), (n) =>
    n.toString(16).padStart(2, "0"),
  ).join("");
}
export type Demo = {
  demo_id: string;
  run_id: string | null;
  state: DemoState;
  permission: "pending" | "approved" | "denied";
  approval_id: string | null;
  created_at_ms: number;
  updated_at_ms: number;
  expires_at_ms: number;
  worker_connected: boolean;
  active_holds: number;
  progress: { completed: number; total: number; waiting: number };
  request_count: number;
  protected_effects: number;
  public_completed: boolean;
  artifacts: DemoArtifact[];
  timeline: { at_ms: number; kind: string; message: string }[];
  task_ids: Record<string, string>;
  execution_mode?: DemoMode;
  model?: DemoModel;
  model_calls?: number;
  failure_code?: string | null;
};
export const demoTerminal = (state: DemoState) =>
  ["completed", "denied", "expired", "interrupted", "failed"].includes(state);
export function demoHeadline(
  demo: Pick<
    Demo,
    "state" | "permission" | "active_holds" | "public_completed"
  >,
) {
  if (demo.state === "completed") return "Your analyst brief is ready.";
  if (demo.state === "denied")
    return "Access denied. Public findings are still available.";
  if (["expired", "interrupted"].includes(demo.state))
    return "This walkthrough has ended.";
  if (demo.state === "failed") return "The walkthrough needs a fresh start.";
  if (demo.active_holds > 0) return "Some tasks are paused by an operator.";
  if (demo.permission === "approved")
    return "Access granted. The team is finishing the brief.";
  if (demo.state === "starting") return "Getting the local team ready…";
  if (demo.public_completed)
    return "Public findings are ready. Dataset access needs your review.";
  return "Public research can continue. Dataset access needs your review.";
}
export function demoStateLabel(state: DemoState) {
  return {
    starting: "Starting",
    waiting: "Waiting for access",
    running: "Working",
    completed: "Brief ready",
    denied: "Access denied",
    expired: "Time limit reached",
    interrupted: "Worker stopped",
    failed: "Needs attention",
  }[state];
}
