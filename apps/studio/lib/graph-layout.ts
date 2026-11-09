import ELK, { type ElkNode } from "elkjs/lib/elk.bundled.js";
import type { Graph } from "./types.ts";

import {
  NODE_WIDTH,
  NODE_HEIGHT,
  flowDirection,
  type LayoutResult,
} from "./graph-geometry.ts";
export async function arrangeGraph(graph: Graph): Promise<LayoutResult> {
  const nodes = graph.nodes.slice(0, 200);
  const ids = new Set(nodes.map((n) => n.id));
  const edges = graph.edges
    .filter(
      (e) =>
        e.evidence_kind === "explicit" &&
        ids.has(e.source) &&
        ids.has(e.target),
    )
    .slice(0, 400);
  const elk = new ELK();
  const specification: ElkNode = {
    id: "workflow",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "RIGHT",
      "elk.edgeRouting": "ORTHOGONAL",
      "elk.spacing.nodeNode": "68",
      "elk.layered.spacing.nodeNodeBetweenLayers": "44",
      "elk.layered.spacing.edgeNodeBetweenLayers": "26",
      "elk.padding": "[top=55,left=35,bottom=55,right=35]",
      "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
    },
    children: nodes.map((n) => ({
      id: n.id,
      width: NODE_WIDTH,
      height: NODE_HEIGHT,
      layoutOptions: { "org.eclipse.elk.portConstraints": "FIXED_POS" },
      ports: [
        {
          id: `${n.id}:in`,
          x: 0,
          y: NODE_HEIGHT / 2,
          width: 0,
          height: 0,
          properties: { side: "WEST" },
        },
        {
          id: `${n.id}:out`,
          x: NODE_WIDTH,
          y: NODE_HEIGHT / 2,
          width: 0,
          height: 0,
          properties: { side: "EAST" },
        },
      ],
    })),
    edges: edges.map((e) => {
      const dir = flowDirection(e);
      return {
        id: e.id,
        sources: [`${dir.source}:out`],
        targets: [`${dir.target}:in`],
      };
    }),
  };
  const result = await elk.layout(specification);
  return {
    nodes: (result.children || []).map((n) => ({
      id: n.id,
      position: { x: n.x || 0, y: n.y || 0 },
    })),
    routes: Object.fromEntries(
      (result.edges || []).flatMap((e) => {
        const section = e.sections?.[0];
        return section
          ? [
              [
                e.id,
                [
                  section.startPoint,
                  ...(section.bendPoints || []),
                  section.endPoint,
                ],
              ],
            ]
          : [];
      }),
    ),
  };
}
