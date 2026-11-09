import type {
  Command,
  Evidence,
  Graph,
  GraphNode,
  Page,
  Runtime,
} from "./types.ts";

export function short(id?: string) {
  return id ? id.slice(0, 8) : "—";
}
export function words(value: string) {
  return value.replaceAll("_", " ");
}
export function time(value?: number | null) {
  return value == null
    ? "—"
    : new Intl.DateTimeFormat("en-GB", {
        timeZone: "UTC",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }).format(value);
}
export function duration(ms: number) {
  return ms < 1000
    ? `${Math.round(ms)} ms`
    : ms < 60000
      ? `${(ms / 1000).toFixed(1)} s`
      : `${(ms / 60000).toFixed(1)} min`;
}
export function spanDuration(item: Evidence) {
  if (!item.start_unix_ns || !item.end_unix_ns) return null;
  return (
    Number(BigInt(item.end_unix_ns) - BigInt(item.start_unix_ns)) / 1_000_000
  );
}
export function closure(graph: Graph, selected: string) {
  const seen = new Set([selected]);
  const pending = [selected];
  while (pending.length) {
    const current = pending.pop();
    for (const edge of graph.edges)
      if (
        edge.evidence_kind === "explicit" &&
        edge.target === current &&
        !seen.has(edge.source)
      ) {
        seen.add(edge.source);
        pending.push(edge.source);
      }
  }
  return seen;
}
export function layout(graph: Graph) {
  const levels = new Map(graph.nodes.map((n) => [n.id, 0]));
  // Bounded relaxation preserves cycles as a visible cluster; never invents a dependency.
  for (let i = 0; i < Math.min(graph.nodes.length, 8); i++) {
    let changed = false;
    for (const edge of graph.edges) {
      const candidate = Math.min(7, (levels.get(edge.target) || 0) + 1);
      if (candidate > (levels.get(edge.source) || 0)) {
        levels.set(edge.source, candidate);
        changed = true;
      }
    }
    if (!changed) break;
  }
  const counts = new Map<number, number>();
  for (const level of levels.values())
    counts.set(level, (counts.get(level) || 0) + 1);
  const offsets = [0];
  for (let group = 0; group < 3; group++) {
    const depth = Math.max(
      1,
      ...[0, 1, 2].map((column) => counts.get(group * 3 + column) || 0),
    );
    offsets.push(offsets[group] + depth * 138 + 80);
  }
  const rows = new Map<number, number>();
  return [...graph.nodes]
    .sort((a, b) => a.id.localeCompare(b.id))
    .map((node) => {
      const level = levels.get(node.id) || 0;
      const row = rows.get(level) || 0;
      rows.set(level, row + 1);
      return {
        id: node.id,
        position: {
          x: (level % 3) * 288,
          y: offsets[Math.floor(level / 3)] + row * 138 + (level % 2) * 38,
        },
      };
    });
}
export function displayedState(node: GraphNode, runtimes: Runtime[]) {
  if (node.state === "held") {
    const runtime = runtimes.find((s) =>
      s.checkpoints.some(
        (p) => p.task_id === node.id && p.state !== "released",
      ),
    );
    if (
      !runtime ||
      runtime.state !== "connected" ||
      runtime.checkpoints.some(
        (p) => p.task_id === node.id && p.state === "unknown",
      )
    )
      return "pause state unconfirmed";
  }
  return node.state ? words(node.state) : "agent";
}
export function confirmed(command: Command) {
  return (
    command.state === "applied" &&
    command.acknowledgements.some(
      (a) =>
        a.result === "applied" &&
        a.runtime_session_id === command.runtime_session_id &&
        a.session_fencing_epoch === command.session_fencing_epoch,
    )
  );
}
export function commandLabel(command: Command) {
  if (command.state === "applied")
    return confirmed(command)
      ? command.command_kind === "hold_task"
        ? "Pause confirmed by host"
        : "Resume confirmed by host"
      : "Applied record · host confirmation missing";
  return command.state === "queued"
    ? "Queued · awaiting host confirmation"
    : words(command.state);
}
export function mergeById<T>(
  current: T[],
  incoming: T[],
  key: (value: T) => string,
) {
  const items = new Map(current.map((item) => [key(item), item]));
  for (const item of incoming) items.set(key(item), item);
  return [...items.values()];
}
export function mergePage<T>(
  current: Page<T>,
  incoming: Page<T>,
  key: (value: T) => string,
): Page<T> {
  const known = new Set(current.items.map(key));
  const overlaps = incoming.items.some((item) => known.has(key(item)));
  return {
    items: mergeById(current.items, incoming.items, key),
    next_cursor: overlaps ? current.next_cursor : incoming.next_cursor,
  };
}
