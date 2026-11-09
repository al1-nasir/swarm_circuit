"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import {
  demoHeadline,
  demoDecisionBody,
  demoDecisionHash,
  demoStateLabel,
  demoTerminal,
  demoStartBody,
  demoRestoreStartBody,
  demoReviewLabel,
  demoFailureLabel,
  type Demo,
  type DemoCapabilities,
  type DemoDecisionIntent,
  type DemoMode,
  type DemoStartIntent,
} from "@/lib/demo";
import { time } from "@/lib/model";
import { useProject } from "./shell";
import { Asset } from "./asset";
import { Status } from "./ui";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const outputs = [
  {
    slug: "public-findings",
    title: "Public findings",
    note: "Independent research, available without dataset permission.",
    asset: "globe",
  },
  {
    slug: "dataset-analysis",
    title: "Dataset analysis",
    note: "Calculated only after access is granted.",
    asset: "database",
  },
  {
    slug: "final-brief",
    title: "Analyst brief",
    note: "The completed deliverable, combining the findings.",
    asset: "files",
  },
];
const agentOutputs = [
  { slug: "agent-draft", title: "Writer's original draft" },
  { slug: "agent-review", title: "Reviewer's feedback" },
  { slug: "agent-repair", title: "Writer's repair" },
  { slug: "handoff-evidence", title: "Handoff checks and provenance" },
];
function readStored<T>(key: string): T | null {
  try {
    return JSON.parse(localStorage.getItem(key) || "null") as T | null;
  } catch {
    return null;
  }
}
function writeStored(key: string, value: unknown) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* The server remains authoritative when storage is unavailable. */
  }
}
function ArtifactDocument({ text }: { text: string }) {
  return (
    <article className="demo-document">
      {text
        .trim()
        .split(/\n\s*\n/)
        .map((block, i) => {
          const lines = block.split("\n");
          if (/^```(?:json)?\n[\s\S]*\n```$/.test(block))
            return (
              <pre key={i}>
                <code>{block.replace(/^```(?:json)?\n|\n```$/g, "")}</code>
              </pre>
            );
          if (/^#{1,3} /.test(block))
            return <h3 key={i}>{block.replace(/^#{1,3} /, "")}</h3>;
          if (lines.every((line) => /^[-*] /.test(line)))
            return (
              <ul key={i}>
                {lines.map((line, j) => (
                  <li key={j}>{line.slice(2)}</li>
                ))}
              </ul>
            );
          if (lines.some((line) => line.startsWith("|")))
            return <pre key={i}>{block}</pre>;
          return <p key={i}>{block}</p>;
        })}
    </article>
  );
}
export function GuidedDemo() {
  const { config, health, rememberRun } = useProject();
  const router = useRouter();
  const params = useSearchParams();
  const selected = params.get("demo") || "";
  const [recent, setRecent] = useState<Demo[]>([]);
  const [demo, setDemo] = useState<Demo | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [unknownStart, setUnknownStart] = useState(false);
  const [startMode, setStartMode] = useState<DemoMode>("fixture");
  const [capabilities, setCapabilities] = useState<DemoCapabilities | null>(
    null,
  );
  const [capabilityError, setCapabilityError] = useState("");
  const [capabilityRevision, setCapabilityRevision] = useState(0);
  const [liveReviewOpen, setLiveReviewOpen] = useState(false);
  const [retryLiveStart, setRetryLiveStart] = useState(false);
  const [decisionIntent, setDecisionIntent] =
    useState<DemoDecisionIntent | null>(null);
  const [permissionOpen, setPermissionOpen] = useState(false);
  const [retryDecision, setRetryDecision] = useState(false);
  const [decisionError, setDecisionError] = useState("");
  const [decision, setDecision] = useState<"approved" | "denied">("approved");
  const [reason, setReason] = useState("");
  const [artifact, setArtifact] = useState("");
  const [text, setText] = useState("");
  const [artifactError, setArtifactError] = useState("");
  const [artifactLoading, setArtifactLoading] = useState(false);
  const [artifactRevision, setArtifactRevision] = useState(0);
  const dialog = useRef<HTMLDialogElement>(null);
  const liveDialog = useRef<HTMLDialogElement>(null);
  const originalDecision = useRef<{
    demoId: string;
    key: string;
    body: string;
  } | null>(null);
  const startKey = `swarmcircuit:demo-start:${config?.projectId || ""}`;
  const decisionKey = `swarmcircuit:demo-decision:${selected}`;
  const activeRef = useRef(selected);
  activeRef.current = selected;
  const operator = Boolean(config?.operator) && health === "ready";
  const loadRecent = useCallback(async () => {
    if (!config) return [];
    const r = await api<{ items: Demo[] }>(
      `projects/${config.projectId}/demos`,
    );
    setRecent(r.items);
    return r.items;
  }, [config?.projectId]);
  useEffect(() => {
    if (!config?.projectId || selected) return;
    let stopped = false;
    api<{ items: Demo[] }>(`projects/${config.projectId}/demos`)
      .then((r) => {
        if (!stopped) setRecent(r.items);
      })
      .catch((e) => {
        if (!stopped) setError(e.message);
      });
    return () => {
      stopped = true;
    };
  }, [config?.projectId, selected]);
  useEffect(() => {
    if (!config) return;
    const storedStart = readStored<DemoStartIntent>(startKey);
    const validStart =
      typeof storedStart?.key === "string" && uuid.test(storedStart.key);
    setUnknownStart(validStart);
    if (storedStart && !validStart) writeStored(startKey, null);
  }, [config?.projectId, startKey]);
  useEffect(() => {
    if (!config?.projectId) return;
    const abort = new AbortController();
    api<DemoCapabilities>(`projects/${config.projectId}/demo-capabilities`, {
      signal: abort.signal,
    })
      .then((value) => {
        if (!abort.signal.aborted) {
          setCapabilities(value);
          setCapabilityError("");
        }
      })
      .catch(() => {
        if (!abort.signal.aborted) {
          setCapabilities(null);
          setCapabilityError(
            "Live setup could not be checked. The offline walkthrough remains available.",
          );
        }
      });
    return () => abort.abort();
  }, [config?.projectId, capabilityRevision]);
  useEffect(() => {
    setDemo(null);
    setError("");
    setText("");
    setArtifact("");
    setPermissionOpen(false);
    setLiveReviewOpen(false);
    setRetryDecision(false);
    setDecisionError("");
    originalDecision.current = null;
    const intent = readStored<DemoDecisionIntent>(decisionKey);
    setDecisionIntent(
      intent &&
        uuid.test(intent.key) &&
        ["approved", "denied"].includes(intent.decision)
        ? intent
        : null,
    );
  }, [selected, decisionKey]);
  const acceptStatus = useCallback(
    (r: Demo) => {
      if (activeRef.current !== r.demo_id) return;
      setDemo(r);
      setRecent((items) =>
        items.map((item) => (item.demo_id === r.demo_id ? r : item)),
      );
      setError("");
      if (r.permission !== "pending" || demoTerminal(r.state)) {
        setDecisionIntent(null);
        setPermissionOpen(false);
        setRetryDecision(false);
        setReason("");
        originalDecision.current = null;
        writeStored(`swarmcircuit:demo-decision:${r.demo_id}`, null);
      }
      if (r.run_id)
        rememberRun({ run_id: r.run_id, name: "Analyst brief · guided demo" });
      setArtifact((old) =>
        r.artifacts.some((a) => a.slug === old)
          ? old
          : r.artifacts.some((a) => a.slug === "final-brief")
            ? "final-brief"
            : r.artifacts[0]?.slug || "",
      );
    },
    [rememberRun],
  );
  useEffect(() => {
    if (!selected || !config) return;
    if (!uuid.test(selected)) {
      setError(
        "This walkthrough link is invalid. Choose a recent walkthrough or start a new one.",
      );
      return;
    }
    const abort = new AbortController();
    let inFlight = false;
    let ended = false;
    async function poll() {
      if (inFlight || ended) return;
      inFlight = true;
      try {
        const r = await api<Demo>(`demos/${selected}`, {
          signal: abort.signal,
        });
        if (!abort.signal.aborted) {
          acceptStatus(r);
          ended = demoTerminal(r.state);
        }
      } catch (e) {
        if (!abort.signal.aborted)
          setError(
            e instanceof Error
              ? e.message
              : "The last saved walkthrough is retained. Recheck its status.",
          );
      } finally {
        inFlight = false;
      }
    }
    void poll();
    const timer = setInterval(() => void poll(), 1500);
    return () => {
      abort.abort();
      clearInterval(timer);
    };
  }, [selected, config?.projectId, acceptStatus]);
  useEffect(() => {
    if (permissionOpen && !dialog.current?.open) dialog.current?.showModal();
    else if (!permissionOpen && dialog.current?.open) dialog.current.close();
  }, [permissionOpen]);
  useEffect(() => {
    if (liveReviewOpen && !liveDialog.current?.open)
      liveDialog.current?.showModal();
    else if (!liveReviewOpen && liveDialog.current?.open)
      liveDialog.current.close();
  }, [liveReviewOpen]);
  useEffect(() => {
    setText("");
    setArtifactError("");
    if (!selected || !artifact) {
      setArtifactLoading(false);
      return;
    }
    const abort = new AbortController();
    setArtifactLoading(true);
    fetch(`/api/backend/demos/${selected}/artifacts/${artifact}`, {
      cache: "no-store",
      signal: abort.signal,
    })
      .then(async (r) => {
        if (!r.ok)
          throw new Error(
            "This output could not be loaded. Recheck the walkthrough.",
          );
        const value = await r.text();
        if (!abort.signal.aborted) setText(value);
      })
      .catch((e) => {
        if (!abort.signal.aborted) setArtifactError(e.message);
      })
      .finally(() => {
        if (!abort.signal.aborted) setArtifactLoading(false);
      });
    return () => abort.abort();
  }, [selected, artifact, artifactRevision]);
  function open(id: string) {
    router.push(`/demo?demo=${encodeURIComponent(id)}`, { scroll: false });
  }
  async function recheck() {
    const requestSelected = selected;
    try {
      const pendingStart = readStored<DemoStartIntent>(startKey);
      if (pendingStart?.key && config) {
        const recovered = await api<{ items: Demo[] }>(
          `projects/${config.projectId}/demos?key=${encodeURIComponent(pendingStart.key)}`,
        );
        if (recovered.items.length) {
          writeStored(startKey, null);
          setUnknownStart(false);
          if (activeRef.current === requestSelected)
            open(recovered.items[0].demo_id);
        }
      }
      await loadRecent();
      if (selected && uuid.test(selected))
        acceptStatus(await api<Demo>(`demos/${selected}`));
      if (activeRef.current === requestSelected) {
        setError("");
        setArtifactRevision((n) => n + 1);
      }
    } catch (e) {
      if (activeRef.current !== requestSelected) return;
      setError(
        e instanceof Error
          ? e.message
          : "Status unavailable. Keep the original request.",
      );
    }
  }
  function reviewStart(mode: DemoMode = startMode, retryOriginal = false) {
    const saved = readStored<DemoStartIntent>(startKey);
    const originalBody = saved ? demoRestoreStartBody(saved) : null;
    if (retryOriginal && !originalBody) {
      setError(
        "The original start content cannot be reconstructed. Recheck its saved outcome before starting another walkthrough.",
      );
      return;
    }
    const requestedMode = retryOriginal
      ? originalBody === demoStartBody("live")
        ? "live"
        : "fixture"
      : mode;
    if (requestedMode === "live") {
      setRetryLiveStart(retryOriginal);
      setLiveReviewOpen(true);
    } else void start(retryOriginal, "fixture");
  }
  async function start(retryOriginal = false, mode: DemoMode = "fixture") {
    if (!config || !operator || busy || (unknownStart && !retryOriginal))
      return;
    const previous = readStored<DemoStartIntent>(startKey);
    const key = retryOriginal ? previous?.key : crypto.randomUUID();
    if (!key || !uuid.test(key)) return;
    const body =
      retryOriginal && previous
        ? demoRestoreStartBody(previous)
        : demoStartBody(mode);
    if (!body) return;
    if (
      body === demoStartBody("live") &&
      !capabilities?.live.available &&
      !retryOriginal
    ) {
      setLiveReviewOpen(false);
      setError(
        "Live agents are not configured on this server. Recheck setup or choose the offline walkthrough.",
      );
      return;
    }
    writeStored(startKey, { key, body });
    setLiveReviewOpen(false);
    const requestSelected = selected;
    setBusy(true);
    setError("");
    try {
      const r = await api<Demo>(`projects/${config.projectId}/demos`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": key },
        body,
      });
      writeStored(startKey, null);
      setUnknownStart(false);
      if (activeRef.current === requestSelected) open(r.demo_id);
      void loadRecent().catch(() => {});
    } catch (e) {
      if (activeRef.current !== requestSelected) return;
      if (
        e instanceof ApiError &&
        e.status >= 400 &&
        e.status < 500 &&
        e.status !== 408
      ) {
        writeStored(startKey, null);
        setUnknownStart(false);
        setError(e.message);
        return;
      }
      setUnknownStart(true);
      setError(
        `The start outcome is unknown. Recheck recent walkthroughs before making another request. ${e instanceof Error ? e.message : ""}`,
      );
    } finally {
      setBusy(false);
    }
  }
  async function submitDecision() {
    if (
      !demo ||
      !operator ||
      busy ||
      !reason.trim() ||
      (decisionIntent && !retryDecision)
    )
      return;
    const id = demo.demo_id;
    setBusy(true);
    setError("");
    setDecisionError("");
    try {
      const body = demoDecisionBody(decision, reason);
      const requestSha256 = await demoDecisionHash(body);
      if (activeRef.current !== id) return;
      const intent = retryDecision
        ? decisionIntent
        : {
            key: crypto.randomUUID(),
            decision,
            requestSha256,
          };
      if (!intent) return;
      if (
        retryDecision &&
        (!intent.requestSha256 || intent.requestSha256 !== requestSha256)
      ) {
        setDecisionError(
          "Use the exact original reason to retry this request. No new request was sent.",
        );
        return;
      }
      writeStored(`swarmcircuit:demo-decision:${id}`, intent);
      setDecisionIntent(intent);
      originalDecision.current = { demoId: id, key: intent.key, body };
      const r = await api<Demo>(`demos/${id}/decision`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": intent.key,
        },
        body,
      });
      if (activeRef.current !== id) return;
      acceptStatus(r);
      setPermissionOpen(false);
      setRetryDecision(false);
      setReason("");
    } catch (e) {
      if (activeRef.current !== id) return;
      if (
        e instanceof ApiError &&
        e.status >= 400 &&
        e.status < 500 &&
        e.status !== 408
      ) {
        writeStored(`swarmcircuit:demo-decision:${id}`, null);
        setDecisionIntent(null);
        originalDecision.current = null;
        setError(e.message);
        setPermissionOpen(false);
        void recheck();
        return;
      }
      setError(
        `Permission outcome is unconfirmed. Recheck this walkthrough; no replacement request will be sent automatically. ${e instanceof Error ? e.message : ""}`,
      );
      setPermissionOpen(false);
    } finally {
      setBusy(false);
    }
  }
  const activeWalkthrough = recent.find((d) => !demoTerminal(d.state));
  const selectedArtifact = demo?.artifacts.find((a) => a.slug === artifact);
  const liveMode = demo ? demo.execution_mode === "live" : startMode === "live";
  function reviewSampleAccess() {
    setReason("");
    setDecision("approved");
    setRetryDecision(false);
    setDecisionError("");
    setPermissionOpen(true);
  }
  return (
    <div className="page-content demo-page">
      <div className="page-heading">
        <div>
          <div className="eyebrow">GUIDED WALKTHROUGH</div>
          <h1>
            {liveMode
              ? "Follow the team's handoffs."
              : "A team with one shared blocker."}
          </h1>
          <p>
            {liveMode
              ? "Read the writer's draft, the reviewer's feedback and any repair before the checked brief is published."
              : "See what can keep moving, review sample data access, and read the finished analyst brief."}
          </p>
        </div>
        <div className="demo-mode">
          {liveMode ? "LIVE AGENTS · SAMPLE DATA" : "LOCAL SAMPLE DATA"}
        </div>
      </div>
      <p className="demo-grounding">
        {liveMode
          ? "Live model calls use only bundled sample data. Up to three calls; provider charges may apply. No payments or production permissions are changed."
          : "A real SDK workflow using local fixtures. No model calls, payments, or production permissions."}
      </p>
      {demo?.state === "failed" && (
        <div className="banner warning" role="status">
          <p>
            {demoFailureLabel(demo.failure_code)}{" "}
            {liveMode
              ? "Saved agent evidence is retained. No offline brief was substituted for this live run."
              : "Saved outputs remain available."}
          </p>
        </div>
      )}
      {error && (
        <div className="banner warning" role="status">
          <span>{error}</span>
          <button onClick={() => void recheck()}>Recheck status</button>
        </div>
      )}
      {!operator && (
        <p className="demo-readonly" role="status">
          {health !== "ready"
            ? "Reconnect to the backend to start or review access. Previously loaded outputs remain on screen."
            : "This is a read-only workspace. A local operator can start the walkthrough and review its sample permission."}
        </p>
      )}
      {!selected && (
        <>
          <section className="demo-intro">
            <div>
              <span className="eyebrow">CHOOSE A WALKTHROUGH</span>
              <div
                className="demo-intro-actions"
                role="group"
                aria-label="Walkthrough mode"
              >
                <button
                  className={`button ${startMode === "fixture" ? "primary" : "secondary"}`}
                  aria-pressed={startMode === "fixture"}
                  onClick={() => setStartMode("fixture")}
                >
                  Offline SDK walkthrough
                </button>
                <button
                  className={`button ${startMode === "live" ? "primary" : "secondary"}`}
                  aria-pressed={startMode === "live"}
                  onClick={() => setStartMode("live")}
                >
                  Live writer and reviewer
                </button>
              </div>
              <h2>Prepare a quarterly sales brief.</h2>
              <p>
                {startMode === "live"
                  ? "A writer turns checked sample facts into a structured draft. A separate reviewer reads that draft and its source facts. One repair is allowed if needed; typed facts must pass the source-data check before publication."
                  : "The team can read public reference notes immediately. Analysis of a sample sales dataset needs your permission. That wait should leave the independent research free to finish."}
              </p>
              {startMode === "live" && (
                <p className="metadata" role="status">
                  {capabilities?.live.available
                    ? `Configured: ${capabilities.live.configured_model} via ${capabilities.live.provider_host}. Two calls normally, three maximum. Sample access still needs your review before any model call.`
                    : capabilityError ||
                      (capabilities
                        ? "Live agents need a provider configured on the server. Choose the offline walkthrough while setup is unavailable."
                        : "Checking the server's live setup…")}{" "}
                  <button
                    className="text-link"
                    onClick={() => setCapabilityRevision((n) => n + 1)}
                  >
                    Recheck live setup
                  </button>
                </p>
              )}
              <div className="demo-intro-actions">
                <button
                  className="button primary"
                  disabled={
                    !operator ||
                    busy ||
                    unknownStart ||
                    (!activeWalkthrough &&
                      startMode === "live" &&
                      !capabilities?.live.available)
                  }
                  onClick={() =>
                    activeWalkthrough
                      ? open(activeWalkthrough.demo_id)
                      : reviewStart()
                  }
                >
                  {busy
                    ? "Starting…"
                    : activeWalkthrough
                      ? `Continue active ${activeWalkthrough.execution_mode === "live" ? "live" : "offline"} walkthrough`
                      : startMode === "live"
                        ? "Review live walkthrough"
                        : "Start walkthrough"}
                </button>
                <Link href="/setup" className="text-link">
                  Connect your own workflow
                </Link>
              </div>
              {activeWalkthrough &&
                activeWalkthrough.execution_mode !== startMode && (
                  <p className="metadata">
                    Finish the active{" "}
                    {activeWalkthrough.execution_mode === "live"
                      ? "live"
                      : "offline"}{" "}
                    walkthrough before starting another mode.
                  </p>
                )}
              {unknownStart && (
                <p className="metadata">
                  A previous start is unconfirmed. Use Recheck status to recover
                  the original walkthrough.{" "}
                  <button className="text-link" onClick={() => void recheck()}>
                    Recheck status
                  </button>
                  {" · "}
                  <button
                    className="text-link"
                    disabled={!operator || busy}
                    onClick={() => reviewStart(startMode, true)}
                  >
                    Retry original start
                  </button>
                </p>
              )}
            </div>
            <ol className="demo-outline">
              <li>
                <Asset name="globe" />
                <div>
                  <strong>
                    {startMode === "live"
                      ? "The writer leaves a draft"
                      : "Public research continues"}
                  </strong>
                  <span>
                    {startMode === "live"
                      ? "Its structured claims and rationale stay available for inspection."
                      : "A useful findings note appears on its own schedule."}
                  </span>
                </div>
              </li>
              <li>
                <Asset name="shield-check" />
                <div>
                  <strong>
                    {startMode === "live"
                      ? "The reviewer sees actual work"
                      : "Restricted work waits"}
                  </strong>
                  <span>
                    {startMode === "live"
                      ? "Feedback uses that draft and independently computed source facts."
                      : "SDK guards keep sample data protected."}
                  </span>
                </div>
              </li>
              <li>
                <Asset name="files" />
                <div>
                  <strong>
                    {startMode === "live"
                      ? "A bounded repair can follow"
                      : "You review access"}
                  </strong>
                  <span>
                    {startMode === "live"
                      ? "The writer receives the actual feedback once. A rejected handoff stays visible and is not replaced with an offline result."
                      : "Grant sample access to finish, or deny it and keep the public output."}
                  </span>
                </div>
              </li>
            </ol>
          </section>
          {!!recent.length && (
            <section className="demo-recent">
              <div className="section-heading">
                <h2>Recent walkthroughs</h2>
                <button className="text-link" onClick={() => void recheck()}>
                  Refresh
                </button>
              </div>
              {recent.map((d) => (
                <button
                  className="demo-recent-row"
                  key={d.demo_id}
                  onClick={() => open(d.demo_id)}
                >
                  <span>
                    <strong>
                      {d.execution_mode === "live"
                        ? "Live agent brief"
                        : "Offline analyst brief"}
                    </strong>
                    <small>
                      {new Date(d.created_at_ms).toLocaleDateString("en-GB", {
                        timeZone: "UTC",
                      })}{" "}
                      · {time(d.created_at_ms)} UTC
                    </small>
                  </span>
                  <span>{demoStateLabel(d.state)}</span>
                  <span className="text-link">Open</span>
                </button>
              ))}
            </section>
          )}
        </>
      )}
      {selected && !demo && !error && (
        <div className="loading-state" aria-busy="true">
          Reading the saved walkthrough…
        </div>
      )}
      {demo && (
        <>
          <section className="demo-status">
            <div>
              <span className="eyebrow">
                {demo.worker_connected
                  ? "WORKER CONNECTED"
                  : "SAVED WALKTHROUGH"}
              </span>
              <h2>{demoHeadline(demo)}</h2>
              <div className="demo-progress">
                <progress
                  value={demo.progress.completed}
                  max={Math.max(1, demo.progress.total)}
                  aria-label="Tasks completed"
                />
                <span>
                  {demo.progress.completed} of {demo.progress.total} tasks
                  complete
                </span>
              </div>
              <p className="metadata">
                {demo.progress.waiting} waiting · {demo.active_holds || 0}{" "}
                operator pauses ·{" "}
                {demo.worker_connected
                  ? "Local worker connected"
                  : "No connected demo worker"}
              </p>
              {liveMode && demo.model && (
                <p className="metadata">
                  {demo.model.calls} of {demo.model.call_limit} model calls
                  attempted ·{" "}
                  {demoReviewLabel(demo.model, demoTerminal(demo.state))}
                </p>
              )}
            </div>
            <div className="demo-status-actions">
              {demo.permission === "pending" && !demoTerminal(demo.state) && (
                <button
                  className="button primary"
                  disabled={
                    !operator ||
                    busy ||
                    Boolean(decisionIntent) ||
                    !demo.approval_id ||
                    !demo.worker_connected
                  }
                  onClick={reviewSampleAccess}
                >
                  Review sample access
                </button>
              )}
              {demo.artifacts.some((a) => a.slug === "final-brief") && (
                <button
                  className="button primary"
                  onClick={() => {
                    setArtifact("final-brief");
                    document
                      .getElementById("demo-output-reader")
                      ?.scrollIntoView({ behavior: "smooth", block: "start" });
                  }}
                >
                  Read finished brief
                </button>
              )}
              {demo.run_id && (
                <Link
                  className="button secondary"
                  href={`/runs/${demo.run_id}?tab=graph`}
                >
                  Open workflow map
                </Link>
              )}
              {demo.active_holds > 0 &&
                demo.permission === "approved" &&
                demo.run_id &&
                !demoTerminal(demo.state) && (
                  <Link
                    className="button primary"
                    href={`/runs/${demo.run_id}?tab=commands`}
                  >
                    Review pauses to continue
                  </Link>
                )}
              <Link className="text-link" href="/demo">
                All walkthroughs
              </Link>
            </div>
          </section>
          <div className="demo-workspace">
            <div className="demo-main">
              <section className="demo-output-section">
                <div className="section-heading">
                  <h2>Useful outputs</h2>
                  <span className="metadata muted">Created by this run</span>
                </div>
                <div
                  className="demo-output-tabs"
                  role="group"
                  aria-label="Read workflow outputs"
                >
                  {outputs.map((o) => {
                    const exists = demo.artifacts.some(
                      (a) => a.slug === o.slug,
                    );
                    return (
                      <button
                        key={o.slug}
                        className={artifact === o.slug ? "selected" : ""}
                        disabled={!exists}
                        onClick={() => setArtifact(o.slug)}
                      >
                        <Asset name={o.asset} />
                        <span>
                          <strong>{o.title}</strong>
                          <small>
                            {exists ? "Ready to read" : "Not created yet"}
                          </small>
                        </span>
                      </button>
                    );
                  })}
                </div>
                {liveMode && (
                  <details className="demo-evidence">
                    <summary>Agent handoff evidence</summary>
                    <p className="metadata">
                      Inspect the actual draft, feedback and any repair. Model
                      rationale is unverified evidence; publication checks cover
                      the required typed facts.
                    </p>
                    <label htmlFor="demo-agent-output">
                      Read an agent output
                    </label>{" "}
                    <select
                      id="demo-agent-output"
                      value={
                        agentOutputs.some((o) => o.slug === artifact)
                          ? artifact
                          : ""
                      }
                      onChange={(e) => {
                        if (e.target.value) setArtifact(e.target.value);
                      }}
                    >
                      <option value="">Choose handoff evidence</option>
                      {agentOutputs.map((o) => (
                        <option
                          key={o.slug}
                          value={o.slug}
                          disabled={
                            !demo.artifacts.some((a) => a.slug === o.slug)
                          }
                        >
                          {o.title}
                          {demo.artifacts.some((a) => a.slug === o.slug)
                            ? ""
                            : " · not created"}
                        </option>
                      ))}
                    </select>
                  </details>
                )}
                {selectedArtifact ? (
                  <div className="demo-reader" id="demo-output-reader">
                    <div className="demo-reader-heading">
                      <div>
                        <span className="eyebrow">SAVED OUTPUT</span>
                        <h2>{selectedArtifact.title}</h2>
                      </div>
                      <a
                        className="button secondary small"
                        href={`/api/backend/demos/${demo.demo_id}/artifacts/${selectedArtifact.slug}`}
                        download={`${selectedArtifact.slug}.md`}
                      >
                        Download
                      </a>
                    </div>
                    {artifactLoading ? (
                      <p className="loading-state" aria-busy="true">
                        Opening output…
                      </p>
                    ) : artifactError ? (
                      <div className="banner warning" role="status">
                        <p>{artifactError}</p>
                        <button
                          onClick={() => setArtifactRevision((n) => n + 1)}
                        >
                          Retry output
                        </button>
                      </div>
                    ) : (
                      <ArtifactDocument text={text} />
                    )}
                    <details className="demo-evidence">
                      <summary>Output evidence</summary>
                      <p className="metadata">
                        Saved {time(selectedArtifact.created_at_ms)} UTC ·{" "}
                        {selectedArtifact.media_type}
                      </p>
                      <p className="mono break">
                        SHA-256 {selectedArtifact.sha256}
                      </p>
                    </details>
                  </div>
                ) : (
                  <div className="demo-no-output">
                    <Asset name="files" />
                    <h3>The first output will appear here.</h3>
                    <p>
                      Public research runs independently. Dataset analysis waits
                      for the sample permission.
                    </p>
                  </div>
                )}
              </section>
              <section className="demo-activity">
                <h2>What happened</h2>
                <ol>
                  {demo.timeline.map((event, i) => (
                    <li key={`${event.at_ms}:${event.kind}:${i}`}>
                      <time>{time(event.at_ms)} UTC</time>
                      <p>{event.message}</p>
                    </li>
                  ))}
                </ol>
              </section>
            </div>
            <aside className="demo-context">
              {liveMode && demo.model && (
                <section aria-label="Live agent handoffs">
                  <span className="eyebrow">
                    WRITER → REVIEWER → REPAIR IF NEEDED
                  </span>
                  <h2>Every handoff leaves evidence.</h2>
                  <p>{demoReviewLabel(demo.model, demoTerminal(demo.state))}</p>
                  <dl className="demo-observed">
                    <div>
                      <dt>Model calls attempted</dt>
                      <dd>
                        {demo.model.calls} / {demo.model.call_limit}
                      </dd>
                    </div>
                    <div>
                      <dt>Input tokens</dt>
                      <dd>
                        {demo.model.input_tokens === null
                          ? "Not reported"
                          : demo.model.input_tokens}
                      </dd>
                    </div>
                    <div>
                      <dt>Output tokens</dt>
                      <dd>
                        {demo.model.output_tokens === null
                          ? "Not reported"
                          : demo.model.output_tokens}
                      </dd>
                    </div>
                    <div>
                      <dt>Repair used</dt>
                      <dd>
                        {demo.model.repair_used
                          ? "Yes · typed facts checked before publication"
                          : "No"}
                      </dd>
                    </div>
                  </dl>
                  <details className="demo-evidence">
                    <summary>Model provenance and limits</summary>
                    <p className="metadata">
                      Configured model:{" "}
                      {demo.model.configured_model || "Not available"}
                      <br />
                      Provider: {demo.model.provider_host || "Not available"}
                      <br />
                      Provider-reported model:{" "}
                      {demo.model.provider_reported_model || "Not reported"}
                    </p>
                    <p className="metadata">
                      Writer and reviewer are separate roles using the same
                      configured provider; this does not establish model
                      independence or verify the provider's model identity. A
                      repaired draft receives typed fact checks, without a
                      second model review. Token counts are provider-reported
                      and are not a price quote.
                    </p>
                  </details>
                </section>
              )}
              <section>
                <span className="eyebrow">SHARED DEPENDENCY</span>
                <h2>Sample dataset access</h2>
                <Status value={demo.permission} />
                <p>
                  {demo.permission === "pending"
                    ? "Public findings do not need this permission. The restricted branch waits at its SDK checkpoints."
                    : demo.permission === "approved"
                      ? "The mock authority granted access for this walkthrough. An operator pause, if any, still needs an explicit resume."
                      : "The mock authority denied access. Protected work stays blocked; the public findings remain available."}
                </p>
                {demo.permission === "pending" && !demoTerminal(demo.state) && (
                  <button
                    className="button primary"
                    disabled={
                      !operator ||
                      busy ||
                      Boolean(decisionIntent) ||
                      !demo.approval_id ||
                      !demo.worker_connected
                    }
                    onClick={reviewSampleAccess}
                  >
                    Review sample access
                  </button>
                )}
                {decisionIntent && (
                  <div className="demo-pending" role="status">
                    <p>
                      The permission request is unconfirmed. Recheck the
                      original walkthrough before another action.
                    </p>
                    <button
                      className="button secondary"
                      onClick={() => void recheck()}
                    >
                      Recheck permission
                    </button>
                    {decisionIntent.requestSha256 && (
                      <button
                        className="button secondary"
                        disabled={!operator || busy}
                        onClick={() => {
                          const saved = originalDecision.current;
                          setDecision(decisionIntent.decision);
                          setReason(
                            saved?.demoId === demo.demo_id &&
                              saved.key === decisionIntent.key
                              ? JSON.parse(saved.body).reason
                              : "",
                          );
                          setRetryDecision(true);
                          setDecisionError("");
                          setPermissionOpen(true);
                        }}
                      >
                        Review original decision again
                      </button>
                    )}
                    <p className="metadata">
                      {decisionIntent.requestSha256
                        ? "The reason is not stored in your browser. After reloading, enter the original reason to retry the same request."
                        : "This older browser record cannot reconstruct the original decision. Keep rechecking its outcome; if the walkthrough reaches its time limit, start a fresh one."}
                    </p>
                  </div>
                )}
                {demo.active_holds > 0 && demo.run_id && (
                  <p>
                    <Link
                      className="text-link"
                      href={`/runs/${demo.run_id}?tab=commands`}
                    >
                      Review paused tasks and resume explicitly
                    </Link>
                  </p>
                )}
                {demo.active_holds > 0 &&
                  demo.run_id &&
                  !demoTerminal(demo.state) && (
                    <p className="metadata">
                      Review each paused task in Pause history, then return
                      here. Granting sample access alone keeps operator pauses
                      in place.
                    </p>
                  )}
              </section>
              <section>
                <h3>Work observed</h3>
                <dl className="demo-observed">
                  <div>
                    <dt>Public findings</dt>
                    <dd>
                      {demo.public_completed
                        ? "Completed independently"
                        : "In progress"}
                    </dd>
                  </div>
                  <div>
                    <dt>Access requests recorded</dt>
                    <dd>{demo.request_count}</dd>
                  </div>
                  <div>
                    <dt>Protected steps executed</dt>
                    <dd>{demo.protected_effects}</dd>
                  </div>
                </dl>
                <details>
                  <summary>What this demonstrates</summary>
                  <p className="metadata">
                    {liveMode
                      ? "The writer and reviewer exchange actual outputs, with at most one repair. Required typed claims are checked against source data before publication; arbitrary model rationale is not certified. This small fixture case is not a general safety benchmark or a measured cost saving."
                      : "A pending permission is a valid wait. SDK checkpoints keep restricted actions blocked; this walkthrough makes no claim that an extra pause saves requests or model cost. The output records and mock effects are stored separately from control confirmations."}
                  </p>
                </details>
              </section>
              {demoTerminal(demo.state) && (
                <section>
                  <h3>
                    {demo.state === "completed"
                      ? "Try another outcome"
                      : "Start a fresh walkthrough"}
                  </h3>
                  <p>
                    Saved outputs stay available after the local worker has
                    stopped.
                  </p>
                  <Link className="button secondary" href="/demo">
                    Choose another walkthrough
                  </Link>
                </section>
              )}
            </aside>
          </div>
        </>
      )}
      <dialog
        ref={liveDialog}
        className="control-dialog demo-decision"
        aria-labelledby="live-demo-title"
        onCancel={() => setLiveReviewOpen(false)}
        onClose={() => setLiveReviewOpen(false)}
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void start(retryLiveStart, "live");
          }}
        >
          <div className="row-title">
            <div>
              <div className="eyebrow">OPTIONAL LIVE MODEL CALLS</div>
              <h2 id="live-demo-title">
                {retryLiveStart
                  ? "Review the original live start"
                  : "Review live agent work"}
              </h2>
            </div>
            <button
              type="button"
              className="button small"
              onClick={() => setLiveReviewOpen(false)}
            >
              Close
            </button>
          </div>
          <p>
            A writer drafts from sample facts. A separate reviewer reads its
            actual draft; the writer can receive that feedback for one repair.
            This run attempts at most three model calls. Provider charges may
            apply, and no price estimate is available here.
          </p>
          <dl className="demo-observed">
            <div>
              <dt>Configured model</dt>
              <dd>{capabilities?.live.configured_model || "Unavailable"}</dd>
            </div>
            <div>
              <dt>Provider</dt>
              <dd>{capabilities?.live.provider_host || "Unavailable"}</dd>
            </div>
            <div>
              <dt>Call limit</dt>
              <dd>3 total, including a possible repair</dd>
            </div>
          </dl>
          <p>
            Model messages contain only bundled synthetic CSV facts, public
            notes and the agents' own draft/feedback. Operator reasons,
            application credentials and other workspace content are not included
            in model messages. The provider key is used only for HTTPS
            authentication and stays out of the browser and retained evidence.
            Sample access still needs your review before the first model call.
          </p>
          <p>
            Writer and reviewer use the same configured provider. Required typed
            facts are checked against source data before publication; model
            rationale remains unverified evidence. A repair receives fact checks
            without a second model review.
          </p>
          {retryLiveStart && (
            <p className="metadata">
              This retries the original live start using its saved key and exact
              mode. It does not create a replacement walkthrough or increase
              that walkthrough's call limit. Recheck status first if the outcome
              is uncertain.
            </p>
          )}
          {!capabilities?.live.available && (
            <p role="status">
              Live setup is unavailable. You can reconcile an original request;
              starting new live work requires a configured server.
            </p>
          )}
          <div className="demo-review-actions">
            <button
              type="button"
              className="button secondary"
              onClick={() => setLiveReviewOpen(false)}
            >
              Cancel
            </button>
            <button
              className="button primary"
              disabled={
                !operator ||
                busy ||
                (!capabilities?.live.available && !retryLiveStart)
              }
            >
              {retryLiveStart
                ? "Retry original live start"
                : "Start live walkthrough · up to 3 calls"}
            </button>
          </div>
        </form>
      </dialog>
      <dialog
        ref={dialog}
        className="control-dialog demo-decision"
        aria-labelledby="demo-decision-title"
        onCancel={(e) => {
          if (busy) e.preventDefault();
          else setPermissionOpen(false);
        }}
        onClose={() => setPermissionOpen(false)}
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void submitDecision();
          }}
        >
          <div className="row-title">
            <div>
              <div className="eyebrow">LOCAL DEMO ONLY</div>
              <h2 id="demo-decision-title">
                {retryDecision
                  ? "Review the original decision"
                  : "Review sample access"}
              </h2>
            </div>
            <button
              type="button"
              className="button small"
              disabled={busy}
              onClick={() => setPermissionOpen(false)}
            >
              Close
            </button>
          </div>
          <p>
            This decision applies only to this walkthrough’s mock dataset.
            Connected production approvals are not changed.
          </p>
          {retryDecision && (
            <p className="metadata">
              This retries the original decision using its saved request key and
              exact reason. Recheck permission first if you are unsure whether
              it already completed.
            </p>
          )}
          {decisionError && (
            <p className="banner warning" role="alert">
              {decisionError}
            </p>
          )}
          <fieldset disabled={busy || retryDecision}>
            <legend>Decision</legend>
            <label>
              <input
                type="radio"
                name="demo-decision"
                checked={decision === "approved"}
                onChange={() => setDecision("approved")}
              />{" "}
              Grant access to sample data
            </label>
            <label>
              <input
                type="radio"
                name="demo-decision"
                checked={decision === "denied"}
                onChange={() => setDecision("denied")}
              />{" "}
              Deny access; keep only public findings
            </label>
          </fieldset>
          <label htmlFor="demo-reason">Reason, saved with this decision</label>
          <textarea
            id="demo-reason"
            maxLength={500}
            required
            value={reason}
            disabled={busy}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Explain your decision for this local walkthrough."
          />
          <p className="metadata muted">
            Granting access does not clear an operator pause. Those tasks
            require a separately reviewed resume.
          </p>
          <div className="demo-review-actions">
            <button
              className="button secondary"
              type="button"
              disabled={busy}
              onClick={() => setPermissionOpen(false)}
            >
              Cancel
            </button>
            <button
              className="button primary"
              disabled={
                !operator ||
                busy ||
                !reason.trim() ||
                (Boolean(decisionIntent) && !retryDecision)
              }
            >
              {busy
                ? "Saving decision…"
                : retryDecision
                  ? "Retry original decision"
                  : decision === "approved"
                    ? "Grant demo access"
                    : "Deny demo access"}
            </button>
          </div>
        </form>
      </dialog>
    </div>
  );
}
