"use client";
import {
  Check,
  CheckCheck,
  Circle,
  Copy,
  HelpCircle,
  Pause,
  TriangleAlert,
} from "lucide-react";
import { useState } from "react";
import { words } from "@/lib/model";
import { Asset } from "./asset";

export function Status({
  value,
  children,
}: {
  value: string;
  children?: React.ReactNode;
}) {
  const key = value.toLowerCase();
  const tone = /unknown|unverified|disconnected|expired/.test(key)
    ? "muted"
    : /held/.test(key)
      ? "held"
      : /fail|critical|deny|denied/.test(key)
        ? "danger"
        : /waiting|pending|ask|warning|queued|dispatched/.test(key)
          ? "waiting"
          : /completed|ready|connected|settled|approved|applied/.test(key)
            ? "good"
            : "neutral";
  const Icon = /unknown|unverified/.test(key)
    ? HelpCircle
    : /held/.test(key)
      ? Pause
      : /completed|applied|approved/.test(key)
        ? CheckCheck
        : /fail|critical/.test(key)
          ? TriangleAlert
          : Circle;
  return (
    <span className={`status status-${tone}`}>
      <Icon size={12} />
      {children || words(value)}
    </span>
  );
}
export function Trust({ value }: { value: string }) {
  const label =
    value === "simulation_truth" || value === "simulator_truth"
      ? "Simulation receipt"
      : value === "service_receipt"
        ? "Service receipt"
        : value === "derived"
          ? "Derived evidence"
          : value === "sdk_observation"
            ? "SDK-observed"
            : value === "runtime"
              ? "Runtime ACK"
              : "Telemetry · reported";
  return (
    <span className={`trust ${value.includes("simulat") ? "trust-sim" : ""}`}>
      {label}
    </span>
  );
}
export function CopyButton({
  value,
  label = "Copy ID",
}: {
  value: string;
  label?: string;
}) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="icon-button"
      aria-label={copied ? "Copied" : label}
      title={label}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setCopied(true);
          setTimeout(() => setCopied(false), 1600);
        } catch {
          setCopied(false);
        }
      }}
    >
      {copied ? <Check size={14} /> : <Copy size={14} />}
    </button>
  );
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">
        <Asset name="stack" />
      </div>
      <h3>{title}</h3>
      <div>{children}</div>
    </div>
  );
}
export function KeyValue({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="key-value">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}
