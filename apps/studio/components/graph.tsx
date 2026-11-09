"use client";
import {
  Background,
  BaseEdge,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  applyNodeChanges,
  getSmoothStepPath,
  useReactFlow,
  type Node,
  type NodeChange,
  type NodeProps,
  type EdgeProps,
} from "@xyflow/react";
import { Focus, Layers, Network, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { closure, displayedState, layout, short } from "@/lib/model";
import {
  flowDirection,
  NODE_HEIGHT,
  NODE_WIDTH,
  roundedPath,
  type LayoutResult,
  type Point,
} from "@/lib/graph-geometry";
import type { Graph, GraphNode, Runtime } from "@/lib/types";
import { Asset, taskAsset } from "./asset";
import { Empty, Status } from "./ui";

type FlowData = {
  label: string;
  state: string;
  kind: string;
  incidents: number;
  identifier: string;
  asset: string;
  [key: string]: unknown;
};
type FlowNode = Node<FlowData, "workflow">;
function WorkflowNode({ data, selected }: NodeProps<FlowNode>) {
  return (
    <div className={`workflow-node ${selected ? "selected" : ""}`}>
      <Handle id="in" type="target" position={Position.Left} />
      <div className="node-top">
        <Asset name={data.asset} className="node-art" />
        <span className="node-kind">{data.kind}</span>
        {data.incidents > 0 && (
          <span className="node-incident">
            {data.incidents} finding{data.incidents > 1 ? "s" : ""}
          </span>
        )}
      </div>
      <strong title={data.label}>{data.label}</strong>
      <div className="node-bottom">
        <Status value={data.state} />
        <span className="mono">{short(data.identifier)}</span>
      </div>
      <Handle id="out" type="source" position={Position.Right} />
    </div>
  );
}
function RoutedEdge(props: EdgeProps) {
  const route = props.data?.route as Point[] | undefined;
  const start = route?.[0],
    end = route?.at(-1);
  const follows =
    !!start &&
    !!end &&
    Math.abs(start.x - props.sourceX) < 2 &&
    Math.abs(start.y - props.sourceY) < 2 &&
    Math.abs(end.x - props.targetX) < 2 &&
    Math.abs(end.y - props.targetY) < 2;
  const path = follows ? roundedPath(route!) : getSmoothStepPath(props)[0];
  return (
    <BaseEdge
      id={props.id}
      path={path}
      style={props.style}
      markerEnd={props.markerEnd}
      interactionWidth={18}
    />
  );
}
const nodeTypes = { workflow: WorkflowNode };
const edgeTypes = { routed: RoutedEdge };
interface Props {
  graph: Graph;
  runtimes: Runtime[];
  selected: string | null;
  onSelect: (id: string) => void;
  onEdge: (id: string) => void;
  taskCount: number;
  agentCount: number;
}
function Canvas({ graph, runtimes, selected, onSelect, onEdge }: Props) {
  const flow = useReactFlow();
  const [nodes, setNodes] = useState<FlowNode[]>([]);
  const [arranged, setArranged] = useState<LayoutResult | null>(null);
  const [layoutError, setLayoutError] = useState(false);
  const fitted = useRef(false);
  const worker = useRef<Worker | null>(null);
  const layoutKey = JSON.stringify({
    nodes: graph.nodes.slice(0, 200).map((n) => ({ id: n.id })),
    edges: graph.edges.slice(0, 400).map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      relation_kind: e.relation_kind,
      evidence_kind: e.evidence_kind,
    })),
  });
  const topology = useMemo(() => JSON.parse(layoutKey), [layoutKey]);
  useEffect(() => {
    let disposed = false;
    const instance = new Worker(
      new URL("../lib/layout.worker.ts", import.meta.url),
    );
    worker.current = instance;
    setArranged(null);
    setLayoutError(false);
    fitted.current = false;
    instance.onmessage = (event) => {
      if (disposed || event.data.key !== layoutKey) return;
      if (event.data.layout) setArranged(event.data.layout);
      else setLayoutError(true);
    };
    instance.onerror = () => setLayoutError(true);
    instance.postMessage({ key: layoutKey, graph: topology });
    return () => {
      disposed = true;
      instance.terminate();
      worker.current = null;
    };
  }, [layoutKey, topology]);
  const positions = useMemo(
    () =>
      new Map(
        (arranged?.nodes || layout(graph)).map((p) => [p.id, p.position]),
      ),
    [arranged, layoutKey],
  );
  useEffect(() => {
    setNodes((old) =>
      graph.nodes.slice(0, 200).map((node) => ({
        id: node.id,
        type: "workflow",
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
        position: old.find((n) => n.id === node.id)?.position ||
          positions.get(node.id) || { x: 0, y: 0 },
        selected: node.id === selected,
        data: {
          label: node.label,
          state: displayedState(node, runtimes),
          kind: node.node_kind,
          incidents: node.incident_ids?.length || 0,
          identifier: node.id,
          asset: taskAsset(node),
        },
        ariaLabel: `${node.label}, ${displayedState(node, runtimes)}. Open inspector.`,
      })),
    );
  }, [graph, runtimes, selected, positions]);
  useEffect(() => {
    if (!arranged) return;
    setNodes((old) =>
      old.map((n) => ({ ...n, position: positions.get(n.id) || n.position })),
    );
  }, [arranged, positions]);
  useEffect(() => {
    if (nodes.length && (arranged || layoutError) && !fitted.current) {
      const timer = setTimeout(() => {
        void flow.fitView({
          nodes: selected ? [{ id: selected }] : undefined,
          padding: selected ? 0.2 : 0.06,
          maxZoom: 1,
        });
        fitted.current = true;
      }, 120);
      return () => clearTimeout(timer);
    }
  }, [nodes.length, arranged, layoutError, flow, selected]);
  const affected = selected ? closure(graph, selected) : null;
  const visible = new Set(graph.nodes.slice(0, 200).map((n) => n.id));
  const edges = graph.edges
    .filter((e) => visible.has(e.source) && visible.has(e.target))
    .slice(0, 400)
    .map((edge) => ({
      id: edge.id,
      ...flowDirection(edge),
      sourceHandle: "out",
      targetHandle: "in",
      type: "routed",
      data: { route: arranged?.routes[edge.id] },
      animated: false,
      style: {
        stroke:
          affected && affected.has(edge.source) && affected.has(edge.target)
            ? "#222521"
            : "#777e70",
        strokeWidth: 1.5,
        strokeDasharray: edge.evidence_kind === "explicit" ? undefined : "5 4",
      },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: "#777e70",
        width: 14,
        height: 14,
      },
      ariaLabel: `${edge.relation_kind}, ${edge.evidence_kind} relationship`,
    }));
  return (
    <>
      <div className="canvas-fit">
        <button
          className="button small"
          onClick={() => void flow.fitView({ padding: 0.06, maxZoom: 1 })}
        >
          <Focus size={13} />
          Fit graph
        </button>
        <span className="canvas-layout-state">
          {layoutError
            ? "Simple layout"
            : !arranged
              ? "Arranging dependencies…"
              : "Prerequisite → dependent"}
        </span>
      </div>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={(changes: NodeChange<FlowNode>[]) =>
          setNodes((old) => applyNodeChanges(changes, old))
        }
        onNodeClick={(_, node) => onSelect(node.id)}
        onEdgeClick={(_, edge) => onEdge(edge.id)}
        nodesConnectable={false}
        edgesReconnectable={false}
        nodesFocusable={false}
        edgesFocusable={false}
        disableKeyboardA11y
        deleteKeyCode={null}
        selectionKeyCode={null}
        multiSelectionKeyCode={null}
        panActivationKeyCode={null}
        zoomActivationKeyCode={null}
        minZoom={0.18}
        maxZoom={1.5}
        colorMode="light"
      >
        <Background color="#dbded2" gap={24} size={0.7} />
        <Controls showInteractive={false} />
        {graph.nodes.length > 4 && (
          <MiniMap
            className="graph-minimap"
            nodeColor="#b8bfac"
            maskColor="#f4f3ee99"
            zoomable
            pannable
          />
        )}
      </ReactFlow>
      <div className="canvas-legend">
        <span>
          <i />
          Explicit dependency
        </span>
        {graph.edges.some((e) => e.evidence_kind !== "explicit") && (
          <span>
            <i className="dashed" />
            Inferred association
          </span>
        )}
        <span>Read-only orchestration</span>
      </div>
    </>
  );
}
export default function GraphView(
  props: Props & { view: string; setView: (view: string) => void },
) {
  const [query, setQuery] = useState("");
  const [format, setFormat] = useState("graph");
  useEffect(() => {
    if (window.matchMedia("(max-width:767px)").matches) setFormat("list");
  }, []);
  const selectedIds = new Set(
    props.graph.nodes
      .filter((n) =>
        (n.label + " " + n.id).toLowerCase().includes(query.toLowerCase()),
      )
      .map((n) => n.id),
  );
  return (
    <section className="panel graph-panel">
      <div className="graph-toolbar">
        <div className="segmented" aria-label="Graph projection">
          <button
            className={props.view === "task" ? "active" : ""}
            onClick={() => props.setView("task")}
          >
            Tasks <span className="count">{props.taskCount}</span>
          </button>
          <button
            className={props.view === "agent" ? "active" : ""}
            onClick={() => props.setView("agent")}
          >
            Agents <span className="count">{props.agentCount}</span>
          </button>
        </div>
        <label className="graph-search">
          <Search size={13} />
          <input
            placeholder="Find a node…"
            aria-label="Find graph node"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              if (e.target.value) setFormat("list");
            }}
          />
        </label>
        <div className="segmented format-toggle">
          <button
            aria-label="Graph view"
            className={format === "graph" ? "active" : ""}
            onClick={() => {
              setQuery("");
              setFormat("graph");
            }}
          >
            <Network size={14} />
          </button>
          <button
            aria-label="List view"
            className={format === "list" ? "active" : ""}
            onClick={() => setFormat("list")}
          >
            <Layers size={14} />
          </button>
        </div>
      </div>
      {!props.graph.nodes.length ? (
        <Empty title="No declared nodes in this view">
          <p>Task dependencies appear after SDK lifecycle ingestion.</p>
        </Empty>
      ) : (
        <>
          <div
            className={`graph-canvas ${format === "list" ? "list-only" : ""}`}
          >
            <ReactFlowProvider key={props.view}>
              <Canvas {...props} />
            </ReactFlowProvider>
          </div>
          <div
            className={`node-list ${format === "list" ? "list-active" : "mobile-list"}`}
          >
            <div className="node-list-heading">
              {props.view === "task" ? "Tasks" : "Agents"}
              <span>
                {selectedIds.size} of {props.graph.nodes.length} declared
              </span>
            </div>
            {props.graph.nodes
              .filter((n) => selectedIds.has(n.id))
              .map((node) => (
                <button
                  className={`node-list-row ${node.id === props.selected ? "selected" : ""}`}
                  key={node.id}
                  onClick={() => props.onSelect(node.id)}
                >
                  <Asset name={taskAsset(node)} />
                  <span>
                    <strong>{node.label}</strong>
                    <small className="mono">{short(node.id)}</small>
                  </span>
                  <Status value={displayedState(node, props.runtimes)} />
                </button>
              ))}
            {!selectedIds.size && (
              <Empty title="No matching nodes">
                <p>Try a task name or identifier.</p>
              </Empty>
            )}
          </div>
          <div className="panel-bottom">
            {props.graph.nodes.length} nodes · {props.graph.edges.length}{" "}
            declared relationships
            {props.graph.nodes.length > 200
              ? " · Canvas shows first 200 nodes; use the complete list."
              : ""}
          </div>
        </>
      )}
    </section>
  );
}
