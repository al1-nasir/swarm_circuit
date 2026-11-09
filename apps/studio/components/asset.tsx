import type { GraphNode } from "@/lib/types";

export function taskAsset(node: Pick<GraphNode, "node_kind" | "label">) {
  if (node.node_kind === "agent") return "robot";
  const name = node.label.toLowerCase();
  if (/approv|access|permission|gate/.test(name)) return "shield-check";
  if (/valid|check|verify/.test(name)) return "seal-check";
  if (/report|write|draft|document/.test(name)) return "files";
  if (/public|independent|web/.test(name)) return "globe";
  if (/data|research|collect/.test(name)) return "database";
  if (/plan|study|strateg/.test(name)) return "strategy";
  return "flow-arrow";
}

export function Asset({
  name,
  className = "",
  alt = "",
}: {
  name: string;
  className?: string;
  alt?: string;
}) {
  return (
    <img
      className={`asset ${className}`}
      src={`/assets/tasks/${name}.svg`}
      width={32}
      height={32}
      alt={alt}
      draggable={false}
    />
  );
}

export function IntegrationAssets() {
  return (
    <div
      className="integration-assets"
      aria-label="Python SDK, OpenTelemetry and SQLite"
    >
      {[
        ["python", "Python SDK"],
        ["opentelemetry", "OpenTelemetry"],
        ["sqlite", "SQLite"],
      ].map(([name, label]) => (
        <span key={name}>
          <img
            src={`/assets/integrations/${name}.svg`}
            width={20}
            height={20}
            alt=""
          />
          {label}
        </span>
      ))}
    </div>
  );
}
