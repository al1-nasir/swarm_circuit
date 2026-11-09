"use client";
import Link from "next/link";
import {
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  ChevronRight,
  Layers,
  Radio,
  RefreshCw,
  Search,
  ShieldCheck,
  Workflow,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { mergeById, mergePage, short, time } from "@/lib/model";
import type { Page, Run } from "@/lib/types";
import { useProject } from "./shell";
import { Empty, Status } from "./ui";
import { Asset } from "./asset";
import { WorkspaceOverview } from "./workspace-overview";

export function Runs({ kind = "runs" }: { kind?: string }) {
  return kind === "overview" ? <WorkspaceOverview /> : <RunList kind={kind} />;
}

function RunList({ kind }: { kind: string }) {
  const {
    config,
    health,
    error: connectionError,
    refresh: check,
  } = useProject();
  const [page, setPage] = useState<Page<Run>>({ items: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [mode, setMode] = useState("all");
  const [includeDiagnostics, setIncludeDiagnostics] = useState(false);
  const requestScope = `${config?.projectId}:${includeDiagnostics}`;
  const activeScope = useRef(requestScope);
  activeScope.current = requestScope;
  const [updated, setUpdated] = useState(0);
  const refresh = useCallback(
    async (cursor?: string) => {
      if (!config) return;
      const scope = `${config.projectId}:${includeDiagnostics}`;
      setLoading(true);
      try {
        const data = await api<Page<Run>>(
          `projects/${config.projectId}/runs?kind=workflow&include_diagnostics=${includeDiagnostics}&limit=30${cursor ? "&cursor=" + encodeURIComponent(cursor) : ""}`,
        );
        if (scope !== activeScope.current) return;
        setPage((old) =>
          cursor
            ? {
                items: mergeById(old.items, data.items, (i) => i.run_id),
                next_cursor: data.next_cursor,
              }
            : mergePage(old, data, (i) => i.run_id),
        );
        setError("");
        setUpdated(Date.now());
      } catch (e) {
        if (scope === activeScope.current)
          setError(e instanceof Error ? e.message : "Run list unavailable.");
      } finally {
        if (scope === activeScope.current) setLoading(false);
      }
    },
    [config, includeDiagnostics],
  );
  useEffect(() => {
    if (!config) return;
    setPage({ items: [] });
    void refresh();
    const interval = setInterval(() => void refresh(), 15000);
    return () => clearInterval(interval);
  }, [config, refresh]);
  const items = page.items.filter(
    (r) =>
      (r.name + " " + r.run_id).toLowerCase().includes(query.toLowerCase()) &&
      (status === "all" || r.status === status) &&
      (mode === "all" || r.mode === mode),
  );
  const running = page.items.filter((r) => r.status === "running").length;
  const waiting = page.items.filter((r) => r.status === "waiting").length;
  const incidents = page.items.reduce((n, r) => n + r.open_incident_count, 0);
  const title =
    kind === "incidents"
      ? "Incident evidence"
      : kind === "payments"
        ? "Payment & approval evidence"
        : "Workflows";
  return (
    <div className="page-content">
      <div className="page-heading">
        <div>
          <div className="eyebrow">
            {kind === "runs" ? "WORKFLOW OPERATIONS" : "WORKFLOW EVIDENCE"}
          </div>
          <h1>{title}</h1>
          <p>
            {kind === "incidents"
              ? "Open a workflow to see findings, affected tasks and supporting evidence."
              : kind === "payments"
                ? "Choose a workflow to inspect gate decisions and settlement provenance."
                : "Open a workflow to understand its progress, shared waits and current worker connections."}
          </p>
        </div>
        <Link className="button primary" href="/setup">
          <Workflow size={16} />
          Connect your workflow
          <ArrowUpRight size={14} />
        </Link>
      </div>
      <section className="summary-grid" aria-label="Loaded workflow summary">
        <div className="summary-card">
          <span className="summary-icon teal">
            <Workflow size={19} />
          </span>
          <div>
            <span>Recorded workflows</span>
            <strong>
              {page.items.length}
              <small>in loaded page</small>
            </strong>
          </div>
        </div>
        <div className="summary-card">
          <span className="summary-icon blue">
            <Radio size={19} />
          </span>
          <div>
            <span>Recorded running / waiting</span>
            <strong>
              {running}
              <em>/</em>
              {waiting}
              <small>saved status, not live workers</small>
            </strong>
          </div>
        </div>
        <div className="summary-card">
          <span className="summary-icon amber">
            <Layers size={19} />
          </span>
          <div>
            <span>Open incidents</span>
            <strong>
              {incidents}
              <small>in loaded runs</small>
            </strong>
          </div>
        </div>
      </section>
      <div className="section-heading">
        <h2>
          Recorded workflows
          <span className="count">{items.length}</span>
        </h2>
        <span className="muted metadata">
          {updated ? `Snapshot ${time(updated)} UTC` : "Connecting to backend"}
        </span>
      </div>
      <section className="panel runs-panel">
        <div className="table-toolbar">
          <label className="search-box">
            <Search size={16} />
            <input
              aria-label="Search loaded workflows"
              placeholder="Search loaded workflows…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <div className="filters">
            <label className="diagnostic-toggle">
              <input
                type="checkbox"
                checked={includeDiagnostics}
                onChange={(e) => setIncludeDiagnostics(e.target.checked)}
              />
              Include diagnostic checks
            </label>
            <label className="select-label">
              <select
                aria-label="Filter workflow state"
                value={status}
                onChange={(e) => setStatus(e.target.value)}
              >
                <option value="all">All states</option>
                {["running", "waiting", "completed", "failed"].map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>
            <select
              aria-label="Filter mode"
              value={mode}
              onChange={(e) => setMode(e.target.value)}
            >
              <option value="all">All modes</option>
              <option value="observe">Observe</option>
              <option value="control">Control</option>
            </select>
            <button
              className="icon-button"
              aria-label="Refresh workflows"
              onClick={() => {
                check();
                void refresh();
              }}
            >
              <RefreshCw size={16} className={loading ? "spinning" : ""} />
            </button>
          </div>
        </div>
        {(error || connectionError) && (
          <div className="banner danger" role="status">
            {error || connectionError}{" "}
            {page.items.length > 0 && "Last successful snapshot is retained."}
            <button
              onClick={() => {
                check();
                void refresh();
              }}
            >
              Retry
            </button>
          </div>
        )}
        {loading && !page.items.length && !error ? (
          <div className="loading-state">Loading recorded workflows…</div>
        ) : items.length === 0 ? (
          <Empty
            title={
              query || status !== "all" || mode !== "all"
                ? "No matching loaded workflows"
                : includeDiagnostics
                  ? "No workflows recorded yet"
                  : "No regular workflows recorded yet"
            }
          >
            <p>
              Start the guided demo or connect your own workflow. Diagnostic
              checks can be included using the filter above.
            </p>
            <Link href="/setup" className="text-link">
              View SDK setup <ArrowRight size={14} />
            </Link>
          </Empty>
        ) : (
          <div className="table-scroll">
            <table className="runs-table">
              <thead>
                <tr>
                  <th>
                    Workflow <ArrowDown size={11} />
                  </th>
                  <th>Recorded state</th>
                  <th>Mode</th>
                  <th>Agents</th>
                  <th>Incidents</th>
                  <th>Recorded</th>
                  <th aria-label="Open" />
                </tr>
              </thead>
              <tbody>
                {items.map((run) => (
                  <tr key={run.run_id}>
                    <td>
                      <Link
                        className="workflow-name"
                        href={`/runs/${run.run_id}${kind === "incidents" ? "?tab=incidents" : kind === "payments" ? "?tab=payments" : ""}`}
                      >
                        <span
                          className={`run-icon ${run.mode === "control" ? "control-icon" : ""}`}
                        >
                          <Asset name="flow-arrow" />
                        </span>
                        <span>
                          <strong>{run.name}</strong>
                          <small className="mono">
                            {short(run.run_id)}
                            <span className="metadata-divider">·</span>
                            {run.metadata.simulation
                              ? "Simulated data & tools"
                              : "Host-observed workflow"}
                          </small>
                        </span>
                      </Link>
                    </td>
                    <td>
                      <Status value={run.status} />
                    </td>
                    <td>
                      <span className={`mode ${run.mode}`}>
                        <span className="tiny-dot" />
                        {run.mode === "control" ? "Control" : "Observe"}
                      </span>
                    </td>
                    <td className="mono">{run.agent_count ?? "—"}</td>
                    <td>
                      {run.open_incident_count ? (
                        <span className="incident-count">
                          {run.open_incident_count} open
                        </span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td>
                      <span className="date-cell">
                        {time(run.created_at_ms)}
                        <small>
                          {new Date(run.created_at_ms).toLocaleDateString(
                            "en-GB",
                            { timeZone: "UTC", day: "2-digit", month: "short" },
                          )}{" "}
                          · UTC
                        </small>
                      </span>
                    </td>
                    <td>
                      <Link
                        className="icon-button"
                        href={`/runs/${run.run_id}`}
                        aria-label={`Open ${run.name}`}
                      >
                        <ChevronRight size={17} />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="table-footer">
          <span>
            {page.items.length} loaded · search and counts cover loaded runs
            {!includeDiagnostics && " · diagnostic checks hidden"}
          </span>
          {page.next_cursor ? (
            <button
              className="button small"
              disabled={loading}
              onClick={() => void refresh(page.next_cursor!)}
            >
              Load older workflows
            </button>
          ) : (
            <span className="muted">End of recorded runs</span>
          )}
        </div>
      </section>
      <div className="principle-strip">
        <ShieldCheck size={18} />
        <div>
          <strong>Visibility comes first.</strong>
          <span>
            Observe runs show evidence. Control requires an explicitly
            integrated runtime.
          </span>
        </div>
        <Link href="/settings/integrations">
          Integration details <ArrowUpRight size={14} />
        </Link>
      </div>
    </div>
  );
}
