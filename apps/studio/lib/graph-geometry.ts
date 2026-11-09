import type { GraphEdge } from "./types.ts";
export const NODE_WIDTH = 208;
export const NODE_HEIGHT = 128;
export type Point = { x: number; y: number };
export type LayoutResult = {
  nodes: { id: string; position: Point }[];
  routes: Record<string, Point[]>;
};
export function flowDirection(edge: GraphEdge) {
  return edge.relation_kind === "depends_on"
    ? { source: edge.target, target: edge.source }
    : { source: edge.source, target: edge.target };
}
export function roundedPath(points: Point[], radius = 8) {
  if (points.length < 2) return "";
  let d = `M ${points[0].x} ${points[0].y}`;
  for (let i = 1; i < points.length - 1; i++) {
    const prev = points[i - 1],
      p = points[i],
      next = points[i + 1];
    const a = Math.hypot(p.x - prev.x, p.y - prev.y),
      b = Math.hypot(next.x - p.x, next.y - p.y);
    const r = Math.min(radius, a / 2, b / 2);
    if (!a || !b) continue;
    d += ` L ${p.x + ((prev.x - p.x) * r) / a} ${p.y + ((prev.y - p.y) * r) / a} Q ${p.x} ${p.y} ${p.x + ((next.x - p.x) * r) / b} ${p.y + ((next.y - p.y) * r) / b}`;
  }
  const end = points.at(-1)!;
  return d + ` L ${end.x} ${end.y}`;
}
