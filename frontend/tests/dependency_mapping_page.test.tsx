import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DependencyMappingPage } from "@/features/dependency-mapping/DependencyMappingPage";
import { mockFetchSequence, renderWithProviders } from "./testUtils";
import { FIXTURE_SESSION_ID } from "./fixtures";

const BINDING = {
  id: "binding-1",
  session_id: FIXTURE_SESSION_ID,
  owner_user_id: "owner-1",
  repository_id: 1,
  repository_full_name: "raviganesh-ai/lumen-grove-demo",
  repository_url: "https://github.com/raviganesh-ai/lumen-grove-demo",
  purpose: "code",
  requested_ref: "main",
  resolved_commit: "a".repeat(40),
  included_paths: [],
  excluded_paths: [],
  principal: "raviganesh-ai",
  status: "approved",
  validated_at: "2026-01-01T00:00:00Z",
  created_at: "2026-01-01T00:00:00Z",
};

const ASSESSMENT = {
  id: "assessment-1",
  session_id: FIXTURE_SESSION_ID,
  binding_id: "binding-1",
  repository_full_name: "raviganesh-ai/lumen-grove-demo",
  commit: "a".repeat(40),
  inventory: {
    file_count: 9,
    analyzed_file_count: 1,
    languages: ["javascript"],
    manifest_paths: [],
    infrastructure_paths: [],
    workflow_paths: [],
    test_paths: [],
  },
  nodes: [],
  edges: [],
  coverage_gaps: [],
  code_summary: null,
  created_at: "2026-01-01T00:00:00Z",
};

const ASSESSMENT_WITH_SUMMARY = {
  ...ASSESSMENT,
  nodes: [
    {
      id: "component:1",
      type: "component",
      name: "backend",
      version: null,
      path: "backend",
      attributes: {},
    },
  ],
  code_summary: {
    summary: "This repository implements a FastAPI backend service.",
    highlights: ["Uses FastAPI", "Exposes one webhook endpoint"],
    component_roles: [
      {
        component_id: "component:1",
        component_path: "backend",
        role: "API layer",
        confidence: 0.85,
        rationale: "Contains a FastAPI app.",
      },
    ],
    generated_by: "code-analyst",
    generated_at: "2026-01-01T00:00:00Z",
  },
};

