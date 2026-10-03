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
  Switch,
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
import { DEPENDENCY_NODE_WIDTH, layoutDependencyGraph } from "./dependencyGraphLayout";

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

const COVERAGE_GAP_LABELS: Record<string, string> = {
  unreadable_content: "Files that could not be read",
  unreadable_directory: "Folders that could not be listed",
  large_file: "Files skipped for exceeding the size limit",
  manifest_parse_error: "Manifests that could not be parsed",
  file_limit: "Assessment stopped at the configured file limit",
};

// Only a genuinely incomplete assessment (the configured file cap was hit)
// warrants an alarming "warning" treatment - a handful of individual files
// Genie could not read or parse is an expected, honestly-reported limit of
// static analysis, not a sign the application is broken, so it gets a
// calmer "info" treatment instead of looking like an error per file.
const ALARMING_COVERAGE_GAP_CATEGORIES = new Set(["file_limit"]);

interface CoverageGapGroup {
  category: string;
  title: string;
  intent: "warning" | "info";
  fileCount: number;
  samplePaths: string[];
  remainingCount: number;
}

function groupCoverageGaps(
  gaps: Array<{ category: string; detail: string; paths: string[] }>,
): CoverageGapGroup[] {
  const pathsByCategory = new Map<string, string[]>();
  gaps.forEach((gap) => {
    const paths = pathsByCategory.get(gap.category) ?? [];
    paths.push(...(gap.paths.length > 0 ? gap.paths : [gap.detail]));
    pathsByCategory.set(gap.category, paths);
  });
  return Array.from(pathsByCategory.entries()).map(([category, paths]) => ({
    category,
    title: COVERAGE_GAP_LABELS[category] ?? category,
    intent: ALARMING_COVERAGE_GAP_CATEGORIES.has(category) ? "warning" : "info",
    fileCount: paths.length,
    samplePaths: paths.slice(0, 5),
    remainingCount: Math.max(0, paths.length - 5),
  }));
}

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
  // Individual source files/manifests are the vast majority of nodes in any
  // real repository (hundreds, vs. a handful of components/technologies/
  // packages) - defaulting them OFF keeps the graph legible out of the box;
  // the component/technology/package/endpoint "structural" view already
  // answers "how is this codebase organized and what does it depend on"
  // without forcing a render of every single file.
  const [showSourceFiles, setShowSourceFiles] = useState(false);

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
    const visibleAssessmentNodes = showSourceFiles
      ? assessment.nodes
      : assessment.nodes.filter((node) => node.type !== "source_file");
    const visibleNodeIds = new Set(visibleAssessmentNodes.map((node) => node.id));
    const visibleEdges = assessment.edges.filter(
      (edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target),
    );
    // Lay out nodes by their real edge structure (repository -> component
    // -> manifest/source file -> package/technology -> integration
    // endpoint) instead of an arbitrary type-sorted grid - a grid position
    // unrelated to what a node is actually connected to produced edges
    // that crossed the whole canvas and didn't visually read as a
    // coherent dependency tree.
    const positions = new Map(
      layoutDependencyGraph(visibleAssessmentNodes, visibleEdges).map((position) => [
        position.id,
        position,
      ]),
    );
    const componentRoleByNodeId = new Map(
      (assessment.code_summary?.component_roles ?? []).map((role) => [role.component_id, role]),
    );
    const nodes: Node[] = visibleAssessmentNodes.map((node) => {
      const position = positions.get(node.id) ?? { x: 0, y: 0 };
      const baseLabel = node.version ? `${node.name} ${node.version}` : node.name;
      // Tie the Genie-generated code summary's per-component role
      // classification directly into the graph itself (not only the
      // separate text list above it) by annotating each component node
      // with its own role.
      const role = componentRoleByNodeId.get(node.id);
      const label = role ? `${baseLabel}\n${role.role} (${Math.round(role.confidence * 100)}%)` : baseLabel;
      return {
        id: node.id,
        position: { x: position.x, y: position.y },
        data: { label },
        style: {
          color: "#fff",
          background: NODE_COLORS[node.type],
          border: "1px solid rgba(255,255,255,.35)",
          borderRadius: 8,
          width: DEPENDENCY_NODE_WIDTH,
          fontSize: 12,
          whiteSpace: "pre-line",
        },
      };
    });
    const edges: Edge[] = visibleEdges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      label: `${edge.type} (${Math.round(edge.confidence * 100)}%)`,
      animated: edge.type === "integrates_with" || edge.type === "depends_on",
      style: { stroke: EDGE_STROKE_COLORS[edge.type] ?? "#6f7b8a" },
      labelStyle: { fill: "#c8d0da", fontSize: 10 },
    }));
    return { nodes, edges };
  }, [assessment, showSourceFiles]);

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
              <div className="dependency-graph-controls">
                <Switch
                  label={`Show individual source files (${assessment.nodes.filter((node) => node.type === "source_file").length})`}
                  checked={showSourceFiles}
                  onChange={(_, data) => setShowSourceFiles(data.checked)}
                />
                <Badge color="success">Commit pinned</Badge>
              </div>
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
            <div>
              <Text weight="semibold">Coverage and limitations</Text>
              <Text size={200} style={{ display: "block", opacity: 0.72 }}>
                These are expected, honestly-reported limits of static analysis (a handful of
                files Genie could not read or chose to skip) - not application failures.
              </Text>
            </div>
            {assessment.coverage_gaps.length === 0 ? (
              <MessageBar intent="success">
                <MessageBarBody>
                  <MessageBarTitle>No detected coverage gaps</MessageBarTitle>
                  All enumerated analyzable files were processed.
                </MessageBarBody>
              </MessageBar>
            ) : (
              groupCoverageGaps(assessment.coverage_gaps).map((group) => (
                <MessageBar intent={group.intent} key={group.category}>
                  <MessageBarBody>
                    <MessageBarTitle>{group.title}</MessageBarTitle>
                    {group.fileCount} file{group.fileCount === 1 ? "" : "s"} - {group.samplePaths.join(", ")}
                    {group.remainingCount > 0 ? ` and ${group.remainingCount} more` : ""}
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
