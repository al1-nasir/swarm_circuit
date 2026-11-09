"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { time, words } from "@/lib/model";
import type { Run } from "@/lib/types";
import { useProject } from "./shell";
import "./workspace-overview.css";

type RunBrief = {
  run: Run;
  classification: "workflow" | "diagnostic" | "research";
  progress: {
    completed: number;
    total: number;
    waiting: number;
    held: number;
    failed: number;
  };
  connection: {
    state: "connected" | "offline" | "not_integrated";
    connected_workers: number;
    last_heartbeat_ms: number | null;
  };
  headline: string;
  explanation: string;
  next_action: { label: string; href: string };
  pending_approvals: number;
};
type Workspace = {
  project_id: string;
  as_of_ms: number;
  counts: {
    recorded_workflows: number;
    diagnostic_workflows: number;
    research_trials: number;
    completed_workflows: number;
    recorded_running: number;
    recorded_waiting: number;
    connected_workflows: number;
    connected_workers: number;
    needs_attention: number;
  };
  items: RunBrief[];
  attention: RunBrief[];
};

export function WorkspaceOverview() {
  const { config, health } = useProject();
  const [data, setData] = useState<Workspace | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (!config?.projectId) return;
    const controller = new AbortController();
    let generation = 0;
    async function load() {
      const request = ++generation;
      try {
        const result = await api<Workspace>(
          `projects/${config!.projectId}/workspace?limit=6`,
          { signal: controller.signal },
        );
        if (!controller.signal.aborted && request === generation) {
          setData(result);
          setError("");
        }
      } catch (e) {
        if (!controller.signal.aborted && request === generation)
          setError(e instanceof Error ? e.message : "Workspace unavailable.");
      } finally {
        if (!controller.signal.aborted && request === generation)
          setLoading(false);
      }
    }
    void load();
    const timer = setInterval(() => void load(), 15000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [config?.projectId, revision]);
  const count = (key: keyof Workspace["counts"]) =>
    data ? data.counts[key] : "—";
  const live = health === "ready";
  return (
    <div className="page-content workspace-overview">
      <section className="workspace-intro" aria-labelledby="workspace-title">
        <div>
          <div className="eyebrow">YOUR AGENT WORKSPACE</div>
          <h1 id="workspace-title">
            Follow the team.
            <br />
            Check the handoff.
          </h1>
          <p>
            See how agents hand work to each other. Review shared waits and
            compare their outputs with the source before the next step.
          </p>
          <div className="workspace-intro-actions">
            <Link href="/demo" className="button primary">
              Explore the guided demo <ArrowRight size={16} />
            </Link>
            <Link href="/setup" className="text-link">
              Connect your workflow <ArrowRight size={14} />
            </Link>
          </div>
        </div>
        <div className="workspace-demo-note">
          <span className="eyebrow">START WITH AN EXAMPLE</span>
          <h2>
            A writer drafts a brief.
            <br />A reviewer checks it.
          </h2>
          <p>
            Start with the free local walkthrough, or review a live run that
            checks model-generated claims against sample sales data.
          </p>
          <span className="workspace-demo-disclosure">
            Local fixtures · optional live agents · up to three model calls
          </span>
        </div>
      </section>
      {(error || !live) && (
        <div className="banner warning" role="status">
          {error ||
            "The backend is reconnecting. The last recorded view may be out of date."}
          <button onClick={() => setRevision((n) => n + 1)}>Try again</button>
        </div>
      )}
      <section className="workspace-totals" aria-label="Workspace-wide counts">
        <div>
          <span>Connected workers</span>
          <strong>{live ? count("connected_workers") : "—"}</strong>
          <p>Workers currently reporting to this workspace</p>
        </div>
        <div>
          <span>Workflows needing review</span>
          <strong>{count("needs_attention")}</strong>
          <p>Permission waits or findings to inspect</p>
        </div>
        <div>
          <span>Recorded workflows</span>
          <strong>{count("recorded_workflows")}</strong>
          <p>Saved history, separate from live connections</p>
        </div>
      </section>
      <section
        className="workspace-attention"
        aria-labelledby="attention-title"
      >
        <div className="section-heading">
          <h2 id="attention-title">What needs attention</h2>
          <button
            className="button small"
            disabled={loading}
            onClick={() => setRevision((n) => n + 1)}
          >
            <RefreshCw size={14} /> Refresh
          </button>
        </div>
        {loading && !data ? (
          <p className="workspace-empty">Checking your workflows…</p>
        ) : data?.attention.length ? (
          <div className="workspace-attention-list">
            {data.attention.slice(0, 4).map((brief) => (
              <BriefRow key={brief.run.run_id} brief={brief} />
            ))}
          </div>
        ) : (
          <div className="workspace-empty">
            <h3>
              {error
                ? "Workspace summary is unavailable"
                : "No workflows need review right now"}
            </h3>
            <p>
              {error
                ? "Reconnect to inspect saved workflows and their current connections."
                : "Use the guided demo to see a permission wait and the work that can continue."}
            </p>
            <Link href={error ? "/runs" : "/demo"} className="text-link">
              {error ? "View recorded workflows" : "Open the guided demo"}{" "}
              <ArrowRight size={14} />
            </Link>
          </div>
        )}
        {data && data.counts.needs_attention > 4 && (
          <p className="workspace-history-note">
            Showing four workflows to review.{" "}
            <Link href="/runs">Browse all recorded workflows</Link>.
          </p>
        )}
      </section>
      <section aria-labelledby="recent-title">
        <div className="section-heading">
          <h2 id="recent-title">Recent work</h2>
          <Link className="text-link" href="/runs">
            All workflows <ArrowRight size={14} />
          </Link>
        </div>
        {data?.items.length ? (
          <div className="workspace-recent-list">
            {data.items.slice(0, 6).map((brief) => (
              <BriefRow key={brief.run.run_id} brief={brief} />
            ))}
          </div>
        ) : (
          <p className="workspace-empty">
            No work is recorded yet. Start the local demonstration or connect
            your own workflow.
          </p>
        )}
        <p className="workspace-history-note">
          Diagnostic checks and experiment trials stay in their own views.
          {data
            ? ` ${data.counts.diagnostic_workflows} diagnostic checks are hidden here.`
            : ""}{" "}
          {data ? `Updated ${time(data.as_of_ms)} UTC.` : ""}
        </p>
      </section>
    </div>
  );
}

