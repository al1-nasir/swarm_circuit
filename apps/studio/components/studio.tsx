"use client";
import { WorkflowSummary } from "./workflow-summary";
import { Containment } from "./containment";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  Bell,
  ChevronRight,
  Clock3,
  Command as CommandIcon,
  FileClock,
  GitBranch,
  Info,
  Network,
  PanelRight,
  Radio,
  RefreshCw,
  ShieldCheck,
  Wallet,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { commandLabel, short, time, words } from "@/lib/model";
import type { Command, Evidence, GraphNode, Intent } from "@/lib/types";
import { useRun } from "@/lib/use-run";
import { useProject } from "./shell";
import { CopyButton, Empty, Status } from "./ui";
import { ControlDialog, type Draft } from "./control-dialog";
import { Commands, Incidents, Payments } from "./evidence-panels";
import { Inspector } from "./inspector";
import { Timeline } from "./timeline";

const GraphView = dynamic(() => import("./graph"), {
  ssr: false,
  loading: () => (
    <div className="panel loading-state graph-placeholder">
      Preparing workflow graph…
    </div>
  ),
});
const tabs = [
  { id: "graph", label: "Workflow map", Icon: Network },
  { id: "timeline", label: "Timeline", Icon: FileClock },
  { id: "incidents", label: "Findings", Icon: Activity },
  { id: "approvals", label: "Approvals", Icon: ShieldCheck },
  { id: "payments", label: "Payments", Icon: Wallet },
  { id: "commands", label: "Pause history", Icon: CommandIcon },
];
const reasonLabels: Record<string, string> = {
  observe_only:
    "This workflow is monitored, not controlled. Add explicit SDK checkpoints.",
  stale_session:
    "Runtime disconnected or expired. A historical ACK does not establish current control.",
  not_found: "No active owned reversible checkpoint for this task.",
  no_active_boundary: "No active owned reversible checkpoint for this task.",
  approval_unresolved:
    "An external approval is pending, denied, or unverified.",
  payment_boundary:
    "Payment authorization or settlement needs external reconciliation.",
  unresolved_dependency: "Declared prerequisites have not completed.",
  pending_or_uncertain_command:
    "A pending or uncertain command already targets this task.",
};

