import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  Dropdown,
  Input,
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
import { AgentActivityAnimation } from "@/components/AgentActivityAnimation";
import { ErrorState } from "@/components/ErrorState";
import { ApiError } from "@/services/httpClient";
import { repositoryConnectionApi } from "@/services/repositoryConnectionApi";
import { useSessionContext } from "@/state/SessionContext";
import type { SafeError } from "@/types/common";
import type {
  DependencyEdgeType,
  DependencyNodeType,
  RepositoryAssessment,
  RepositoryPurposeBinding,
} from "@/types/repositoryConnection";

const NODE_COLORS: Record<DependencyNodeType, string> = {
  repository: "#2f83e0",
  component: "#5a7fb8",
  manifest: "#8a63d2",
  source_file: "#3fa66a",
  package: "#d99a2b",
  technology: "#2bb3a3",
  integration_endpoint: "#d35f5f",
};

// "depends_on" is the heuristic, cross-component intra-repository
// interdependency edge (RepositoryAssessmentService._resolve_local_dependencies)
// - given its own distinct, animated color so real code interdependencies
// stand out from purely structural "contains"/"built_on" edges.
const EDGE_STROKE_COLORS: Partial<Record<DependencyEdgeType, string>> = {
  integrates_with: "#d35f5f",
  depends_on: "#c77dff",
};

const NODE_COLUMNS: Record<DependencyNodeType, number> = {
  repository: 0,
  component: 1,
  manifest: 2,
  source_file: 2,
  package: 3,
  technology: 3,
  integration_endpoint: 4,
};

interface RepositoryChatMessage {
  id: string;
  role: "user" | "genie";
  text: string;
  referencedPaths?: string[];
}


