"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { short } from "@/lib/model";
import { useProject } from "./shell";
import { CopyButton, Empty, Status } from "./ui";

type Plan = {
  experiment_id: string;
  title: string;
  protocol_version: string;
  protocol_sha256: string;
  specification: {
    source_kind: string;
    implementation_sha: string;
    preparation_date: string;
    evidence_scope: string;
    protocol: {
      arms: string[];
      scenarios: string[];
      seeds: number[];
      horizon_ticks: number;
      work_weights: number[];
    };
  };
};
type Estimate = {
  scenario: string;
  arm: string;
  metric: string;
  n: number;
  mean: number | null;
  low: number | null;
  high: number | null;
  reference?: string;
};
type Results = {
  experiment: Plan;
  expected_trials: number;
  completed: number;
  failed: number;
  missing: number;
  failures: { trial_id: string; failure_code: string }[];
  arms: Record<string, string>;
  scenarios: Record<string, string>;
  metrics: Record<string, { unit: string; higher_is_better: boolean }>;
  estimates: Estimate[];
  contrasts: Estimate[];
  uncertainty: string;
  contrast_direction: string;
};
type Trial = {
  trial_id: string;
  run_id: string;
  scenario_key: string;
  policy_arm: string;
  seed: number;
  state: string;
  source_kind: string;
  input_sha256: string;
  artifact_sha256: string;
  failure_code?: string;
  model_config: { model: string; calls: number; limitation: string };
};
const format = (value: number | null) =>
  value === null
    ? "—"
    : new Intl.NumberFormat("en", { maximumFractionDigits: 2 }).format(value);
const interval = (r: Estimate) =>
  r.low === null || r.high === null
    ? "Unavailable (n < 2)"
    : `${format(r.low)} to ${format(r.high)}`;