export function Studio({ runId }: { runId: string }) {
  const router = useRouter();
  const params = useSearchParams();
  const { config, health, rememberRun } = useProject();
  const { data, error, updated, live, refreshing, refresh, older } =
    useRun(runId);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [notice, setNotice] = useState("");
  const [intents, setIntents] = useState<Intent[]>([]);
  const [extraEvidence, setExtraEvidence] = useState<Evidence | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  useEffect(() => {
    const selected = ["task", "event", "incident", "edge"].some((key) =>
      params.has(key),
    );
    setInspectorOpen(selected);
  }, [runId]);
  const tab = tabs.some((t) => t.id === params.get("tab"))
    ? params.get("tab")!
    : "graph";
  const view = params.get("view") === "agent" ? "agent" : "task";
  const taskId = params.get("task");
  const incidentId = params.get("incident");
  const evidenceId = params.get("event");
  const edgeId = params.get("edge");
  const node =
    data?.taskGraph.nodes.find((n) => n.id === taskId) ||
    data?.agentGraph.nodes.find((n) => n.id === taskId);
  const incident = data?.incidents.find((i) => i.incident_id === incidentId);
  const graph = data
    ? view === "agent"
      ? data.agentGraph
      : data.taskGraph
    : null;
  const edge = graph?.edges.find((e) => e.id === edgeId);
  const timelineEvidence = data?.timeline.items.find(
    (e) => e.id === evidenceId,
  );
  const evidence =
    timelineEvidence ||
    (extraEvidence?.id === evidenceId ? extraEvidence : undefined);
  function update(values: Record<string, string | null>) {
    const next = new URLSearchParams(params.toString());
    for (const [key, value] of Object.entries(values)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    router.replace(`/runs/${runId}${next.size ? "?" + next : ""}`, {
      scroll: false,
    });
  }
  function selectTask(id: string) {
    setInspectorOpen(true);
    const agent = data?.agentGraph.nodes.some((n) => n.id === id);
    update({
      task: id,
      event: null,
      incident: null,
      edge: null,
      tab: "graph",
      view: agent ? "agent" : "task",
    });
  }
  function selectEvidence(id: string) {
    setInspectorOpen(true);
    update({ event: id, edge: null });
  }
  useEffect(() => {
    setExtraEvidence(null);
    setEvidenceLoading(false);
    if (!evidenceId || timelineEvidence) return;
    let stopped = false;
    setEvidenceLoading(true);
    api<Evidence>(`runs/${runId}/evidence/${evidenceId}`)
      .then((item) => {
        if (!stopped) setExtraEvidence(item);
      })
      .catch(() => {
        if (!stopped)
          setNotice(
            "Source evidence is unavailable in this run. Refresh the snapshot.",
          );
      })
      .finally(() => {
        if (!stopped) setEvidenceLoading(false);
      });
    return () => {
      stopped = true;
    };
  }, [runId, evidenceId, Boolean(timelineEvidence)]);
  useEffect(() => {
    if (data) rememberRun(data.run);
  }, [rememberRun, data?.run.run_id, data?.run.name]);
  const storageKey = `swarmcircuit:requests:${runId}`;
  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || "[]");
      setIntents(
        Array.isArray(saved)
          ? saved
              .filter(
                (i) =>
                  i.runId === runId &&
                  typeof i.key === "string" &&
                  typeof i.taskId === "string",
              )
              .slice(0, 50)
          : [],
      );
    } catch {
      setIntents([]);
    }
  }, [storageKey, runId]);
  function saveIntents(next: Intent[]) {
    setIntents(next);
    try {
      localStorage.setItem(storageKey, JSON.stringify(next));
    } catch {
      setNotice(
        "Request metadata is retained in this tab only. Keep the command ID for reconciliation.",
      );
    }
  }
  useEffect(() => {
    if (!data || !intents.length) return;
    const unresolved = intents.filter(
      (i) => !data.commands.items.some((c) => c.idempotency_key === i.key),
    );
    if (unresolved.length !== intents.length) {
      const reconciled = data.commands.items.find((c) =>
        intents.some((i) => i.key === c.idempotency_key),
      );
      if (reconciled)
        setNotice(`${commandLabel(reconciled)} · ${reconciled.command_id}`);
      saveIntents(unresolved);
    }
  }, [data?.commands.items, intents]);
  useEffect(() => {
    if (!data || !notice) return;
    const command = data.commands.items.find((c) =>
      notice.endsWith(c.command_id),
    );
    if (command) {
      const current = `${commandLabel(command)} · ${command.command_id}`;
      if (current !== notice) setNotice(current);
    }
  }, [data?.commands.items, notice]);
  const globalBlocked = !config?.operator
    ? "Operator control is unavailable in this Studio session."
    : health !== "ready"
      ? "Backend is not ready. Refresh connection diagnostics."
      : !live
        ? "Live updates paused. Reconnect and resync before a new control request."
        : error
          ? "Snapshot refresh failed. Reconcile current state first."
          : !updated || Date.now() - updated > 15000
            ? "Snapshot is stale. Refresh before requesting control."
            : "";
  const pending = node ? intents.some((i) => i.taskId === node.id) : false;
  const controlReason =
    globalBlocked ||
    (pending
      ? "Submission outcome unknown. Reconcile command history before another request."
      : data?.run.mode !== "control"
        ? reasonLabels.observe_only
        : node && !node.control?.hold_task && !node.control?.resume_task
          ? reasonLabels[node.control?.reason || "no_active_boundary"] ||
            words(node.control?.reason || "No active checkpoint")
          : "");
  const lastCommand = node
    ? [...(data?.commands.items || [])]
        .filter((c) => c.task_id === node.id)
        .sort((a, b) => b.created_at_ms - a.created_at_ms)[0]
    : undefined;
  useEffect(() => {
    if (draft && globalBlocked) {
      setDraft(null);
      setNotice(
        "Connection or permission changed. Reconcile before opening another review.",
      );
    }
  }, [globalBlocked, draft]);
  async function submit(reason: string) {
    if (!draft) return;
    const key = crypto.randomUUID();
    const intent: Intent = {
      key,
      runId,
      taskId: draft.node.id,
      kind: draft.kind,
      createdAt: Date.now(),
    };
    saveIntents([...intents, intent]);
    const body = {
      command_kind: draft.kind,
      task_id: draft.node.id,
      runtime_session_id: draft.node.control?.runtime_session_id,
      expected_task_version: draft.node.state_version,
      reason,
    };
    try {
      const command = await api<Command>(`runs/${runId}/control-commands`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": key },
        body: JSON.stringify(body),
      });
      setNotice(`${commandLabel(command)} · ${command.command_id}`);
    } catch (e) {
      if (e instanceof ApiError && e.status < 500 && e.status !== 429) {
        saveIntents(intents);
        setNotice(
          e.status === 409
            ? "Task changed since review. No new command was accepted; refresh and review current state."
            : e.message,
        );
      } else
        setNotice(
          `Submission outcome unknown. Reconcile request ${short(key)} in control history; do not submit a replacement.`,
        );
    } finally {
      setDraft(null);
      void refresh();
    }
  }
  if (!data)
    return (
      <div className="page-content">
        <Link className="text-link" href="/runs">
          <ArrowLeft size={15} />
          Back to workflows
        </Link>
        {error ? (
          <Empty title="Workflow snapshot unavailable">
            <p>{error}</p>
            <button className="button primary" onClick={() => void refresh()}>
              Retry snapshot
            </button>
          </Empty>
        ) : (
          <div className="studio-skeleton">
            <div />
            <div />
            <div />
          </div>
        )}
      </div>
    );
  const connected = data.runtimes.filter((r) => r.state === "connected").length;
  return (
    <div className="studio-page">
      <div className="studio-breadcrumb">
        <Link href="/runs">Workflows</Link>
        <ChevronRight size={12} />
        <span className="mono">{short(runId)}</span>
        <CopyButton value={runId} />
        <span className="snapshot-stamp">Snapshot {time(updated)} UTC</span>
      </div>
      <div className="studio-heading">
        <div>
          <h1>{data.run.name}</h1>
          <div className="run-subline">
            <Status value={data.run.status} />
            <span className={`mode ${data.run.mode}`}>
              <span className="tiny-dot" />
              {data.run.mode === "control" ? "Control mode" : "Observe mode"}
            </span>
            {data.run.metadata.simulation && (
              <span className="simulation-label">SIMULATED DATA & TOOLS</span>
            )}
          </div>
        </div>
        <div className="heading-actions">
          <details className="run-details">
            <summary className="button secondary">Run details</summary>
            <div className="run-details-body">
              <h3>Run context</h3>
              <dl>
                <div className="key-value">
                  <dt>Tasks / agents</dt>
                  <dd>
                    {data.taskGraph.nodes.length} /{" "}
                    {data.agentGraph.nodes.length}
                  </dd>
                </div>
                <div className="key-value">
                  <dt>Open findings</dt>
                  <dd>
                    {
                      data.incidents.filter(
                        (i) => i.state === "open" || i.state === "acknowledged",
                      ).length
                    }
                  </dd>
                </div>
                <div className="key-value">
                  <dt>Pending approvals</dt>
                  <dd>
                    {
                      data.approvals.items.filter((a) => a.state === "pending")
                        .length
                    }
                  </dd>
                </div>
                <div className="key-value">
                  <dt>Live runtimes</dt>
                  <dd>{connected || "None registered"}</dd>
                </div>
                <div className="key-value">
                  <dt>Snapshot</dt>
                  <dd>{time(updated)} UTC</dd>
                </div>
              </dl>
            </div>
          </details>
          <button className="button secondary" onClick={() => void refresh()}>
            <RefreshCw size={14} className={refreshing ? "spinning" : ""} />
            Refresh
          </button>
          <button
            className="icon-button"
            aria-label={inspectorOpen ? "Hide inspector" : "Show inspector"}
            onClick={() => setInspectorOpen((v) => !v)}
          >
            <PanelRight size={18} />
          </button>
        </div>
      </div>
      {(!live || error) && (
        <div className="banner warning" role="status">
          <Radio size={16} />
          <span>
            {error ||
              "Live updates paused. Last successful data is retained; controls are disabled until snapshot resync."}
          </span>
          <button onClick={() => void refresh()}>Refresh snapshot</button>
        </div>
      )}
      {notice && (
        <div className="banner info" role="status">
          <Info size={16} />
          <span>{notice}</span>
          <button
            className="icon-button"
            aria-label="Dismiss notification"
            onClick={() => setNotice("")}
          >
            <X size={15} />
          </button>
        </div>
      )}
      {intents.length > 0 && (
        <div className="banner warning" role="status">
          <Clock3 size={16} />
          <span>
            {intents.length} submission{intents.length > 1 ? "s" : ""} awaiting
            durable reconciliation. History is checked with the original request
            key.
          </span>
          <button
            onClick={() => {
              update({ tab: "commands" });
              void refresh();
            }}
          >
            View history
          </button>
        </div>
      )}
      <WorkflowSummary runId={runId} updated={updated} />
      <nav className="workspace-tabs" aria-label="Workflow views">
        {tabs.map(({ id, label }) => (
          <button
            key={id}
            className={tab === id ? "active" : ""}
            aria-current={tab === id ? "page" : undefined}
            onClick={() => update({ tab: id })}
          >
            {label}
            {id === "approvals" &&
              data.approvals.items.some((a) => a.state === "pending") && (
                <span className="tab-count">
                  {
                    data.approvals.items.filter((a) => a.state === "pending")
                      .length
                  }
                </span>
              )}
            {id === "incidents" &&
              data.incidents.some(
                (i) => i.state === "open" || i.state === "acknowledged",
              ) && (
                <span className="tab-count">
                  {
                    data.incidents.filter(
                      (i) => i.state === "open" || i.state === "acknowledged",
                    ).length
                  }
                </span>
              )}
          </button>
        ))}
      </nav>
      <div
        className={`studio-workspace ${inspectorOpen ? "with-inspector" : ""}`}
      >
        <div className="studio-primary">
          {tab === "graph" && graph && (
            <GraphView
              key={view}
              graph={graph}
              taskCount={data.taskGraph.nodes.length}
              agentCount={data.agentGraph.nodes.length}
              runtimes={data.runtimes}
              selected={taskId}
              onSelect={selectTask}
              onEdge={(id) => {
                setInspectorOpen(true);
                update({ edge: id, task: null, event: null, incident: null });
              }}
              view={view}
              setView={(view) => update({ view, task: null, edge: null })}
            />
          )}
          {tab === "timeline" && (
            <Timeline
              items={data.timeline.items}
              selected={evidenceId}
              onSelect={selectEvidence}
              hasOlder={Boolean(data.timeline.next_cursor)}
              onOlder={() => void older("timeline")}
            />
          )}
          {tab === "incidents" && (
            <Incidents
              items={data.incidents}
              selected={incidentId}
              onSelect={(id) => {
                setInspectorOpen(true);
                update({ incident: id, event: null, task: null, edge: null });
              }}
            />
          )}
          {tab === "approvals" && (
            <Containment key={runId} data={data} onRefresh={refresh} />
          )}
          {(tab === "payments" || tab === "approvals") && (
            <Payments
              section={tab === "approvals" ? "approvals" : "payments"}
              payments={data.payments.items}
              approvals={data.approvals.items}
              onTask={selectTask}
              onEvidence={selectEvidence}
              morePayments={Boolean(data.payments.next_cursor)}
              moreApprovals={Boolean(data.approvals.next_cursor)}
              onOlderPayments={() => void older("payments")}
              onOlderApprovals={() => void older("approvals")}
            />
          )}
          {tab === "commands" && (
            <>
              {data.taskGraph.nodes.some((task) => task.state === "held") && (
                <section
                  className="panel recovery-panel"
                  aria-label="Resume paused work"
                >
                  <h2>Resume paused work</h2>
                  <p>
                    Permission and operator pauses are separate. Review each
                    task below; prerequisites must finish before their dependent
                    tasks can resume. Each request still needs a worker
                    confirmation.
                  </p>
                  {data.taskGraph.nodes
                    .filter((task) => task.state === "held")
                    .map((task) => {
                      const blocked =
                        globalBlocked ||
                        (intents.some((intent) => intent.taskId === task.id)
                          ? "Recheck the earlier request before sending another."
                          : !task.control?.resume_task
                            ? reasonLabels[
                                task.control?.reason || "no_active_boundary"
                              ] ||
                              "This task is not ready to resume. Refresh its evidence."
                            : "");
                      return (
                        <div className="recovery-task" key={task.id}>
                          <div>
                            <strong>{task.label}</strong>
                            <p className="metadata muted">
                              {blocked ||
                                "Ready for a reviewed resume request."}
                            </p>
                          </div>
                          <button
                            className="button secondary"
                            disabled={Boolean(blocked)}
                            onClick={() => {
                              if (!blocked && task.control?.resume_task)
                                setDraft({
                                  kind: "resume_task",
                                  node: {
                                    ...task,
                                    control: { ...task.control },
                                  },
                                });
                            }}
                          >
                            Review resume
                          </button>
                        </div>
                      );
                    })}
                </section>
              )}
              <Commands
                items={data.commands.items}
                onTask={selectTask}
                more={Boolean(data.commands.next_cursor)}
                onOlder={() => void older("commands")}
              />
            </>
          )}
          <div className="workspace-caption">
            <span className={`live-indicator ${live ? "online" : "offline"}`}>
              {live ? "Live snapshot" : "Reconnecting"}
            </span>
            <span>
              {data.run.mode === "observe"
                ? "Observe mode · runtime controls require explicit SDK integration."
                : "Control is cooperative · queued requests remain unconfirmed until a matching runtime ACK."}
            </span>
            <span className="mono">
              projection {data.taskGraph.projection_version}
            </span>
          </div>
        </div>
        {inspectorOpen && (
          <Inspector
            data={data}
            node={node}
            incident={evidenceId ? undefined : incident}
            evidence={evidence}
            evidenceLoading={evidenceLoading}
            edge={edge}
            latestCommand={lastCommand}
            controlReason={controlReason}
            onClose={() => {
              setInspectorOpen(false);
              update({ task: null, incident: null, event: null, edge: null });
            }}
            onTask={selectTask}
            onEvidence={selectEvidence}
            onIncident={(id) => {
              setInspectorOpen(true);
              update({
                tab: "incidents",
                incident: id,
                event: null,
                task: null,
                edge: null,
              });
            }}
            onRequest={(kind) => {
              if (node && !controlReason)
                setDraft({
                  kind,
                  node: { ...node, control: { ...node.control! } },
                });
            }}
            onCommands={() => update({ tab: "commands" })}
          />
        )}
      </div>
      {draft && (
        <ControlDialog
          draft={draft}
          data={data}
          onClose={() => setDraft(null)}
          onSubmit={submit}
          blocked={globalBlocked}
        />
      )}
    </div>
  );
}
