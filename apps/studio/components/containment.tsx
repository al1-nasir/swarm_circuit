"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { commandLabel, confirmed, short, time } from "@/lib/model";
import type { Command, Snapshot } from "@/lib/types";
import { useProject } from "./shell";
import { Status } from "./ui";
import "./control-clarity.css";

type Preview = {
  approval_id: string;
  root_task_id: string;
  dependent_task_ids: string[];
  targets: {
    task_id: string;
    runtime_session_id: string;
    expected_task_version: number;
    checkpoint_id: string;
    fencing_epoch: number;
  }[];
  skipped: { task_id: string; reason: string }[];
  preview_sha256: string;
  max_targets: number;
  policy: string;
  commands: Command[];
  command_ids: string[];
  policy_request_id?: string;
  idempotency_key?: string;
  created_at_ms?: number;
};
type Pending = { key: string; approvalId: string; runId: string };
const unresolved = (record: Preview) =>
  record.commands.some((c) =>
    ["queued", "dispatched", "unknown"].includes(c.state),
  );

export function Containment({
  data,
  onRefresh,
}: {
  data: Snapshot;
  onRefresh: () => void;
}) {
  const { config, health } = useProject();
  const runId = data.run.run_id;
  const storage = `swarmcircuit:policy-intent:v1:${runId}`;
  const [open, setOpen] = useState(false);
  const [approval, setApproval] = useState("");
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [record, setRecord] = useState<Preview | null>(null);
  const [history, setHistory] = useState<Preview[]>([]);
  const [unconfirmedCount, setUnconfirmedCount] = useState(0);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [historyCursor, setHistoryCursor] = useState<string | null>(null);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const activeKey = useRef<string | null>(null);
  const historyGeneration = useRef(0);
  const activeRun = useRef(runId);
  activeRun.current = runId;
  const loadedOlderHistory = useRef(false);
  activeKey.current = pending?.key || null;
  const eligible = data.approvals.items.filter((a) => a.state === "pending");
  const connected = new Set(
    data.runtimes
      .filter((r) => r.state === "connected")
      .map((r) => r.runtime_session_id),
  );
  const label = (id: string) =>
    data.taskGraph.nodes.find((n) => n.id === id)?.label || short(id);
  const live =
    Boolean(config?.operator) &&
    health === "ready" &&
    data.run.mode === "control" &&
    connected.size > 0;
  const commandsFingerprint = data.commands.items
    .map((c) => `${c.command_id}:${c.state}:${c.acknowledgements.length}`)
    .join("|");
  const loadHistory = useCallback(async () => {
    const generation = ++historyGeneration.current;
    try {
      const saved = await api<{
        items: Preview[];
        next_cursor?: string | null;
        unconfirmed_count?: number;
      }>(`runs/${runId}/backpressure/history?limit=25`);
      if (generation !== historyGeneration.current) return;
      setHistory((previous) => {
        const known = new Set(saved.items.map((p) => p.policy_request_id));
        return [
          ...saved.items,
          ...previous.filter((p) => !known.has(p.policy_request_id)),
        ];
      });
      if (!loadedOlderHistory.current)
        setHistoryCursor(saved.next_cursor || null);
      setUnconfirmedCount(saved.unconfirmed_count || 0);
      setHistoryLoaded(true);
      setHistoryError("");
    } catch (e) {
      if (generation === historyGeneration.current)
        setHistoryError(
          e instanceof Error ? e.message : "Pause history unavailable.",
        );
    }
  }, [runId]);
  useEffect(() => {
    setPending(null);
    try {
      const p = JSON.parse(localStorage.getItem(storage) || "null");
      if (p && p.runId === runId && /^[0-9a-f-]{36}$/i.test(p.key))
        setPending(p);
    } catch {
      /* History remains available when browser storage is unavailable. */
    }
    setRecord(null);
    setHistory([]);
    setHistoryLoaded(false);
    setUnconfirmedCount(0);
    setHistoryCursor(null);
    loadedOlderHistory.current = false;
    setLoadingOlder(false);
    setPreview(null);
    setError("");
    return () => {
      historyGeneration.current += 1;
    };
  }, [runId, storage]);
  useEffect(() => {
    void loadHistory();
  }, [loadHistory, commandsFingerprint]);
  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    if (!dialog.current?.open) dialog.current?.showModal();
    return () => {
      dialog.current?.close();
      opener?.focus();
    };
  }, [open]);
  const reconcile = useCallback(async () => {
    if (!pending) return;
    try {
      const saved = await api<Preview>(
        `runs/${runId}/backpressure?key=${encodeURIComponent(pending.key)}`,
      );
      if (activeKey.current !== pending.key) return;
      setRecord(saved);
      setError("");
      onRefresh();
      void loadHistory();
      return saved;
    } catch (e) {
      if (activeKey.current !== pending.key) return;
      setError(
        e instanceof ApiError && e.status === 404
          ? "The original pause request has no saved outcome yet. Recheck this request before sending another."
          : e instanceof Error
            ? e.message
            : "Pause history unavailable.",
      );
    }
  }, [pending, runId, onRefresh, loadHistory]);
  useEffect(() => {
    if (!pending || busy) return;
    let stopped = false;
    const timer = setInterval(() => {
      void poll();
    }, 2000);
    async function poll() {
      const r = await reconcile();
      if (
        !stopped &&
        r &&
        r.commands.every((c) => !["queued", "dispatched"].includes(c.state))
      )
        clearInterval(timer);
    }
    void poll();
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [reconcile, pending, busy]);
  useEffect(() => {
    if (!unconfirmedCount && !history.some(unresolved)) return;
    const timer = setInterval(() => void loadHistory(), 5000);
    return () => clearInterval(timer);
  }, [history, loadHistory, unconfirmedCount]);
  async function olderHistory() {
    if (!historyCursor || loadingOlder) return;
    const requestRun = runId;
    setLoadingOlder(true);
    try {
      const saved = await api<{
        items: Preview[];
        next_cursor?: string | null;
        unconfirmed_count?: number;
      }>(
        `runs/${runId}/backpressure/history?limit=25&cursor=${encodeURIComponent(historyCursor)}`,
      );
      if (requestRun !== activeRun.current) return;
      setHistory((old) => [
        ...old,
        ...saved.items.filter(
          (p) => !old.some((r) => r.policy_request_id === p.policy_request_id),
        ),
      ]);
      loadedOlderHistory.current = true;
      setHistoryCursor(saved.next_cursor || null);
      setHistoryError("");
    } catch (e) {
      if (requestRun === activeRun.current)
        setHistoryError(
          e instanceof Error ? e.message : "Older history unavailable.",
        );
    } finally {
      if (requestRun === activeRun.current) setLoadingOlder(false);
    }
  }
  async function review() {
    if (!live || !reason.trim() || !approval) return;
    setBusy(true);
    setError("");
    try {
      setPreview(
        await api<Preview>(`runs/${runId}/backpressure`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": crypto.randomUUID(),
          },
          body: JSON.stringify({
            approval_id: approval,
            reason: reason.trim(),
            apply: false,
          }),
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Preview unavailable");
    } finally {
      setBusy(false);
    }
  }
  async function apply() {
    if (!preview || !live || busy) return;
    const intent = { key: crypto.randomUUID(), approvalId: approval, runId };
    try {
      localStorage.setItem(storage, JSON.stringify(intent));
    } catch {
      /* Keep the original key in this tab. */
    }
    activeKey.current = intent.key;
    setPending(intent);
    setBusy(true);
    setError("");
    try {
      const saved = await api<Preview>(`runs/${runId}/backpressure`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": intent.key,
        },
        body: JSON.stringify({
          approval_id: approval,
          reason: reason.trim(),
          apply: true,
          expected_preview_sha256: preview.preview_sha256,
        }),
      });
      setRecord(saved);
      setOpen(false);
      setPreview(null);
      onRefresh();
      void loadHistory();
    } catch (e) {
      if (e instanceof ApiError && e.status >= 400 && e.status < 500) {
        activeKey.current = null;
        setPending(null);
        try {
          localStorage.removeItem(storage);
        } catch {
          /* Storage is optional. */
        }
        setPreview(null);
        setError(
          `${e.message}. Review the affected tasks again before submitting.`,
        );
      } else {
        setOpen(false);
        setError(
          "The pause request's outcome is unknown. Recheck the original request; no replacement was sent.",
        );
      }
    } finally {
      setBusy(false);
    }
  }
  const localUncertain = Boolean(pending && (!record || unresolved(record)));
  const uncertain =
    localUncertain || unconfirmedCount > 0 || history.some(unresolved);
  const affected = new Set(preview?.dependent_task_ids || []);
  const independent = data.taskGraph.nodes.filter((n) => !affected.has(n.id));
  if (!eligible.length && !pending && !history.length && historyLoaded)
    return null;
  const otherHistory = history.filter(
    (p) =>
      !record?.policy_request_id ||
      p.policy_request_id !== record.policy_request_id,
  );
  return (
    <section className="panel containment-panel">
      <div className="panel-title">
        <div>
          <h2>Pause affected tasks</h2>
          <p className="metadata muted">
            Review the tasks sharing a permission wait. Work outside the
            selected branch stays outside this request.
          </p>
        </div>
        <button
          className="button secondary"
          disabled={
            !live ||
            !eligible.length ||
            uncertain ||
            !historyLoaded ||
            Boolean(historyError)
          }
          onClick={() => {
            setApproval(eligible[0].approval_id);
            setReason("");
            setPreview(null);
            setError("");
            setOpen(true);
          }}
        >
          Review affected tasks
        </button>
      </div>
      {!live && (
        <p className="containment-note">
          {data.run.mode !== "control"
            ? "This workflow records activity only. Pausing requires connected workers with control hooks."
            : !config?.operator
              ? "A local operator credential is required to request a pause."
              : health !== "ready"
                ? "Reconnect to the backend before requesting a pause."
                : "Workers are offline. Saved confirmations below describe earlier requests, not their current state."}
        </p>
      )}
      {uncertain && (
        <p className="containment-note">
          An earlier request still has an unconfirmed outcome. Recheck its
          history before requesting another pause.
        </p>
      )}
      {error && (
        <div className="banner warning" role="status">
          {error}
        </div>
      )}
      {historyError && (
        <div className="banner warning" role="status">
          Pause history could not be refreshed. {historyError}{" "}
          <button onClick={() => void loadHistory()}>Recheck history</button>
        </div>
      )}
      {!historyLoaded && !historyError && (
        <p className="containment-note">Loading saved pause requests…</p>
      )}
      {pending && (
        <div className="policy-record">
          <div className="row-title">
            <strong>Pause request {short(pending.key)}</strong>
            <button className="button small" onClick={() => void reconcile()}>
              Recheck request
            </button>
          </div>
          {record ? (
            <>
              <PauseOutcome
                record={record}
                label={label}
                connected={connected}
              />
              {!localUncertain && (
                <button
                  className="text-link"
                  onClick={() => {
                    try {
                      localStorage.removeItem(storage);
                    } catch {
                      /* Storage is optional. */
                    }
                    activeKey.current = null;
                    setPending(null);
                    setRecord(null);
                  }}
                >
                  Dismiss this local notice
                </button>
              )}
            </>
          ) : (
            <>
              <p className="metadata">
                Waiting for the saved outcome. The original request is retained
                while its status is checked.
              </p>
              <details className="pause-technical">
                <summary>Request details</summary>
                <span className="mono break">{pending.key}</span>
              </details>
            </>
          )}
        </div>
      )}
      {otherHistory.map((saved) => (
        <details
          className="pause-history-item"
          key={saved.policy_request_id}
          open={unresolved(saved)}
        >
          <summary>
            Pause request · {saved.commands.length} task
            {saved.commands.length === 1 ? "" : "s"}
            <span className="muted">
              {saved.created_at_ms
                ? ` · ${new Date(saved.created_at_ms).toLocaleString("en-GB", { timeZone: "UTC", dateStyle: "medium", timeStyle: "short" })} UTC`
                : " · saved history"}
            </span>
          </summary>
          <PauseOutcome record={saved} label={label} connected={connected} />
        </details>
      ))}
      {historyCursor && (
        <div className="pause-history-footer">
          <button
            className="button small"
            disabled={loadingOlder}
            onClick={() => void olderHistory()}
          >
            {loadingOlder ? "Loading…" : "Older pause requests"}
          </button>
        </div>
      )}
      <dialog
        ref={dialog}
        className="control-dialog containment-dialog"
        aria-labelledby="containment-title"
        onCancel={(e) => {
          if (busy) e.preventDefault();
          else setOpen(false);
        }}
        onClose={() => setOpen(false)}
      >
        <div className="row-title">
          <div>
            <div className="eyebrow">REVIEW A PAUSE</div>
            <h2 id="containment-title">Which tasks should wait?</h2>
          </div>
          <button
            className="button small"
            aria-label="Close pause review"
            disabled={busy}
            onClick={() => setOpen(false)}
          >
            Close
          </button>
        </div>
        <p className="dialog-description">
          A pause takes effect only when a connected worker confirms it at a
          safe stopping point. Permission decisions remain separate.
        </p>
        <label className="research-field">
          Shared permission request
          <select
            aria-label="Pause approval"
            value={approval}
            disabled={busy}
            onChange={(e) => {
              setApproval(e.target.value);
              setPreview(null);
            }}
          >
            {eligible.map((a) => (
              <option key={a.approval_id} value={a.approval_id}>
                {label(a.related_task_id || "")} · {short(a.approval_id)}
              </option>
            ))}
          </select>
        </label>
        <label htmlFor="containment-reason">
          Reason · saved with the request
        </label>
        <textarea
          id="containment-reason"
          required
          maxLength={1000}
          value={reason}
          disabled={busy}
          onChange={(e) => {
            setReason(e.target.value);
            setPreview(null);
          }}
          placeholder="Explain why these tasks should wait…"
        />
        <button
          className="button secondary"
          onClick={() => void review()}
          disabled={busy || !live || !reason.trim()}
        >
          {busy ? "Checking…" : "Preview affected tasks"}
        </button>
        {error && (
          <div className="banner warning" role="status">
            {error}
          </div>
        )}
        {preview && (
          <div className="containment-preview">
            <h3>Tasks in this request</h3>
            <p>
              Shared starting point:{" "}
              <strong>{label(preview.root_task_id)}</strong>
            </p>
            <div className="pause-target-summary">
              <span>
                <strong>{preview.targets.length}</strong> ready for a pause
                request
              </span>
              <span>
                <strong>{preview.skipped.length}</strong> unavailable or already
                stopped
              </span>
              <span>
                <strong>{independent.length}</strong> outside this branch
              </span>
            </div>
            <div className="table-scroll">
              <table className="payment-table">
                <thead>
                  <tr>
                    <th>Task</th>
                    <th>What will be requested</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.targets.map((t) => (
                    <tr key={t.task_id}>
                      <td>{label(t.task_id)}</td>
                      <td>Pause at its current safe stopping point</td>
                    </tr>
                  ))}
                  {preview.skipped.map((t) => (
                    <tr key={t.task_id}>
                      <td>{label(t.task_id)}</td>
                      <td>Not included: {t.reason.replaceAll("_", " ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <details>
              <summary>
                Work outside this request · {independent.length}
              </summary>
              <ul>
                {independent.map((n) => (
                  <li key={n.id}>{n.label}</li>
                ))}
              </ul>
            </details>
            <details className="pause-technical">
              <summary>Technical evidence for this preview</summary>
              <p>
                The server checks task versions, stopping-point identities and
                worker epochs again before accepting this exact preview. A
                change requires a new review. At most {preview.max_targets}{" "}
                tasks may be included.
              </p>
              <ul>
                {preview.targets.map((t) => (
                  <li key={t.task_id}>
                    {label(t.task_id)} · checkpoint{" "}
                    <span className="mono">{short(t.checkpoint_id)}</span> ·
                    epoch {t.fencing_epoch} · task v{t.expected_task_version}
                  </li>
                ))}
              </ul>
              <p className="mono break">Preview: {preview.preview_sha256}</p>
            </details>
          </div>
        )}
        <div className="dialog-actions">
          <button
            className="button secondary"
            disabled={busy}
            onClick={() => setOpen(false)}
          >
            Cancel
          </button>
          <button
            className="button primary"
            onClick={() => void apply()}
            disabled={busy || !live || !preview?.targets.length || uncertain}
          >
            Request pause for {preview?.targets.length || 0} tasks
          </button>
        </div>
      </dialog>
    </section>
  );
}

function PauseOutcome({
  record,
  label,
  connected,
}: {
  record: Preview;
  label: (id: string) => string;
  connected: Set<string>;
}) {
  return (
    <>
      <p className="pause-host-note">
        A received request is not a confirmed pause. This is saved history; the
        workflow map shows the latest observed task state.
      </p>
      <div className="table-scroll">
        <table className="payment-table">
          <thead>
            <tr>
              <th>Task</th>
              <th>Confirmed result</th>
              <th>Worker connection now</th>
            </tr>
          </thead>
          <tbody>
            {record.commands.map((c) => (
              <tr key={c.command_id}>
                <td>{label(c.task_id)}</td>
                <td>
                  <Status
                    value={
                      c.state === "applied" && !confirmed(c)
                        ? "unknown"
                        : c.state
                    }
                  >
                    {commandLabel(c)}
                  </Status>
                  {c.completed_at_ms && (
                    <small>Recorded at {time(c.completed_at_ms)} UTC</small>
                  )}
                </td>
                <td>
                  {connected.has(c.runtime_session_id)
                    ? "Connected"
                    : "Offline · current pause unconfirmed"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {record.skipped.length > 0 && (
        <p className="pause-host-note">
          {record.skipped.length} tasks were not included. This request does not
          establish that the whole branch is paused.
        </p>
      )}
      <details className="pause-technical">
        <summary>Technical evidence</summary>
        <dl>
          <dt>Saved request</dt>
          <dd className="mono">
            {record.policy_request_id || "Awaiting saved identity"}
          </dd>
          <dt>Shared permission</dt>
          <dd className="mono">{record.approval_id}</dd>
        </dl>
        {record.commands.map((c) => (
          <p key={c.command_id}>
            {label(c.task_id)} · {c.acknowledgements.length} recorded
            confirmations · epoch {c.session_fencing_epoch} · task v
            {c.expected_task_version}
          </p>
        ))}
      </details>
    </>
  );
}
