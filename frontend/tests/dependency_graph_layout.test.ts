import { describe, expect, it } from "vitest";
import {
  DEPENDENCY_NODE_HEIGHT,
  DEPENDENCY_NODE_WIDTH,
  layoutDependencyGraph,
} from "@/features/dependency-mapping/dependencyGraphLayout";

describe("layoutDependencyGraph", () => {
  it("positions a repository -> component -> package tree with non-overlapping nodes and edges flowing downward", () => {
    const nodes = [
      { id: "repository:1" },
      { id: "component:backend" },
      { id: "component:frontend" },
      { id: "manifest:pyproject" },
      { id: "package:fastapi" },
      { id: "package:react" },
    ];
    const edges = [
      { source: "repository:1", target: "component:backend" },
      { source: "repository:1", target: "component:frontend" },
      { source: "component:backend", target: "manifest:pyproject" },
      { source: "manifest:pyproject", target: "package:fastapi" },
      { source: "component:frontend", target: "package:react" },
    ];

    const positions = layoutDependencyGraph(nodes, edges);

    expect(positions).toHaveLength(nodes.length);
    for (let leftIndex = 0; leftIndex < positions.length; leftIndex += 1) {
      for (let rightIndex = leftIndex + 1; rightIndex < positions.length; rightIndex += 1) {
        const left = positions[leftIndex];
        const right = positions[rightIndex];
        const overlapsHorizontally = left.x < right.x + DEPENDENCY_NODE_WIDTH
          && left.x + DEPENDENCY_NODE_WIDTH > right.x;
        const overlapsVertically = left.y < right.y + DEPENDENCY_NODE_HEIGHT
          && left.y + DEPENDENCY_NODE_HEIGHT > right.y;
        expect(overlapsHorizontally && overlapsVertically).toBe(false);
      }
    }

    // A top-down hierarchy means every edge's target sits at or below its
    // source - this is what makes the graph read as a coherent dependency
    // tree instead of edges crossing the whole canvas in no particular
    // order, which was the actual complaint about the previous type-sorted
    // grid layout.
    const byId = new Map(positions.map((position) => [position.id, position]));
    edges.forEach((edge) => {
      expect(byId.get(edge.target)!.y).toBeGreaterThan(byId.get(edge.source)!.y);
    });
  });

  it("handles a large, mostly-flat set of sibling nodes without throwing", () => {
    const nodes = [
      { id: "repository:1" },
      { id: "component:backend" },
      ...Array.from({ length: 300 }, (_, index) => ({ id: `source_file:${index}` })),
    ];
    const edges = [
      { source: "repository:1", target: "component:backend" },
      ...Array.from({ length: 300 }, (_, index) => ({
        source: "component:backend",
        target: `source_file:${index}`,
      })),
    ];

    const positions = layoutDependencyGraph(nodes, edges);

    expect(positions).toHaveLength(nodes.length);
    expect(positions.every((position) => Number.isFinite(position.x) && Number.isFinite(position.y))).toBe(
      true,
    );
  });
});