export function Experiments({ experimentId }: { experimentId?: string }) {
  const { config } = useProject();
  const router = useRouter();
  const [plans, setPlans] = useState<Plan[]>([]);
  const [data, setData] = useState<Results | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  const [tab, setTab] = useState("comparison");
  const [scenario, setScenario] = useState("");
  const [metric, setMetric] = useState("coordination_requests");
  const [rows, setRows] = useState<Trial[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [arm, setArm] = useState("");
  const [listError, setListError] = useState("");
  const listGeneration = useRef(0);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [enteredId, setEnteredId] = useState("");
  const selected = experimentId || "";
  useEffect(() => {
    if (!config) return;
    const control = new AbortController();
    api<{ items: Plan[] }>(
      `projects/${config.projectId}/experiments?limit=25`,
      { signal: control.signal },
    )
      .then((r) => setPlans(r.items))
      .catch((e) => {
        if (!control.signal.aborted) setError(e.message);
      });
    return () => control.abort();
  }, [config?.projectId, revision]);
  useEffect(() => {
    setData(null);
    setScenario("");
    setRows([]);
    setError("");
  }, [selected]);
  useEffect(() => {
    if (!selected || !config) return;
    const control = new AbortController();
    setLoading(true);
    setError("");
    api<Results>(`experiments/${selected}/results`, { signal: control.signal })
      .then((r) => {
        setData(r);
        setScenario((old) =>
          r.experiment.specification.protocol.scenarios.includes(old)
            ? old
            : r.experiment.specification.protocol.scenarios[0],
        );
      })
      .catch((e) => {
        if (!control.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!control.signal.aborted) setLoading(false);
      });
    return () => control.abort();
  }, [selected, config?.projectId, revision]);
  useEffect(() => {
    if (!data?.missing) return;
    const timer = setInterval(() => setRevision((n) => n + 1), 10000);
    return () => clearInterval(timer);
  }, [data?.missing]);
  useEffect(() => {
    const generation = ++listGeneration.current;
    setLoadingOlder(false);
    if (!selected || !scenario) return;
    const control = new AbortController();
    setListError("");
    setRows([]);
    const query = new URLSearchParams({
      limit: "100",
      scenario,
      ...(arm ? { arm } : {}),
    });
    api<{ items: Trial[]; next_cursor?: string }>(
      `experiments/${selected}/trials?${query}`,
      { signal: control.signal },
    )
      .then((r) => {
        if (generation !== listGeneration.current) return;
        setRows(r.items);
        setCursor(r.next_cursor || null);
      })
      .catch((e) => {
        if (!control.signal.aborted) setListError(e.message);
      });
    return () => control.abort();
  }, [selected, scenario, arm, revision]);
  async function older() {
    if (!cursor || loadingOlder) return;
    const generation = listGeneration.current;
    setLoadingOlder(true);
    setListError("");
    try {
      const q = new URLSearchParams({
        limit: "100",
        scenario,
        ...(arm ? { arm } : {}),
        cursor: cursor!,
      });
      const r = await api<{ items: Trial[]; next_cursor?: string }>(
        `experiments/${selected}/trials?${q}`,
      );
      if (generation !== listGeneration.current) return;
      setRows((old) => [
        ...old,
        ...r.items.filter((t) => !old.some((o) => o.trial_id === t.trial_id)),
      ]);
      setCursor(r.next_cursor || null);
    } catch (e) {
      if (generation === listGeneration.current)
        setListError(
          e instanceof Error ? e.message : "Older trials unavailable",
        );
    } finally {
      if (generation === listGeneration.current) setLoadingOlder(false);
    }
  }
  const p = data?.experiment.specification.protocol;
  const estimates = (data?.estimates || []).filter(
    (r) => r.scenario === scenario && r.metric === metric,
  );
  const contrasts = (data?.contrasts || []).filter(
    (r) => r.scenario === scenario && r.metric === metric,
  );
  const requestResult = (arm: string) =>
    data?.estimates.find(
      (r) =>
        r.scenario === scenario &&
        r.metric === "coordination_requests" &&
        r.arm === arm,
    )?.mean;
  const insight =
    requestResult("B3") !== undefined &&
    requestResult("B4") !== undefined &&
    requestResult("A_ready_queue") !== undefined
      ? `In this scenario, ignoring identical repeats recorded ${format(requestResult("B3") ?? null)} requests, branch backpressure ${format(requestResult("B4") ?? null)}, and waiting until prerequisites were ready ${format(requestResult("A_ready_queue") ?? null)}. Check completion as well as request counts before choosing a strategy.`
      : "Completed measurements are needed to compare these strategies. Failed trials are not replaced with successful-looking numbers.";
  const upper = Math.max(1, ...estimates.map((r) => r.high ?? r.mean ?? 0));
  function downloadManifest() {
    if (!data) return;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(data.experiment, null, 2)], {
        type: "application/json",
      }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = `experiment-${selected}-protocol.json`;
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <div className="page-content research-page">
      <div className="page-heading">
        <div>
          <div className="eyebrow">RECORDED EVALUATION</div>
          <h1>Comparisons</h1>
          <p>Compare requests, completed work and failures in recorded runs.</p>
        </div>
        <button
          className="button secondary"
          onClick={() => setRevision((n) => n + 1)}
          disabled={loading}
        >
          {loading ? "Refreshing…" : "Refresh results"}
        </button>
      </div>
      <div className="research-selector panel">
        <label>
          Recorded experiments
          <select
            aria-label="Recorded experiment"
            value={selected}
            onChange={(e) =>
              e.target.value && router.push(`/experiments/${e.target.value}`)
            }
          >
            <option value="">Choose a recorded experiment</option>
            {selected && !plans.some((p) => p.experiment_id === selected) && (
              <option value={selected}>{short(selected)}</option>
            )}
            {plans.map((p) => (
              <option key={p.experiment_id} value={p.experiment_id}>
                {p.title} · {short(p.experiment_id)}
              </option>
            ))}
          </select>
        </label>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (/^[0-9a-f-]{36}$/i.test(enteredId))
              router.push(`/experiments/${enteredId}`);
            else setError("Enter a valid experiment UUID.");
          }}
        >
          <label>
            Open by ID
            <input
              aria-label="Experiment ID"
              placeholder="Experiment UUID"
              value={enteredId}
              onChange={(e) => setEnteredId(e.target.value)}
            />
          </label>
          <button className="button secondary">Open</button>
        </form>
      </div>
      {error && (
        <div role="status" className="banner danger">
          {error}{" "}
          <button onClick={() => setRevision((n) => n + 1)}>Retry</button>
        </div>
      )}
      {!selected && (
        <section className="panel">
          <Empty
            title={
              plans.length
                ? "Choose an experiment to inspect"
                : "No recorded experiments"
            }
          >
            <p>
              Run the local CLI to record reproducible trials. The dashboard
              never launches paid model calls.
            </p>
            <code className="research-command">make research</code>
          </Empty>
        </section>
      )}
      {selected && !data && !error && (
        <div className="loading-state">Loading stored experiment evidence…</div>
      )}
      {data && p && (
        <>
          <section className="panel research-summary">
            <div>
              <div className="eyebrow">
                {data.experiment.specification.source_kind === "synthetic"
                  ? "SIMULATED ACTORS & EFFECTS"
                  : "LIVE LLM WORKLOAD · SIMULATED EFFECTS"}
              </div>
              <h2>{data.experiment.title}</h2>
              <p>
                {data.completed} completed · {data.failed} failed ·{" "}
                {data.missing} missing of {data.expected_trials} planned trials
              </p>
              <span className="metadata muted">
                {p.seeds.length} seed{p.seeds.length === 1 ? "" : "s"} ·{" "}
                {p.scenarios.length} scenarios · {p.arms.length} policy arms ·{" "}
                {p.horizon_ticks} logical ticks
              </span>
            </div>
            <div className="research-exports">
              <a
                className={`button primary ${data.completed + data.failed ? "" : "disabled-link"}`}
                aria-disabled={!data.completed && !data.failed}
                href={
                  data.completed + data.failed
                    ? `/api/backend/experiments/${selected}/export.csv`
                    : undefined
                }
              >
                Export trial CSV
              </a>
              <button className="button secondary" onClick={downloadManifest}>
                Protocol & provenance
              </button>
            </div>
          </section>
          <p className="research-scope">
            Pre-sprint preparation ·{" "}
            {data.experiment.specification.preparation_date}.{" "}
            {data.experiment.specification.evidence_scope}
          </p>
          {(data.failed > 0 || data.missing > 0) && (
            <div className="banner warning" role="status">
              This experiment is incomplete. Failed and missing trials are
              reported separately and are not filled with zero-valued outcomes.
            </div>
          )}
          <nav className="workspace-tabs" aria-label="Experiment views">
            {["comparison", "trials", "protocol"].map((t) => (
              <button
                key={t}
                aria-current={tab === t ? "page" : undefined}
                className={tab === t ? "active" : ""}
                onClick={() => setTab(t)}
              >
                {t[0].toUpperCase() + t.slice(1)}
              </button>
            ))}
          </nav>
          {tab !== "protocol" && (
            <div className="research-filters">
              <label>
                Scenario
                <select
                  aria-label="Research scenario"
                  value={scenario}
                  onChange={(e) => setScenario(e.target.value)}
                >
                  {p.scenarios.map((s) => (
                    <option key={s} value={s}>
                      {data.scenarios[s]}
                    </option>
                  ))}
                </select>
              </label>
              {tab === "comparison" ? (
                <label>
                  Measurement
                  <select
                    aria-label="Research measurement"
                    value={metric}
                    onChange={(e) => setMetric(e.target.value)}
                  >
                    {Object.keys(data.metrics).map((m) => (
                      <option key={m} value={m}>
                        {m.replaceAll("_", " ")}
                      </option>
                    ))}
                  </select>
                </label>
              ) : (
                <label>
                  Policy arm
                  <select
                    aria-label="Trial policy arm"
                    value={arm}
                    onChange={(e) => setArm(e.target.value)}
                  >
                    <option value="">All recorded arms</option>
                    {p.arms.map((a) => (
                      <option key={a} value={a}>
                        {a} · {data.arms[a]}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </div>
          )}
          {tab === "comparison" && (
            <>
              <section className="comparison-explanation">
                <h2>What the numbers say</h2>
                <p>{insight}</p>
                <p className="metadata muted">
                  These are recorded simulation outcomes, not measured model
                  bills or proof of production safety. Eligible completion
                  excludes goals that remain unauthorized; it is not total
                  workflow progress.
                </p>
              </section>
              <section className="panel">
                <div className="panel-title">
                  <h2>{metric.replaceAll("_", " ")}</h2>
                  <span className="metadata muted">
                    {data.metrics[metric]?.unit} ·{" "}
                    {data.metrics[metric]?.higher_is_better
                      ? "higher"
                      : "lower"}{" "}
                    is better
                  </span>
                </div>
                {!estimates.length ? (
                  <Empty title="No completed measurements for this scenario">
                    <p>Inspect trial outcomes before drawing a conclusion.</p>
                  </Empty>
                ) : (
                  <div className="research-estimates">
                    {p.arms.map((a) => {
                      const r = estimates.find((v) => v.arm === a);
                      return (
                        <div className="research-estimate" key={a}>
                          <div>
                            <strong>{a}</strong>
                            <span>{data.arms[a]}</span>
                          </div>
                          <meter
                            aria-label={`${a} mean ${metric}`}
                            min={0}
                            max={upper}
                            value={r?.mean ?? 0}
                          />
                          <div>
                            <strong>{format(r?.mean ?? null)}</strong>
                            <small>
                              {r
                                ? `95% CI: ${interval(r)} · n=${r.n}`
                                : "No completed trials"}
                            </small>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </section>
              <section className="panel research-contrasts">
                <div className="panel-title">
                  <h2>Difference from ignoring repeated requests</h2>
                  <span className="metadata muted">
                    Exact-key deduplication reference
                  </span>
                </div>
                <div className="table-scroll">
                  <table className="payment-table">
                    <thead>
                      <tr>
                        <th>Policy arm</th>
                        <th>Mean difference</th>
                        <th>95% interval</th>
                        <th>Matched seeds</th>
                      </tr>
                    </thead>
                    <tbody>
                      {contrasts.map((r) => (
                        <tr key={r.arm}>
                          <td>
                            {r.arm} · {data.arms[r.arm]}
                          </td>
                          <td className="mono">{format(r.mean)}</td>
                          <td className="mono">{interval(r)}</td>
                          <td>{r.n}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="table-footer">
                  <span>{data.contrast_direction}</span>
                </div>
              </section>
              <p className="research-scope">
                {data.uncertainty} These intervals describe the recorded
                workload distribution, not real-world deployment risk. An
                ordinary ready queue is included as a strong comparison; no
                universal winner is assumed.
              </p>
            </>
          )}
          {tab === "trials" && (
            <section className="panel">
              <div className="panel-title">
                <h2>
                  Trial evidence{" "}
                  <span className="count">{rows.length} loaded</span>
                </h2>
                <span className="muted metadata">
                  Scenario and policy filters apply to stored trials
                </span>
              </div>
              {listError && <div className="banner danger">{listError}</div>}
              <div className="table-scroll">
                <table className="payment-table">
                  <thead>
                    <tr>
                      <th>Seed / policy</th>
                      <th>Outcome</th>
                      <th>Workflow</th>
                      <th>Raw evidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((t) => (
                      <tr key={t.trial_id}>
                        <td>
                          <strong>
                            Seed {t.seed} · {t.policy_arm}
                          </strong>
                          <small className="mono">
                            {short(t.trial_id)} · {short(t.artifact_sha256)}
                          </small>
                        </td>
                        <td>
                          <Status value={t.state} />
                          {t.failure_code && <small>{t.failure_code}</small>}
                        </td>
                        <td>
                          <Link
                            className="text-link"
                            href={`/runs/${t.run_id}`}
                          >
                            Inspect run
                          </Link>
                        </td>
                        <td>
                          <div className="trial-downloads">
                            <a
                              className="text-link"
                              href={`/api/backend/experiments/${selected}/trials/${t.trial_id}/truth.jsonl`}
                            >
                              Outcome JSONL
                            </a>
                            <a
                              className="text-link"
                              href={`/api/backend/experiments/${selected}/trials/${t.trial_id}/observations.jsonl`}
                            >
                              Observed JSONL
                            </a>
                            {t.source_kind === "llm_workload_replay" && (
                              <a
                                className="text-link"
                                href={`/api/backend/experiments/${selected}/trials/${t.trial_id}/proposals.json`}
                              >
                                Model proposals
                              </a>
                            )}
                          </div>
                          <details>
                            <summary className="muted metadata">
                              Provenance
                            </summary>
                            <p className="mono break metadata">
                              Input {t.input_sha256}
                              <br />
                              Artifact {t.artifact_sha256}
                            </p>
                            <p className="metadata">
                              {t.model_config.model || "No model"} ·{" "}
                              {t.model_config.calls || 0} model calls in shared
                              workload. {t.model_config.limitation}
                            </p>
                          </details>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {!rows.length && !listError && (
                <Empty title="No recorded trials match this selection" />
              )}
              <div className="table-footer">
                <span>
                  Failed trials retain their failure code. Simulated workflow
                  projections do not represent live runtime ACKs.
                </span>
                {cursor && (
                  <button
                    className="button small"
                    disabled={loadingOlder}
                    onClick={() => void older()}
                  >
                    {loadingOlder ? "Loading trials…" : "Load older trials"}
                  </button>
                )}
              </div>
            </section>
          )}
          {tab === "protocol" && (
            <section className="panel research-protocol">
              <h2>Sealed protocol</h2>
              <dl>
                <div className="key-value">
                  <dt>Experiment</dt>
                  <dd className="mono break">
                    {selected}
                    <CopyButton value={selected} />
                  </dd>
                </div>
                <div className="key-value">
                  <dt>Protocol</dt>
                  <dd>{data.experiment.protocol_version}</dd>
                </div>
                <div className="key-value">
                  <dt>Protocol SHA-256</dt>
                  <dd className="mono break">
                    {data.experiment.protocol_sha256}
                  </dd>
                </div>
                <div className="key-value">
                  <dt>Source SHA-256</dt>
                  <dd className="mono break">
                    {data.experiment.specification.implementation_sha}
                  </dd>
                </div>
              </dl>
              <p>
                Source fingerprints are not Git commit IDs. Every policy uses
                the same exogenous world and safety guards. Outcome metrics are
                reduced from the tool/host journal rather than detector success
                labels.
              </p>
              <h3>Workload and limits</h3>
              <p>
                Modelled work weights are {p.work_weights.join(" / ")} for actor
                requests, guard checks and delivered notifications. They are
                declared accounting units, not measured dollars or production
                runtime. Incomplete independent work is assigned the fixed
                horizon in the latency metric and also has a separate completion
                indicator.
              </p>
              <p>
                LLM workload replays hold recorded proposals fixed across policy
                arms. They do not establish how a model would adapt to different
                counterfactual feedback. One-seed trials have no confidence
                interval.
              </p>
              <pre className="code-block">{JSON.stringify(p, null, 2)}</pre>
            </section>
          )}
        </>
      )}
    </div>
  );
}
