"use client";
import { IntegrationAssets } from "./asset";
import Link from "next/link";
import {
  ArrowRight,
  CheckCheck,
  Code2,
  Database,
  Download,
  FlaskConical,
  Plug,
  Radio,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { short } from "@/lib/model";
import { useProject } from "./shell";
import { CopyButton, Empty, KeyValue, Status } from "./ui";

const observe = `import os\nfrom swarmcircuit import SwarmCircuit\n\nwith SwarmCircuit(\n    os.environ["SWARM_PROJECT_ID"],\n    os.environ["SWARM_SDK_PROJECT_TOKEN"],\n) as sc:\n    with sc.run("research") as run:\n        with run.task("collect", agent="researcher"):\n            pass  # Run your own host action here.\n`;
const control = `with sc.run("controlled-research", mode="control") as run:\n    task = run.task("public read", agent="researcher")\n    with run.runtime("my-host") as runtime:\n        with task:\n            runtime.checkpoint(\n                task, action="before_public_read", timeout=60\n            )\n            # Reversible host action after checkpoint release.\n`;
export function Support({ kind }: { kind: string }) {
  const { config, health, error, refresh } = useProject();
  const [mode, setMode] = useState("observe");
  const [schema, setSchema] = useState("—");
  useEffect(() => {
    api<{ schema_version: string }>("health")
      .then((data) => setSchema(data.schema_version))
      .catch(() => setSchema("unavailable"));
  }, [health]);
  return (
    <div className="page-content">
      <div className="page-heading">
        <div>
          <div className="eyebrow">
            {kind === "setup"
              ? "CONNECT YOUR WORKFLOW"
              : "LOCAL CONNECTION DIAGNOSTICS"}
          </div>
          <h1>
            {kind === "setup" ? "Start with visibility." : "Integrations"}
          </h1>
          <p>
            A framework-neutral SDK. OpenTelemetry for timing. Explicit
            checkpoints for control.
          </p>
        </div>
        <button className="button secondary" onClick={refresh}>
          <Radio size={15} />
          Check connection
        </button>
      </div>
      {error && <div className="banner warning">{error}</div>}
      <IntegrationAssets />
      <div className="setup-grid">
        <section className="panel">
          <div className="panel-title">
            <h2>
              <Plug size={17} />
              Backend connection
            </h2>
            <Status value={health} />
          </div>
          <div className="support-content">
            <dl>
              <KeyValue label="Project">
                <span className="mono">
                  {short(config?.projectId)}
                  {config && <CopyButton value={config.projectId} />}
                </span>
              </KeyValue>
              <KeyValue label="Schema">
                <span className="mono">{schema}</span>
              </KeyValue>
              <KeyValue label="Studio role">
                {config?.operator ? "Local operator" : "Read only"}
              </KeyValue>
              <KeyValue label="Credentials">Server-side only</KeyValue>
              <KeyValue label="OTLP endpoint">
                <span className="mono break">
                  {config?.backend || "http://127.0.0.1:8000"}/v1/traces
                </span>
              </KeyValue>
            </dl>
            <div className="banner info">
              <ShieldCheck size={17} />
              <span>
                Keys stay on the Studio server. Snippets reference environment
                variables and contain no credentials.
              </span>
            </div>
            <h3>Run locally</h3>
            <pre className="code-block">
              make init-local{"\n"}make server{"\n"}# Another terminal:{"\n"}
              make demo SEED=7
            </pre>
            <p className="muted metadata">
              If the backend uses another port, set SWARM_API_URL when starting
              Studio.
            </p>
          </div>
        </section>
        <section className="panel">
          <div className="panel-title">
            <h2>
              <Code2 size={17} />
              Python SDK setup
            </h2>
            <CopyButton
              value={mode === "observe" ? observe : control}
              label="Copy SDK example"
            />
          </div>
          <div className="support-content">
            <div className="segmented">
              <button
                className={mode === "observe" ? "active" : ""}
                onClick={() => setMode("observe")}
              >
                Observe mode
              </button>
              <button
                className={mode === "control" ? "active" : ""}
                onClick={() => setMode("control")}
              >
                Control checkpoints
              </button>
            </div>
            <pre className="code-block">
              {mode === "observe" ? observe : control}
            </pre>
            <p className="muted">
              {mode === "observe"
                ? "Contexts emit host observations. Trace ancestry does not create blocking task dependencies."
                : "Create sc with the Observe example first. Never continue protected work after ControlError. Checkpoints cannot interrupt in-flight or irreversible effects."}
            </p>
          </div>
        </section>
      </div>
      <div className="support-bottom-grid">
        <section className="panel support-note">
          <ShieldCheck size={21} />
          <h3>Privacy by default</h3>
          <p>
            SDK traces use metadata. The live walkthrough intentionally retains
            sample-data drafts, reviews and checks. Provider credentials stay on
            the server.
          </p>
        </section>
        <section className="panel support-note">
          <Database size={21} />
          <h3>Local, explicit evidence</h3>
          <p>
            SDK observations, telemetry, derived findings, runtime ACKs and
            simulation receipts keep distinct provenance labels.
          </p>
        </section>
        <section className="panel support-note">
          <Plug size={21} />
          <h3>Optional integrations</h3>
          <p>
            GateKeep402 observations are optional. Langfuse export is not
            configured and is not required by the control path.
          </p>
        </section>
      </div>
    </div>
  );
}
