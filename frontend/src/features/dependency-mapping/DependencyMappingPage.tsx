import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  Dropdown,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  Option,
  Spinner,
  Text,
  Title2,
} from "@fluentui/react-components";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  type Edge,
  type Node,
} from "reactflow";
import "reactflow/dist/style.css";
import { ErrorState } from "@/components/ErrorState";
import { ApiError } from "@/services/httpClient";
import { repositoryConnectionApi } from "@/services/repositoryConnectionApi";
import { useSessionContext } from "@/state/SessionContext";
import type { SafeError } from "@/types/common";
import type {
  DependencyNodeType,
  RepositoryAssessment,
  RepositoryPurposeBinding,
} from "@/types/repositoryConnection";

const NODE_COLORS: Record<DependencyNodeType, string> = {
  repository: "#2f83e0",
  manifest: "#8a63d2",
  source_file: "#3fa66a",
  package: "#d99a2b",
  integration_endpoint: "#d35f5f",
};

const NODE_COLUMNS: Record<DependencyNodeType, number> = {
  repository: 0,
  manifest: 1,
  source_file: 1,
  package: 2,
  integration_endpoint: 2,
};

export function DependencyMappingPage(): JSX.Element {
  const navigate = useNavigate();
  const { sessionId } = useSessionContext();
  const [bindings, setBindings] = useState<RepositoryPurposeBinding[]>([]);
  const [assessment, setAssessment] = useState<RepositoryAssessment | null>(null);
  const [selectedBindingId, setSelectedBindingId] = useState("");
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<SafeError | null>(null);

  const runAssessmentFor = useCallback(
    async (bindingId: string) => {
      if (!sessionId || !bindingId) return;
      setRunning(true);
      setError(null);
      try {
        setAssessment(await repositoryConnectionApi.createAssessment(sessionId, bindingId));
      } catch (err) {
        setError(
          err instanceof ApiError ? err : { message: "The live repository assessment failed." },
        );
      } finally {
        setRunning(false);
      }
    },
    [sessionId],
  );

  const load = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    setError(null);
    try {
      const [availableBindings, assessments] = await Promise.all([
        repositoryConnectionApi.listBindings(sessionId),
        repositoryConnectionApi.listAssessments(sessionId),
      ]);
      const activeBindings = availableBindings.filter(
        (binding) =>
          binding.status === "approved" &&
          (binding.purpose === "code" || binding.purpose === "architecture"),
      );
      const firstBindingId = activeBindings[0]?.id ?? "";
      setBindings(activeBindings);
      setSelectedBindingId((current) => current || firstBindingId);
      const existingAssessment = assessments[0] ?? null;
      setAssessment(existingAssessment);
      // Auto-run the assessment the first time this page is reached with an
      // approved binding and no prior run - the user already expressed this
      // intent by clicking "Continue to dependency mapping"; requiring a
      // second, separate "Run" click for the same ask is redundant.
      if (!existingAssessment && firstBindingId) {
        setLoading(false);
        await runAssessmentFor(firstBindingId);
        return;
      }
    } catch (err) {
      setError(err instanceof ApiError ? err : { message: "Unable to load dependency mapping." });
    } finally {
      setLoading(false);
    }
  }, [sessionId, runAssessmentFor]);

  useEffect(() => {
    void load();
  }, [load]);

  const runAssessment = useCallback(
    () => runAssessmentFor(selectedBindingId),
    [runAssessmentFor, selectedBindingId],
  );

  const graph = useMemo(() => {
    if (!assessment) return { nodes: [] as Node[], edges: [] as Edge[] };
    const rows: Record<number, number> = {};
    const nodes: Node[] = assessment.nodes.map((node) => {
      const column = NODE_COLUMNS[node.type];
      const row = rows[column] ?? 0;
      rows[column] = row + 1;
      return {
        id: node.id,
        position: { x: column * 340, y: row * 90 },
        data: { label: node.version ? `${node.name} ${node.version}` : node.name },
        style: {
          color: "#fff",
          background: NODE_COLORS[node.type],
          border: "1px solid rgba(255,255,255,.35)",
          borderRadius: 8,
          width: 250,
          fontSize: 12,
        },
      };
    });
    const edges: Edge[] = assessment.edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      label: `${edge.type} (${Math.round(edge.confidence * 100)}%)`,
      animated: edge.type === "integrates_with",
      style: { stroke: edge.type === "integrates_with" ? "#d35f5f" : "#6f7b8a" },
      labelStyle: { fill: "#c8d0da", fontSize: 10 },
    }));
    return { nodes, edges };
  }, [assessment]);

  if (!sessionId) {
    return <ErrorState error={{ message: "Create a session before running dependency mapping." }} />;
  }

  return (
    <section className="genie-fade-in dependency-mapping-page">
      <div>
        <Title2>Dependency Mapping</Title2>
        <Text block style={{ opacity: 0.72, marginTop: 6 }}>
          Build a deterministic dependency and integration context graph from a commit-pinned
          repository. Every edge links back to its source path and immutable commit.
        </Text>
      </div>

      <Card className="repository-intake-card">
        <Text weight="semibold">Repository snapshot</Text>
        {loading ? <Spinner label="Loading approved repository bindings..." /> : null}
        <Dropdown
          placeholder="Select an approved Code or Architecture repository"
          value={
            bindings.find((binding) => binding.id === selectedBindingId)?.repository_full_name ?? ""
          }
          selectedOptions={selectedBindingId ? [selectedBindingId] : []}
          onOptionSelect={(_, data) => setSelectedBindingId(data.optionValue ?? "")}
          disabled={loading || bindings.length === 0 || running}
        >
          {bindings.map((binding) => (
            <Option key={binding.id} value={binding.id} text={binding.repository_full_name}>
              {binding.repository_full_name} ({binding.purpose})
            </Option>
          ))}
        </Dropdown>
        <Button
          appearance="primary"
          disabled={!selectedBindingId || running}
          onClick={() => void runAssessment()}
        >
          {running ? "Reading immutable repository..." : "Run live dependency assessment"}
        </Button>
      </Card>

      {assessment ? (
        <>
          <div className="dependency-mapping-stats">
            <Card><Text weight="semibold">{assessment.inventory.file_count}</Text><Text>Files discovered</Text></Card>
            <Card><Text weight="semibold">{assessment.inventory.analyzed_file_count}</Text><Text>Files analyzed</Text></Card>
            <Card><Text weight="semibold">{assessment.nodes.length}</Text><Text>Graph nodes</Text></Card>
            <Card><Text weight="semibold">{assessment.edges.length}</Text><Text>Evidence edges</Text></Card>
          </div>
          <Card className="repository-intake-card">
            <div className="dependency-mapping-heading">
              <div>
                <Text weight="semibold">{assessment.repository_full_name}</Text>
                <Text block size={200} className="repository-commit">{assessment.commit}</Text>
              </div>
              <Badge color="success">Commit pinned</Badge>
            </div>
            <div className="dependency-graph">
              <ReactFlow nodes={graph.nodes} edges={graph.edges} fitView>
                <Background />
                <MiniMap pannable zoomable />
                <Controls />
              </ReactFlow>
            </div>
          </Card>
          <Card className="repository-intake-card">
            <Text weight="semibold">Coverage and limitations</Text>
            {assessment.coverage_gaps.length === 0 ? (
              <MessageBar intent="success">
                <MessageBarBody>
                  <MessageBarTitle>No detected coverage gaps</MessageBarTitle>
                  All enumerated analyzable files were processed.
                </MessageBarBody>
              </MessageBar>
            ) : (
              assessment.coverage_gaps.map((gap, index) => (
                <MessageBar intent="warning" key={`${gap.category}-${index}`}>
                  <MessageBarBody>
                    <MessageBarTitle>{gap.category}</MessageBarTitle>
                    {gap.detail} {gap.paths.slice(0, 3).join(", ")}
                  </MessageBarBody>
                </MessageBar>
              ))
            )}
          </Card>
          <Button appearance="secondary" onClick={() => navigate("/standards")}>
            Continue to Architecture Standards
          </Button>
        </>
      ) : null}
      {error ? <ErrorState error={error} onRetry={() => void load()} /> : null}
    </section>
  );
}
