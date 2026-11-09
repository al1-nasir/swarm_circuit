"use client";
import {
  ArrowLeft,
  ArrowRight,
  Clock3,
  FileSearch,
  Fingerprint,
  GitBranch,
  Info,
  Pause,
  Play,
  ShieldCheck,
  X,
} from "lucide-react";
import {
  closure,
  commandLabel,
  displayedState,
  duration,
  short,
  spanDuration,
  time,
  words,
} from "@/lib/model";
import type {
  Command,
  Evidence,
  GraphEdge,
  GraphNode,
  Incident,
  Snapshot,
} from "@/lib/types";
import { CopyButton, KeyValue, Status, Trust } from "./ui";

export function Inspector({
  data,
  node,
  incident,
  evidence,
  evidenceLoading,
  edge,
  latestCommand,
  controlReason,
  onClose,
  onTask,
  onEvidence,
  onIncident,
  onRequest,
  onCommands,
}: {
  data: Snapshot;
  node?: GraphNode;
  incident?: Incident;
  evidence?: Evidence;
  edge?: GraphEdge;
  evidenceLoading: boolean;
  latestCommand?: Command;
  controlReason: string;
  onClose: () => void;
  onTask: (id: string) => void;
  onEvidence: (id: string) => void;
  onIncident: (id: string) => void;
  onRequest: (kind: "hold_task" | "resume_task") => void;
  onCommands: () => void;
}) {
  const title = evidence
    ? "Evidence inspector"
    : incident
      ? "Incident inspector"
      : edge
        ? "Relationship inspector"
        : node
          ? `${node.node_kind === "agent" ? "Agent" : "Task"} inspector`
          : "Run context";
  const owner = node
    ? data.runtimes.find((runtime) =>
        runtime.checkpoints.some(
          (p) => p.task_id === node.id && p.state !== "released",
        ),
      )
    : null;
  const related = node ? closure(data.taskGraph, node.id) : new Set<string>();
  return (
    <aside className="panel inspector" aria-label={title}>
      <div className="inspector-header">
        <span>
          <FileSearch size={16} />
          {title}
        </span>
        <button
          className="icon-button"
          aria-label="Close inspector"
          onClick={onClose}
        >
          <X size={16} />
        </button>
      </div>
      <div className="inspector-scroll">
        {evidenceLoading ? (
          <div className="loading-state">Loading source evidence…</div>
        ) : evidence ? (
          <>
            <div className="inspector-section">
              <div className="eyebrow">
                {evidence.item_type === "span"
                  ? "TRACE SPAN"
                  : "PERSISTED SOURCE EVENT"}
              </div>
              <h2>{evidence.label}</h2>
              <Trust value={evidence.trust_class} />
              <div className="entity-id mono">
                {evidence.id}
                <CopyButton value={evidence.id} />
              </div>
            </div>
            <div className="inspector-section">
              <h3>Timing & correlation</h3>
              <dl>
                <KeyValue label="Source time">
                  {time(evidence.occurred_at_ms)} UTC
                </KeyValue>
                {evidence.ingested_at_ms && (
                  <KeyValue label="Ingested">
                    {time(evidence.ingested_at_ms)} UTC
                  </KeyValue>
                )}
                {spanDuration(evidence) !== null && (
                  <KeyValue label="Duration">
                    {duration(spanDuration(evidence)!)}
                  </KeyValue>
                )}
                {evidence.task_id && (
                  <KeyValue label="Task">
                    <button
                      className="text-link mono"
                      onClick={() => onTask(evidence.task_id!)}
                    >
                      {short(evidence.task_id)}
                      <ArrowRight size={12} />
                    </button>
                  </KeyValue>
                )}
                {evidence.trace_id && (
                  <KeyValue label="Trace ID">
                    <span className="mono break">{evidence.trace_id}</span>
                  </KeyValue>
                )}
              </dl>
              {evidence.start_unix_ns && (
                <p className="metadata mono break">
                  Start ns: {evidence.start_unix_ns}
                  <br />
                  End ns: {evidence.end_unix_ns || "Open"}
                </p>
              )}
            </div>
            <div className="inspector-section">
              <h3>Sanitized metadata</h3>
              <p className="muted metadata">
                Content is hidden by the privacy policy. Source metadata remains
                inspectable.
              </p>
              <pre className="json-view">
                {JSON.stringify(
                  evidence.payload || evidence.attributes || {},
                  null,
                  2,
                )}
              </pre>
            </div>
          </>
        ) : incident ? (
          <>
            <div className="inspector-section">
              <div className="eyebrow">DERIVED DIAGNOSIS</div>
              <h2>{incident.title}</h2>
              <div className="inline-badges">
                <Status value={incident.state} />
                <Status value={incident.severity} />
                <Trust value="derived" />
              </div>
              <p className="uncertainty">{incident.uncertainty}</p>
              <div className="entity-id mono">
                {short(incident.incident_id)}
                <CopyButton value={incident.incident_id} />
              </div>
            </div>
            <div className="inspector-section">
              <h3>Rule & observations</h3>
              <dl>
                <KeyValue label="Detector">
                  {incident.detector_version}
                </KeyValue>
                <KeyValue label="Updated">
                  {time(incident.updated_at_ms)} UTC
                </KeyValue>
              </dl>
              <pre className="json-view">
                {JSON.stringify(incident.metrics, null, 2)}
              </pre>
              {incident.resolution_reason && (
                <p className="muted">
                  Resolution: {words(incident.resolution_reason)}
                </p>
              )}
            </div>
            <div className="inspector-section">
              <h3>Affected tasks</h3>
              {incident.affected_task_ids.map((id) => (
                <button
                  className="inspector-link"
                  key={id}
                  onClick={() => onTask(id)}
                >
                  <GitBranch size={14} />
                  <span>
                    {data.taskGraph.nodes.find((n) => n.id === id)?.label ||
                      short(id)}
                  </span>
                  <ArrowRight size={13} />
                </button>
              ))}
            </div>
            <div className="inspector-section">
              <h3>
                Current source evidence{" "}
                <span className="count">
                  {incident.current_evidence_event_ids.length}
                </span>
              </h3>
              {incident.current_evidence_event_ids.slice(0, 30).map((id) => (
                <button
                  className="inspector-link mono"
                  key={id}
                  onClick={() => onEvidence(id)}
                >
                  <Fingerprint size={13} />
                  {short(id)}
                  <ArrowRight size={12} />
                </button>
              ))}
              <p className="metadata muted">
                {incident.evidence_event_ids.length} retained references ·
                source links preserve the run
              </p>
            </div>
          </>
        ) : edge ? (
          <>
            <div className="inspector-section">
              <div className="eyebrow">
                {edge.evidence_kind.toUpperCase()} RELATIONSHIP
              </div>
              <h2>{words(edge.relation_kind)}</h2>
              <p className="uncertainty">
                {edge.evidence_kind === "explicit"
                  ? "This relationship was explicitly declared by the SDK. Layout and span ancestry do not create dependencies."
                  : "This association is inferred. It cannot establish runtime control authority."}
              </p>
            </div>
            <div className="inspector-section">
              <h3>Endpoints</h3>
              {[edge.source, edge.target].map((id) => (
                <button
                  key={id}
                  className="inspector-link"
                  onClick={() => onTask(id)}
                >
                  {data.taskGraph.nodes.find((n) => n.id === id)?.label ||
                    short(id)}
                  <ArrowRight size={13} />
                </button>
              ))}
              {edge.evidence_event_id && (
                <button
                  className="text-link"
                  onClick={() => onEvidence(edge.evidence_event_id!)}
                >
                  Inspect source event
                  <ArrowRight size={13} />
                </button>
              )}
            </div>
          </>
        ) : node ? (
          <>
            <div className="inspector-section">
              <div className="eyebrow">
                EXPLICIT {node.node_kind.toUpperCase()}
              </div>
              <h2>{node.label}</h2>
              <div className="inline-badges">
                <Status value={displayedState(node, data.runtimes)} />
                <Trust value="sdk_observation" />
              </div>
              <div className="entity-id mono">
                {node.id}
                <CopyButton value={node.id} />
              </div>
            </div>
            <div className="inspector-section">
              <h3>Execution context</h3>
              <dl>
                <KeyValue label="Observed state">
                  {words(node.state || "registered agent")}
                </KeyValue>
                {node.state_version !== undefined && (
                  <KeyValue label="Task version">
                    <span className="mono">v{node.state_version}</span>
                  </KeyValue>
                )}
                <KeyValue label="Runtime">
                  {owner ? <Status value={owner.state} /> : "No active owner"}
                </KeyValue>
                {owner && (
                  <KeyValue label="Fencing epoch">
                    <span className="mono">{owner.fencing_epoch}</span>
                  </KeyValue>
                )}
                <KeyValue label="Checkpoint">
                  {owner?.checkpoints.find(
                    (p) => p.task_id === node.id && p.state !== "released",
                  )?.label || "Not available"}
                </KeyValue>
              </dl>
            </div>
            {node.node_kind === "task" && (
              <>
                <div className="inspector-section">
                  <h3>
                    Dependency context{" "}
                    <span className="count">
                      {Math.max(0, related.size - 1)}
                    </span>
                  </h3>
                  <p className="muted metadata">
                    Explicit downstream tasks. A pause request targets this task
                    only.
                  </p>
                  {[...related]
                    .filter((id) => id !== node.id)
                    .map((id) => (
                      <button
                        className="inspector-link"
                        key={id}
                        onClick={() => onTask(id)}
                      >
                        {data.taskGraph.nodes.find((n) => n.id === id)?.label ||
                          short(id)}
                        <ArrowRight size={13} />
                      </button>
                    ))}
                  {related.size === 1 && (
                    <p className="muted">No explicit downstream tasks.</p>
                  )}
                </div>
                {!!node.incident_ids?.length && (
                  <div className="inspector-section">
                    <h3>Linked findings</h3>
                    {node.incident_ids.map((id) => (
                      <button
                        className="inspector-link"
                        key={id}
                        onClick={() => onIncident(id)}
                      >
                        <FileSearch size={14} />
                        <span>
                          {data.incidents.find((i) => i.incident_id === id)
                            ?.title || short(id)}
                        </span>
                        <ArrowRight size={13} />
                      </button>
                    ))}
                  </div>
                )}
                <div className="inspector-section controls-section">
                  <div className="eyebrow">WORKER CONTROLS</div>
                  <button
                    className="button primary full"
                    disabled={
                      Boolean(controlReason) || !node.control?.hold_task
                    }
                    onClick={() => onRequest("hold_task")}
                  >
                    <Pause size={15} />
                    Review pause request
                  </button>
                  <button
                    className="button secondary full"
                    disabled={
                      Boolean(controlReason) || !node.control?.resume_task
                    }
                    onClick={() => onRequest("resume_task")}
                  >
                    <Play size={15} />
                    Review resume request
                  </button>
                  <p className="control-explanation">
                    <Info size={13} />
                    {controlReason ||
                      (!node.control?.hold_task && !node.control?.resume_task
                        ? words(
                            node.control?.reason ||
                              "No supported active checkpoint",
                          )
                        : "Takes effect only at this supported reversible checkpoint. A runtime ACK is required.")}
                  </p>
                  {latestCommand && (
                    <button
                      className={`command-summary command-${latestCommand.state}`}
                      onClick={onCommands}
                    >
                      <span>{commandLabel(latestCommand)}</span>
                      <span className="mono">
                        {short(latestCommand.command_id)}
                        <ArrowRight size={13} />
                      </span>
                    </button>
                  )}
                </div>
              </>
            )}
          </>
        ) : (
          <>
            <div className="inspector-section">
              <span className="context-icon">
                <ShieldCheck size={24} />
              </span>
              <h2>Evidence, then action.</h2>
              <p className="muted">
                Select a task, relationship, or finding to inspect its context
                and supported controls.
              </p>
            </div>
            <div className="inspector-section">
              <h3>Run summary</h3>
              <dl>
                <KeyValue label="Mode">
                  {data.run.mode === "control"
                    ? "Cooperative control"
                    : "Observe only"}
                </KeyValue>
                <KeyValue label="Tasks">{data.taskGraph.nodes.length}</KeyValue>
                <KeyValue label="Agents">
                  {data.agentGraph.nodes.length}
                </KeyValue>
                <KeyValue label="Dependencies">
                  {data.taskGraph.edges.length}
                </KeyValue>
                <KeyValue label="Pending approvals">
                  {
                    data.approvals.items.filter((a) => a.state === "pending")
                      .length
                  }
                </KeyValue>
              </dl>
            </div>
            <div className="inspector-section">
              <h3>Runtime connections</h3>
              {data.runtimes.length ? (
                data.runtimes.map((r) => (
                  <div className="runtime-row" key={r.runtime_session_id}>
                    <div>
                      <strong>{r.runtime_key}</strong>
                      <small className="mono">
                        Epoch {r.fencing_epoch} · {short(r.runtime_session_id)}
                      </small>
                    </div>
                    <Status value={r.state} />
                  </div>
                ))
              ) : (
                <p className="muted">
                  No SDK runtime registered. Trace ingestion alone does not
                  enable controls.
                </p>
              )}
            </div>
            <div className="inspector-note">
              <Info size={16} />
              <p>
                Only explicit dependencies are shown. No causal relationship is
                inferred from timing alone.
              </p>
            </div>
          </>
        )}
      </div>
    </aside>
  );
}
