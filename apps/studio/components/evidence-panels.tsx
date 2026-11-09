"use client";
import { useState } from "react";
import {
  ArrowDown,
  ArrowRight,
  Clock3,
  FileSearch,
  Fingerprint,
  Pause,
  Play,
  ShieldCheck,
  Wallet,
} from "lucide-react";
import { commandLabel, confirmed, short, time, words } from "@/lib/model";
import type { Approval, Command, Incident, Payment } from "@/lib/types";
import { CopyButton, Empty, Status, Trust } from "./ui";

export function Incidents({
  items,
  selected,
  onSelect,
}: {
  items: Incident[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <section className="panel evidence-panel">
      <div className="panel-title">
        <h2>
          Incident evidence <span className="count">{items.length}</span>
        </h2>
        <span className="muted metadata">
          Findings explain observations; they do not change task state
        </span>
      </div>
      {!items.length ? (
        <Empty title="No problems detected">
          <p>A pending human approval alone is expected safety behavior.</p>
        </Empty>
      ) : (
        <div className="incident-list">
          {items.map((item) => (
            <button
              key={item.incident_id}
              className={`incident-row ${selected === item.incident_id ? "selected" : ""}`}
              onClick={() => onSelect(item.incident_id)}
            >
              <span className={`incident-marker severity-${item.severity}`}>
                <FileSearch size={18} />
              </span>
              <div>
                <div className="row-title">
                  <strong>{item.title}</strong>
                  <Status value={item.state} />
                </div>
                <p>
                  {item.affected_task_ids.length} affected tasks ·{" "}
                  {item.current_evidence_event_ids.length} current evidence
                  references · {words(item.kind)}
                </p>
                <small>
                  <Trust value="derived" />
                  <span>{time(item.updated_at_ms)} UTC</span>
                  <span className="mono">{short(item.incident_id)}</span>
                </small>
              </div>
              <ArrowRight size={17} />
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

export function Payments({
  section = "payments",
  payments,
  approvals,
  onTask,
  onEvidence,
  onOlderPayments,
  onOlderApprovals,
  morePayments,
  moreApprovals,
}: {
  section?: "payments" | "approvals";
  payments: Payment[];
  approvals: Approval[];
  onTask: (id: string) => void;
  onEvidence: (id: string) => void;
  onOlderPayments: () => void;
  onOlderApprovals: () => void;
  morePayments: boolean;
  moreApprovals: boolean;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const payment = payments.find((p) => p.payment_intent_id === selected);
  if (section === "approvals")
    return (
      <section className="panel evidence-panel">
        <div className="panel-title">
          <h2>
            Approval requests <span className="count">{approvals.length}</span>
          </h2>
          <span className="muted metadata">
            Permission decisions · read only
          </span>
        </div>
        {!approvals.length ? (
          <Empty title="No approval requests recorded">
            <p>Permission waits appear when the workflow records them.</p>
          </Empty>
        ) : (
          approvals.map((approval) => (
            <article className="approval-card" key={approval.approval_id}>
              <div className="row-title">
                <strong className="mono">
                  Approval {short(approval.approval_id)}
                  <CopyButton value={approval.approval_id} />
                </strong>
                <Status value={approval.state} />
              </div>
              <p>
                {approval.request_count} recorded request
                {approval.request_count === 1 ? "" : "s"} ·{" "}
                {approval.simulation ? "Simulation workflow" : "Host workflow"}
              </p>
              <details className="scope-disclosure">
                <summary>Inspect approval scope</summary>
                <code>{approval.action_fingerprint}</code>
              </details>
              {approval.verified_resolution_source ? (
                <div className="receipt-line">
                  <Trust value={approval.resolution_trust} />
                  <span>
                    {approval.verified_resolution_source} ·{" "}
                    {approval.resolution_actor}
                  </span>
                  {approval.resolution_event_id && (
                    <button
                      className="text-link"
                      onClick={() => onEvidence(approval.resolution_event_id!)}
                    >
                      Resolution evidence <ArrowRight size={12} />
                    </button>
                  )}
                </div>
              ) : (
                <p className="muted">
                  Waiting for a decision from the permission service. No
                  confirmed decision has been recorded.
                </p>
              )}
              {approval.related_task_id && (
                <button
                  className="text-link"
                  onClick={() => onTask(approval.related_task_id!)}
                >
                  View related task <ArrowRight size={12} />
                </button>
              )}
            </article>
          ))
        )}
        <div className="table-footer">
          <span>Request evidence does not grant authorization.</span>
          {moreApprovals && (
            <button className="button small" onClick={onOlderApprovals}>
              Load older approvals
            </button>
          )}
        </div>
      </section>
    );
  return (
    <section className="panel evidence-panel">
      <div className="panel-title">
        <h2>
          Payment evidence <span className="count">{payments.length}</span>
        </h2>
        <span className="muted metadata">
          Exact amounts · no payment actions
        </span>
      </div>
      {!payments.length ? (
        <Empty title="No payment observations">
          <p>
            GateKeep402 evidence appears when the host integrates the optional
            observer.
          </p>
        </Empty>
      ) : (
        <div className="table-scroll">
          <table className="payment-table">
            <thead>
              <tr>
                <th>Destination</th>
                <th>Amount</th>
                <th>Outcome</th>
                <th>Provenance</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {payments.map((p) => (
                <tr
                  key={p.payment_intent_id}
                  className={selected === p.payment_intent_id ? "selected" : ""}
                  onClick={() => setSelected(p.payment_intent_id)}
                >
                  <td>
                    <strong>{p.domain}</strong>
                    <small className="mono">
                      {short(p.payment_intent_id)} · {p.chain_network}
                    </small>
                  </td>
                  <td className="mono">
                    {p.amount_decimal} {p.asset_code}
                  </td>
                  <td>
                    <Status value={p.state}>
                      {p.state === "settled" && p.simulation
                        ? "Settled · simulated"
                        : words(p.state)}
                    </Status>
                    {p.control_blocked && (
                      <small>Release blocked by evidence guard</small>
                    )}
                  </td>
                  <td>
                    <Trust value={p.state_evidence} />
                    <small>
                      {p.simulation ? "Simulation workflow" : "Host workflow"}
                    </small>
                  </td>
                  <td>
                    <button
                      className="text-link"
                      aria-label={`Inspect payment ${p.domain}`}
                      onClick={() => setSelected(p.payment_intent_id)}
                    >
                      Inspect <ArrowRight size={12} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {payment && (
        <div className="payment-detail">
          <div className="row-title">
            <h3>{payment.domain}</h3>
            <button className="button small" onClick={() => setSelected(null)}>
              Close details
            </button>
          </div>
          <div className="payment-badges">
            <Status value={payment.state} />
            <Trust value={payment.state_evidence} />
            {payment.simulation && (
              <span className="simulation-label">SIMULATION</span>
            )}
          </div>
          <div className="payment-detail-grid">
            <div>
              <h3>Gate decisions</h3>
              <div className="gate-decisions">
                {payment.gate_decisions.map((gate) => (
                  <button
                    className={`gate-decision gate-${gate.decision}`}
                    key={gate.gate_decision_id}
                    onClick={() => onEvidence(gate.evidence_event_id)}
                  >
                    {gate.decision.toUpperCase()} <ArrowRight size={12} />
                  </button>
                ))}
              </div>
              {payment.gate_decision_count > payment.gate_decisions.length && (
                <p className="muted metadata">
                  {payment.gate_decision_count} total;{" "}
                  {payment.has_deny
                    ? "DENY remains blocking"
                    : "recent 100 shown"}
                  .
                </p>
              )}
              <button
                className="text-link"
                onClick={() => onTask(payment.task_id)}
              >
                Inspect owning task <ArrowRight size={12} />
              </button>
            </div>
            <div>
              <h3>Attempts & receipts</h3>
              {!payment.attempts.length && (
                <p className="muted metadata">No attempt recorded.</p>
              )}
              {payment.attempts.map((attempt) => (
                <div className="receipt-line" key={attempt.payment_attempt_id}>
                  <span className="mono">
                    Attempt {short(attempt.payment_attempt_id)}
                  </span>
                  <Status value={attempt.phase} />
                  <span>Receipt: {words(attempt.receipt_trust)}</span>
                  {attempt.delivery_checks.map((check) => (
                    <button
                      key={check.evidence_event_id}
                      className="text-link"
                      onClick={() => onEvidence(check.evidence_event_id)}
                    >
                      {check.structural_ok
                        ? "Structural check passed"
                        : "Structural check failed"}{" "}
                      <ArrowRight size={12} />
                    </button>
                  ))}
                </div>
              ))}
            </div>
          </div>
          <div className="payment-footer">
            <span>
              {payment.state === "unknown"
                ? "Settlement unconfirmed. Reconcile externally before another effect."
                : "Delivery checks do not establish content truth or chain finality."}
            </span>
          </div>
        </div>
      )}
      <div className="table-footer">
        <span>
          Read-only evidence. Studio cannot authorize, approve or retry
          payments.
        </span>
        {morePayments && (
          <button className="button small" onClick={onOlderPayments}>
            Load older payments
          </button>
        )}
      </div>
    </section>
  );
}

export function Commands({
  items,
  onTask,
  more,
  onOlder,
}: {
  items: Command[];
  onTask: (id: string) => void;
  more: boolean;
  onOlder: () => void;
}) {
  const sorted = [...items].sort(
    (a, b) =>
      b.created_at_ms - a.created_at_ms ||
      b.command_id.localeCompare(a.command_id),
  );
  return (
    <section className="panel evidence-panel">
      <div className="panel-title">
        <h2>
          Control history <span className="count">{items.length}</span>
        </h2>
        <span className="muted metadata">
          Saved requests and worker confirmations
        </span>
      </div>
      {!items.length ? (
        <Empty title="No control commands recorded">
          <p>
            Pause and resume requests appear here with the result reported by
            their worker.
          </p>
        </Empty>
      ) : (
        sorted.map((command) => (
          <article
            className={`command-card command-${command.state}`}
            key={command.command_id}
          >
            <div className="row-title">
              <strong>
                {command.command_kind === "hold_task" ? (
                  <Pause size={15} />
                ) : (
                  <Play size={15} />
                )}
                {command.command_kind === "hold_task"
                  ? "Pause requested"
                  : "Resume requested"}
              </strong>
              <Status
                value={
                  command.state === "applied" && !confirmed(command)
                    ? "unknown"
                    : command.state
                }
              >
                {commandLabel(command)}
              </Status>
            </div>
            <div className="command-identifier mono">
              {command.command_id}
              <CopyButton value={command.command_id} />
            </div>
            <p>{command.request_reason}</p>
            <div className="command-lifecycle">
              <span>
                <i className="step done" />
                Request saved<small>{time(command.created_at_ms)}</small>
              </span>
              <span>
                <i
                  className={`step ${command.dispatched_at_ms ? "done" : ""}`}
                />
                Sent to worker<small>{time(command.dispatched_at_ms)}</small>
              </span>
              <span>
                <i
                  className={`step ${confirmed(command) ? "confirmed" : ""}`}
                />
                {confirmed(command) ? "Worker confirmation" : "Outcome"}
                <small>{time(command.completed_at_ms)}</small>
              </span>
            </div>
            {command.state === "unknown" && (
              <div className="banner warning">
                Outcome unknown. Reconcile runtime state; no automatic
                replacement request.
              </div>
            )}
            <div className="payment-footer">
              <button
                className="text-link"
                onClick={() => onTask(command.task_id)}
              >
                Task {short(command.task_id)}
                <ArrowRight size={13} />
              </button>
              <details>
                <summary>Technical evidence</summary>
                <span className="mono">
                  Epoch {command.session_fencing_epoch} · task v
                  {command.expected_task_version} ·{" "}
                  {command.acknowledgements.length} recorded worker responses
                </span>
              </details>
            </div>
          </article>
        ))
      )}
      {more && (
        <div className="table-footer">
          <button className="button small" onClick={onOlder}>
            Load older commands
          </button>
        </div>
      )}
    </section>
  );
}
