import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
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
  created_at: "2026-01-01T00:00:00Z",
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
});