function BriefRow({ brief }: { brief: RunBrief }) {
  const total = brief.progress.total;
  return (
    <article className="workspace-brief-row">
      <div className="workspace-brief-main">
        <Link
          href={`/runs/${brief.run.run_id}`}
          className="workspace-run-title"
        >
          {brief.run.name}
        </Link>
        <p>{brief.headline}</p>
      </div>
      <div className="workspace-brief-state">
        <span
          className={
            brief.connection.state === "connected"
              ? "workspace-live-label"
              : "workspace-recorded-label"
          }
        >
          {brief.connection.state === "connected"
            ? `${brief.connection.connected_workers} worker${brief.connection.connected_workers === 1 ? "" : "s"} connected`
            : brief.connection.state === "offline"
              ? "Recorded · workers offline"
              : "Recorded · no live worker integration"}
        </span>
        <span className="workspace-progress">
          {total
            ? `${brief.progress.completed} of ${total} tasks finished`
            : "No tasks recorded"}
        </span>
        {total > 0 && (
          <progress
            aria-label={`${brief.run.name} tasks finished`}
            value={brief.progress.completed}
            max={total}
          />
        )}
        <span className="workspace-recorded-status">
          Recorded status: {words(brief.run.status)}
        </span>
      </div>
      <Link className="button secondary small" href={brief.next_action.href}>
        {brief.next_action.label} <ArrowRight size={14} />
      </Link>
    </article>
  );
}
