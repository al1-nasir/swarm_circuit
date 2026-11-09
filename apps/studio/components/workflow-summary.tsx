"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { time } from "@/lib/model";
import { useProject } from "./shell";

type Brief = {
  guided_demo: { demo_id: string; state: string } | null;
  headline: string;
  explanation: string;
  classification: string;
  progress: {
    completed: number;
    total: number;
    waiting: number;
    held: number;
    failed: number;
  };
  connection: {
    state: string;
    connected_workers: number;
    last_heartbeat_ms: number | null;
  };
  next_action: { label: string; href: string };
  affected_task_ids: string[];
  unaffected_task_ids: string[];
  last_confirmation: {
    kind: string;
    at_ms: number;
    host_connected: boolean;
  } | null;
};
export function WorkflowSummary({
  runId,
  updated,
}: {
  runId: string;
  updated: number;
}) {
  const { config } = useProject();
  const [brief, setBrief] = useState<Brief | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => {
    setBrief(null);
  }, [runId]);
  useEffect(() => {
    if (!config) return;
    const abort = new AbortController();
    api<Brief>(`runs/${runId}/brief`, { signal: abort.signal })
      .then((r) => {
        if (abort.signal.aborted) return;
        setBrief(r);
        setUnavailable(false);
      })
      .catch(() => {
        if (!abort.signal.aborted) setUnavailable(true);
      });
    return () => abort.abort();
  }, [runId, updated, config?.projectId]);
  if (!brief)
    return unavailable ? (
      <div className="workflow-meaning metadata" role="status">
        The workflow summary is unavailable. The recorded map and evidence are
        still below.
      </div>
    ) : (
      <div className="workflow-meaning metadata" aria-busy="true">
        Reading workflow progress…
      </div>
    );
  return (
    <section className="workflow-meaning" aria-label="What is happening">
      <div className="workflow-meaning-copy">
        <span className="eyebrow">
          {brief.connection.state === "connected"
            ? "CONNECTED WORKERS"
            : "RECORDED WORKFLOW"}
        </span>
        <h2>{brief.headline}</h2>
        <p>{brief.explanation}</p>
        <div className="workflow-facts">
          <span>
            <strong>
              {brief.progress.completed}/{brief.progress.total}
            </strong>{" "}
            tasks complete
          </span>
          {brief.progress.waiting > 0 && (
            <span>{brief.progress.waiting} waiting</span>
          )}
          {brief.progress.held > 0 && <span>{brief.progress.held} paused</span>}
          {brief.progress.failed > 0 && (
            <span>{brief.progress.failed} failed</span>
          )}
          <span>
            {brief.connection.connected_workers
              ? `${brief.connection.connected_workers} connected worker${brief.connection.connected_workers === 1 ? "" : "s"}`
              : "No connected control worker"}
          </span>
        </div>
        {brief.last_confirmation && !brief.last_confirmation.host_connected && (
          <p className="metadata muted">
            Last host confirmation: {time(brief.last_confirmation.at_ms)} UTC.
            It is a historical record; the worker is offline now.
          </p>
        )}
      </div>
      <div className="workflow-meaning-actions">
        {brief.next_action?.href && (
          <Link className="button secondary" href={brief.next_action.href}>
            {brief.next_action.label}
          </Link>
        )}
        {brief.guided_demo && !brief.next_action?.href.startsWith("/demo?") && (
          <Link
            className="text-link"
            href={`/demo?demo=${encodeURIComponent(brief.guided_demo.demo_id)}`}
          >
            Return to walkthrough
          </Link>
        )}
      </div>
    </section>
  );
}
