import { arrangeGraph } from "./graph-layout";
import type { Graph } from "./types";
self.onmessage = async (event: MessageEvent<{ key: string; graph: Graph }>) => {
  try {
    self.postMessage({
      key: event.data.key,
      layout: await arrangeGraph(event.data.graph),
    });
  } catch {
    self.postMessage({
      key: event.data.key,
      error: "Automatic layout unavailable",
    });
  }
};
