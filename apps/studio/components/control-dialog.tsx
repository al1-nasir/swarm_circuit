"use client";
import {
  ArrowRight,
  CircleHelp,
  GitBranch,
  Pause,
  Play,
  ShieldCheck,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { closure, short } from "@/lib/model";
import type { GraphNode, Snapshot } from "@/lib/types";
import "./control-clarity.css";

export interface Draft {
  node: GraphNode;
  kind: "hold_task" | "resume_task";
}
export function ControlDialog({
  draft,
  data,
  onClose,
  onSubmit,
  blocked,
}: {
  draft: Draft;
  data: Snapshot;
  onClose: () => void;
  onSubmit: (reason: string) => Promise<void>;
  blocked: string;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const hold = draft.kind === "hold_task";
  const affected = closure(data.taskGraph, draft.node.id);
  const current = data.taskGraph.nodes.find((n) => n.id === draft.node.id);
  const changed =
    current?.state_version !== draft.node.state_version ||
    current?.control?.checkpoint_id !== draft.node.control?.checkpoint_id ||
    current?.control?.fencing_epoch !== draft.node.control?.fencing_epoch;
  const reviewBlocked =
    blocked ||
    (!current?.control?.[draft.kind]
      ? "This task is no longer eligible for this request. Cancel and review its current permissions, prerequisites and command history."
      : "");
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    dialog.current?.showModal();
    return () => {
      dialog.current?.close();
      opener?.focus();
    };
  }, []);
  return (
    <dialog
      ref={dialog}
      className="control-dialog"
      aria-labelledby="control-title"
      onCancel={(e) => {
        e.preventDefault();
        if (!submitting) onClose();
      }}
    >
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          if (submitting || changed || reviewBlocked || !reason.trim()) return;
          setSubmitting(true);
          try {
            await onSubmit(reason.trim());
          } finally {
            setSubmitting(false);
          }
        }}
      >
        <div className="dialog-heading">
          <span className="dialog-icon">
            {hold ? <Pause size={23} /> : <Play size={23} />}
          </span>
          <button
            type="button"
            className="icon-button"
            aria-label="Cancel control request"
            disabled={submitting}
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </div>
        <div className="eyebrow">REVIEW TASK CONTROL</div>
        <h2 id="control-title">{hold ? "Request pause" : "Request resume"}</h2>
        <p className="dialog-description">{draft.node.label}</p>
        <details className="technical-boundary">
          <summary>Technical evidence for this stopping point</summary>
          <div className="dialog-target">
            <GitBranch size={18} />
            <div>
              <strong>
                {short(draft.node.id)}
                <span className="muted">
                  {" "}
                  · task v{draft.node.state_version}
                </span>
              </strong>
              <small>
                Checkpoint{" "}
                {draft.node.control?.checkpoint_id
                  ? short(draft.node.control.checkpoint_id)
                  : "unavailable"}{" "}
                · epoch {draft.node.control?.fencing_epoch}
              </small>
            </div>
          </div>
        </details>
        <div className="dialog-impact">
          <h3>What this request affects</h3>
          <p>
            {hold
              ? "Only this task is included. Its worker must confirm the pause at the current safe stopping point."
              : "The worker checks permissions and prerequisites again before confirming that this task can resume."}
          </p>
          <div>
            <span>
              <strong>1</strong>target task
            </span>
            <span>
              <strong>{Math.max(0, affected.size - 1)}</strong>dependent tasks
            </span>
            <span>
              <strong>{data.taskGraph.nodes.length - affected.size}</strong>
              outside this branch
            </span>
          </div>
        </div>
        <div className="banner info">
          <ShieldCheck size={17} />
          <span>
            Other tasks are not paused by this request. Work already in progress
            is not interrupted, and permissions or payment decisions are not
            changed.
          </span>
        </div>
        <label className="reason-label" htmlFor="control-reason">
          Reason <span>Required · recorded in command history</span>
        </label>
        <textarea
          id="control-reason"
          autoFocus
          maxLength={1000}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder={
            hold
              ? "Explain why this task should wait…"
              : "Explain why this task is ready to continue…"
          }
          required
          disabled={submitting}
        />
        {(changed || reviewBlocked) && (
          <div role="status" className="banner warning">
            {changed
              ? "Task or runtime changed since review. Cancel and open a fresh review."
              : reviewBlocked}
          </div>
        )}
        <div className="dialog-footer">
          <button
            type="button"
            className="button secondary"
            onClick={onClose}
            disabled={submitting}
          >
            Cancel
          </button>
          <button
            className="button primary"
            disabled={
              submitting || changed || Boolean(reviewBlocked) || !reason.trim()
            }
          >
            {submitting
              ? "Submitting…"
              : hold
                ? "Request pause"
                : "Request resume"}
            <ArrowRight size={15} />
          </button>
        </div>
        <p className="dialog-footnote">
          <CircleHelp size={12} />A request becomes confirmed only after the
          worker reports the result.
        </p>
      </form>
    </dialog>
  );
}
