import { useMemo } from "react";
import { Badge, Text } from "@fluentui/react-components";
import ReactFlow, { Background, Controls, type Edge, type Node } from "reactflow";
import "reactflow/dist/style.css";
import {
  DEPENDENCY_NODE_WIDTH,
  layoutDependencyGraph,
} from "@/features/dependency-mapping/dependencyGraphLayout";
import type { ModernizationProposedComponent } from "@/types/modernization";

const MODULE_COLOR = "#5a7fb8";
const EXTRACTED_COLOR = "#2bb3a3";

/**
 * Renders a modernization plan's proposed target architecture as an actual
 * node/edge graph - one node per proposed_components entry (colored by
 * whether the plan recommends extracting it into its own independently
 * deployed service, or leaving it inside the existing deployable unit),
 * connected by its depends_on edges. Reuses the same dagre-based layout
 * already built for the Dependency Mapping graph views (see
 * dependencyGraphLayout.ts) rather than relying on the agent to propose
 * x/y coordinates itself, which is both simpler for the prompt contract
 * and avoids the overlapping/illegible layouts an LLM-guessed layout can
 * produce.
 */
export function ModernizationArchitectureGraph({
  components,
}: {
  components: ModernizationProposedComponent[];
}): JSX.Element {
  const graph = useMemo(() => {
    const positions = new Map(
      layoutDependencyGraph(
        components.map((component) => ({ id: component.id })),
        components.flatMap((component) =>
          component.depends_on.map((dependsOnId) => ({
            source: component.id,
            target: dependsOnId,
          })),
        ),
      ).map((position) => [position.id, position]),
    );
    const nodes: Node[] = components.map((component) => ({
      id: component.id,
      position: positions.get(component.id) ?? { x: 0, y: 0 },
      data: { label: `${component.name}\n${component.extracted ? "Extracted service" : "Module"}` },
      style: {
        color: "#fff",
        background: component.extracted ? EXTRACTED_COLOR : MODULE_COLOR,
        border: "1px solid rgba(255,255,255,.35)",
        borderRadius: 8,
        width: DEPENDENCY_NODE_WIDTH,
        fontSize: 12,
        whiteSpace: "pre-line",
      },
    }));
    const edges: Edge[] = components.flatMap((component) =>
      component.depends_on.map((dependsOnId) => ({
        id: `${component.id}->${dependsOnId}`,
        source: component.id,
        target: dependsOnId,
        label: "depends on",
        style: { stroke: "#c77dff" },
        labelStyle: { fill: "#e6e9ee", fontSize: 10, fontWeight: 600 },
        labelBgStyle: { fill: "#1b2330", fillOpacity: 0.92 },
        labelBgPadding: [4, 2] as [number, number],
        labelBgBorderRadius: 4,
      })),
    );
    return { nodes, edges };
  }, [components]);

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
        <Text weight="semibold">Proposed architecture</Text>
        <Badge appearance="outline" style={{ color: MODULE_COLOR, borderColor: MODULE_COLOR }}>
          Module (stays together)
        </Badge>
        <Badge appearance="outline" style={{ color: EXTRACTED_COLOR, borderColor: EXTRACTED_COLOR }}>
          Extracted service
        </Badge>
      </div>
      <div className="modernization-architecture-graph">
        <ReactFlow nodes={graph.nodes} edges={graph.edges} fitView>
          <Background />
          <Controls />
        </ReactFlow>
      </div>
    </div>
  );
}
