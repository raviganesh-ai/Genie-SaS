import dagre from "@dagrejs/dagre";

export const DEPENDENCY_NODE_WIDTH = 250;
export const DEPENDENCY_NODE_HEIGHT = 56;

// If a single rank (e.g. every file directly inside one component) has
// more nodes than this, laying them out as one single row produces an
// absurdly wide canvas (observed: ~400 sibling file nodes in one row
// requiring >115,000px of width) that defeats ReactFlow's fitView just
// as badly as the original unbounded-single-column bug did - just
// rotated 90 degrees. Beyond this threshold, wrap the rank into a
// roughly square sub-grid instead of one row.
const MAX_NODES_PER_ROW = 24;
const COLUMN_GAP = DEPENDENCY_NODE_WIDTH + 30;
const SUBROW_GAP = DEPENDENCY_NODE_HEIGHT + 40;
const RANK_GAP = 96;

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
 *
 * dagre's own per-rank row is used only to determine which nodes share a
 * rank and their left-to-right reading order within it - the actual
 * on-screen row is then re-flowed into a square-ish sub-grid whenever a
 * rank is unusually large (see MAX_NODES_PER_ROW), with every later
 * rank's vertical band shifted down by however much extra height that
 * wrapping needed, so nothing overlaps.
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
    ranksep: RANK_GAP,
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

  const rawPositions = new Map(
    nodes.map((node) => [node.id, graph.node(node.id) as { x: number; y: number }]),
  );

  // Group nodes into their dagre rank (nodes dagre placed at the same y
  // share a rank) while keeping each rank's dagre-assigned left-to-right
  // order, which already roughly clusters related siblings together.
  const rankGroups = new Map<number, DependencyLayoutNode[]>();
  nodes.forEach((node) => {
    const rankKey = Math.round(rawPositions.get(node.id)!.y);
    const group = rankGroups.get(rankKey);
    if (group) {
      group.push(node);
    } else {
      rankGroups.set(rankKey, [node]);
    }
  });
  const orderedRankKeys = Array.from(rankGroups.keys()).sort((a, b) => a - b);

  const finalPositions = new Map<string, { x: number; y: number }>();
  let bandStartY = 0;
  orderedRankKeys.forEach((rankKey) => {
    const rankNodes = [...rankGroups.get(rankKey)!].sort(
      (a, b) => rawPositions.get(a.id)!.x - rawPositions.get(b.id)!.x,
    );
    const columns = rankNodes.length <= MAX_NODES_PER_ROW
      ? rankNodes.length
      : Math.ceil(Math.sqrt(rankNodes.length));
    rankNodes.forEach((node, index) => {
      const column = index % columns;
      const row = Math.floor(index / columns);
      finalPositions.set(node.id, {
        x: column * COLUMN_GAP,
        y: bandStartY + row * SUBROW_GAP,
      });
    });
    const rowCount = Math.ceil(rankNodes.length / columns);
    bandStartY += rowCount * SUBROW_GAP + RANK_GAP;
  });

  return nodes.map((node) => {
    const position = finalPositions.get(node.id)!;
    return { id: node.id, x: position.x, y: position.y };
  });
}