describe("DependencyMappingPage", () => {
  it("auto-runs the assessment on arrival instead of requiring a second, separate Run click", async () => {
    const fetchMock = mockFetchSequence([
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`, response: [BINDING] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments/binding-1`, response: ASSESSMENT },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments`, response: [] },
    ]);

    renderWithProviders(<DependencyMappingPage />, { sessionId: FIXTURE_SESSION_ID });

    // The assessment results render without the user clicking anything -
    // the user already expressed this intent via "Continue to dependency
    // mapping" on the prior page, so a second, separate "Run" click would
    // be asking for the same thing twice.
    expect(await screen.findByText("Commit pinned")).toBeInTheDocument();
    expect(screen.getAllByText("raviganesh-ai/lumen-grove-demo").length).toBeGreaterThan(0);

    const createCall = fetchMock.mock.calls.find(([input]) =>
      new URL(input.toString()).pathname.endsWith(
        `/sessions/${FIXTURE_SESSION_ID}/repository-assessments/binding-1`,
      ),
    );
    expect(createCall).toBeDefined();
  });

  it("does not re-run automatically when an assessment already exists", async () => {
    const fetchMock = mockFetchSequence([
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`, response: [BINDING] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments`, response: [ASSESSMENT] },
    ]);

    renderWithProviders(<DependencyMappingPage />, { sessionId: FIXTURE_SESSION_ID });

    expect(await screen.findByText("Commit pinned")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run live dependency assessment" })).toBeInTheDocument();

    await waitFor(() => {
      const createCall = fetchMock.mock.calls.find(([input]) =>
        new URL(input.toString()).pathname.endsWith(
          `/sessions/${FIXTURE_SESSION_ID}/repository-assessments/binding-1`,
        ),
      );
      expect(createCall).toBeUndefined();
    });
  });

  it("shows the Genie-generated code summary and component role when present", async () => {
    mockFetchSequence([
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`, response: [BINDING] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments`, response: [ASSESSMENT_WITH_SUMMARY] },
    ]);

    renderWithProviders(<DependencyMappingPage />, { sessionId: FIXTURE_SESSION_ID });

    expect(
      await screen.findByText("This repository implements a FastAPI backend service."),
    ).toBeInTheDocument();
    expect(screen.getByText("Uses FastAPI")).toBeInTheDocument();
    expect(screen.getByText("API layer")).toBeInTheDocument();
    expect(screen.getAllByText("backend").length).toBeGreaterThan(0);
  });

  it("does not render a code summary card when the assessment has none", async () => {
    mockFetchSequence([
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`, response: [BINDING] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments`, response: [ASSESSMENT] },
    ]);

    renderWithProviders(<DependencyMappingPage />, { sessionId: FIXTURE_SESSION_ID });

    expect(await screen.findByText("Commit pinned")).toBeInTheDocument();
    expect(screen.queryByText("Code summary")).not.toBeInTheDocument();
  });

  it("lets the user ask a question about the analyzed repository once code analysis is done", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetchSequence([
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`, response: [BINDING] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments`, response: [ASSESSMENT] },
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments/assessment-1/ask`,
        response: {
          question: "What does the backend depend on?",
          answer: "The backend component declares a dependency on fastapi.",
          referenced_paths: ["backend", "backend/main.py"],
          generated_by: "code-analyst",
          generated_at: "2026-01-02T00:00:00Z",
        },
      },
    ]);

    renderWithProviders(<DependencyMappingPage />, { sessionId: FIXTURE_SESSION_ID });

    expect(await screen.findByText("Ask about this repository")).toBeInTheDocument();
    const input = screen.getByPlaceholderText(/What does the backend component depend on/i);
    await user.type(input, "What does the backend depend on?");
    await user.click(screen.getByRole("button", { name: /^Ask Genie$/ }));

    expect(
      await screen.findByText("The backend component declares a dependency on fastapi."),
    ).toBeInTheDocument();
    expect(screen.getByText("backend/main.py")).toBeInTheDocument();

    const askCall = fetchMock.mock.calls.find(([input]) =>
      new URL(input.toString()).pathname.endsWith(
        `/sessions/${FIXTURE_SESSION_ID}/repository-assessments/assessment-1/ask`,
      ),
    );
    expect(askCall).toBeDefined();
    const [, askInit] = askCall as unknown as [string, RequestInit];
    expect(JSON.parse(askInit.body as string)).toEqual({
      message: "What does the backend depend on?",
    });
  });

  it("hides individual source files by default but reveals them via the toggle, for a large repository", async () => {
    const user = userEvent.setup();
    const sourceFileNodes = Array.from({ length: 40 }, (_, index) => ({
      id: `source_file:${index}`,
      type: "source_file",
      name: `module_${index}.py`,
      version: null,
      path: `backend/module_${index}.py`,
      attributes: {},
    }));
    const largeAssessment = {
      ...ASSESSMENT,
      nodes: [
        {
          id: "component:1",
          type: "component",
          name: "backend",
          version: null,
          path: "backend",
          attributes: {},
        },
        ...sourceFileNodes,
      ],
    };
    mockFetchSequence([
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`, response: [BINDING] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments`, response: [largeAssessment] },
    ]);

    renderWithProviders(<DependencyMappingPage />, { sessionId: FIXTURE_SESSION_ID });

    expect(await screen.findByText("Commit pinned")).toBeInTheDocument();
    // The structural node is always visible, but the 40 individual files
    // default to hidden - without this, a real several-hundred-file
    // repository would render an unboundedly tall single column that
    // breaks ReactFlow's fitView and makes every node invisible.
    expect(screen.getAllByText("backend").length).toBeGreaterThan(0);
    expect(screen.queryByText("module_0.py")).not.toBeInTheDocument();

    const toggle = screen.getByRole("switch", { name: /Show individual source files \(40\)/i });
    expect(toggle).not.toBeChecked();

    await user.click(toggle);

    expect(await screen.findByText("module_0.py")).toBeInTheDocument();
  });
});