export function DependencyMappingPage(): JSX.Element {
  const navigate = useNavigate();
  const { sessionId } = useSessionContext();
  const [bindings, setBindings] = useState<RepositoryPurposeBinding[]>([]);
  const [assessment, setAssessment] = useState<RepositoryAssessment | null>(null);
  const [selectedBindingId, setSelectedBindingId] = useState("");
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [runStartedAt, setRunStartedAt] = useState<string | null>(null);
  const [error, setError] = useState<SafeError | null>(null);
  const [chatMessages, setChatMessages] = useState<RepositoryChatMessage[]>([]);
  const [chatDraft, setChatDraft] = useState("");
  const [chatAsking, setChatAsking] = useState(false);
  const [chatError, setChatError] = useState<SafeError | null>(null);

  const runAssessmentFor = useCallback(
    async (bindingId: string) => {
      if (!sessionId || !bindingId) return;
      setRunning(true);
      setRunStartedAt(new Date().toISOString());
      setError(null);
      setChatMessages([]);
      try {
        setAssessment(await repositoryConnectionApi.createAssessment(sessionId, bindingId));
      } catch (err) {
        setError(
          err instanceof ApiError ? err : { message: "The live repository assessment failed." },
        );
      } finally {
        setRunning(false);
        setRunStartedAt(null);
      }
    },
    [sessionId],
  );

  const handleAskRepository = useCallback(async () => {
    const message = chatDraft.trim();
    if (!sessionId || !assessment || !message || chatAsking) return;
    setChatMessages((current) => [...current, { id: `${Date.now()}-user`, role: "user", text: message }]);
    setChatDraft("");
    setChatError(null);
    setChatAsking(true);
    try {
      const result = await repositoryConnectionApi.askAboutAssessment(sessionId, assessment.id, message);
      setChatMessages((current) => [
        ...current,
        {
          id: `${Date.now()}-genie`,
          role: "genie",
          text: result.answer,
          referencedPaths: result.referenced_paths,
        },
      ]);
    } catch (caught) {
      setChatError(caught instanceof ApiError ? caught : { message: "Unable to answer that question." });
    } finally {
      setChatAsking(false);
    }
  }, [sessionId, assessment, chatDraft, chatAsking]);

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
      animated: edge.type === "integrates_with" || edge.type === "depends_on",
      style: { stroke: EDGE_STROKE_COLORS[edge.type] ?? "#6f7b8a" },
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
      {running ? (
        <AgentActivityAnimation
          label="Reading each file live from GitHub..."
          startedAt={runStartedAt}
          fallbackDetail="Larger repositories can take several minutes - this is still working."
        />
      ) : null}

      {assessment ? (
        <>
          <div className="dependency-mapping-stats">
            <Card><Text weight="semibold">{assessment.inventory.file_count}</Text><Text>Files discovered</Text></Card>
            <Card><Text weight="semibold">{assessment.inventory.analyzed_file_count}</Text><Text>Files analyzed</Text></Card>
            <Card><Text weight="semibold">{assessment.nodes.length}</Text><Text>Graph nodes</Text></Card>
            <Card><Text weight="semibold">{assessment.edges.length}</Text><Text>Evidence edges</Text></Card>
          </div>
          {assessment.code_summary ? (
            <Card className="repository-intake-card code-summary-card">
              <div className="dependency-mapping-heading">
                <Text weight="semibold">Code summary</Text>
                <Badge color="informative" appearance="tint">Genie-generated - verify before relying on it</Badge>
              </div>
              <Text block>{assessment.code_summary.summary}</Text>
              {assessment.code_summary.highlights.length > 0 ? (
                <ul className="code-summary-highlights">
                  {assessment.code_summary.highlights.map((highlight, index) => (
                    <li key={index}>{highlight}</li>
                  ))}
                </ul>
              ) : null}
              {assessment.code_summary.component_roles.length > 0 ? (
                <div className="code-summary-roles">
                  {assessment.code_summary.component_roles.map((role) => (
                    <div key={role.component_id} className="code-summary-role-row">
                      <Badge appearance="outline">{role.component_path}</Badge>
                      <Text weight="semibold">{role.role}</Text>
                      <Text size={200} style={{ opacity: 0.72 }}>
                        {Math.round(role.confidence * 100)}% confidence - {role.rationale}
                      </Text>
                    </div>
                  ))}
                </div>
              ) : null}
            </Card>
          ) : null}
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
          <Card className="repository-intake-card dependency-chat-card">
            <div>
              <Text weight="semibold">Ask about this repository</Text>
              <Text size={200} className="dependency-chat-hint" style={{ display: "block", opacity: 0.72 }}>
                Ask anything about the analyzed repository - its components, dependencies,
                technologies, or integration points. Genie answers only from the graph above,
                not from general knowledge, and cites the specific files or components it relied on.
              </Text>
            </div>
            {chatMessages.length > 0 ? (
              <ul className="dependency-chat-log">
                {chatMessages.map((item) => (
                  <li key={item.id} className={`dependency-chat-message dependency-chat-message-${item.role}`}>
                    <Text size={200} weight="semibold">{item.role === "user" ? "You" : "Genie"}</Text>
                    <Text size={200}>{item.text}</Text>
                    {item.role === "genie" && item.referencedPaths && item.referencedPaths.length > 0 ? (
                      <div className="dependency-chat-references">
                        {item.referencedPaths.map((path) => (
                          <Badge key={path} appearance="outline" size="small">{path}</Badge>
                        ))}
                      </div>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : null}
            {chatError ? <ErrorState error={chatError} /> : null}
            <div className="dependency-chat-row">
              <Input
                className="dependency-chat-input"
                placeholder="e.g. What does the backend component depend on?"
                value={chatDraft}
                disabled={chatAsking}
                onChange={(_, data) => setChatDraft(data.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void handleAskRepository();
                  }
                }}
              />
              <Button
                appearance="primary"
                disabled={chatAsking || !chatDraft.trim()}
                onClick={() => void handleAskRepository()}
              >
                {chatAsking ? "Asking..." : "Ask Genie"}
              </Button>
            </div>
            {chatAsking ? <Spinner size="tiny" label="Genie is reading the dependency graph..." /> : null}
          </Card>
          <Button appearance="secondary" onClick={() => navigate("/iq-collaboration")}>
            Continue to IQ Collaboration
          </Button>
        </>
      ) : null}
      {error ? <ErrorState error={error} onRetry={() => void load()} /> : null}
    </section>
  );
}
