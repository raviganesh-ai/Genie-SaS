import dagre from "@dagrejs/dagre";

export const DEPENDENCY_NODE_WIDTH = 250;
export const DEPENDENCY_NODE_HEIGHT = 56;

export interface DependencyLayoutNode {
  id: string;
}

export interface DependencyLayoutEdge {
  source: string;
  target: string;
}

export interface DependencyNodePosition {
  id: string;
  x: number;
  y: number;
}

/**
 * Lays out the dependency/integration graph by its real edge structure
 * (repository -> component -> manifest/source file -> package/technology ->
 * integration endpoint), mirroring the same dagre-based approach already
 * used for the architecture diagram (see
 * src/features/discovery/architectureLayout.ts). A prior version packed
 * nodes into a type-sorted grid that ignored edges entirely - the grid
 * position of a node had nothing to do with what it was actually
 * connected to, so edges crossed the whole canvas in a way that "didn't
 * make sense" visually even once the container rendered at its correct
 * size. Following the real edges instead produces a legible top-down
 * hierarchy.
 */
export function layoutDependencyGraph(
  nodes: DependencyLayoutNode[],
  edges: DependencyLayoutEdge[],
): DependencyNodePosition[] {
  const graph = new dagre.graphlib.Graph();
  graph.setDefaultEdgeLabel(() => ({}));
  graph.setGraph({
    rankdir: "TB",
    nodesep: 32,
    ranksep: 96,
    marginx: 24,
    marginy: 24,
  });

  nodes.forEach((node) => {
    graph.setNode(node.id, {
      width: DEPENDENCY_NODE_WIDTH,
      height: DEPENDENCY_NODE_HEIGHT,
    });
  });
  const nodeIds = new Set(nodes.map((node) => node.id));
  edges.forEach((edge) => {
    if (nodeIds.has(edge.source) && nodeIds.has(edge.target)) {
      graph.setEdge(edge.source, edge.target);
    }
  });
  dagre.layout(graph);

  return nodes.map((node) => {
    const position = graph.node(node.id) as { x: number; y: number };
    return {
      id: node.id,
      x: position.x - DEPENDENCY_NODE_WIDTH / 2,
      y: position.y - DEPENDENCY_NODE_HEIGHT / 2,
    };
  });
}
