import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { ModernizationPage } from "@/features/modernization/ModernizationPage";
import { mockFetchSequence, renderWithProviders } from "./testUtils";
import { FIXTURE_SESSION_ID } from "./fixtures";

describe("ModernizationPage", () => {
  it("offers only configured capabilities instead of a free-text modernization goal", async () => {
    mockFetchSequence([
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/modernization/capabilities`,
        response: [
          {
            id: "runtime_upgrade",
            name: "Language or runtime upgrade",
            description: "Upgrade a supported runtime.",
            target_label: "Target language or runtime version",
            instruction_template: "Upgrade to {target}.",
          },
          {
            id: "standards_remediation",
            name: "Standards conformance remediation",
            description: "Remediate selected findings.",
            target_label: null,
            instruction_template: "Remediate findings.",
          },
        ],
      },
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`,
        response: [],
      },
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments`,
        response: [],
      },
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/standards`,
        response: [],
      },
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/architecture-reference`,
        response: [],
      },
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/modernization`,
        response: [],
      },
    ]);

    renderWithProviders(<ModernizationPage />, { sessionId: FIXTURE_SESSION_ID });

    expect(await screen.findByLabelText(/Modernization capability/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Target language or runtime version/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Modernization goal")).not.toBeInTheDocument();
    expect(screen.queryByText(/rehost/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/replatform/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/re-architect/i)).not.toBeInTheDocument();
  });

  it("auto-runs a dependency assessment when none exists yet for the bound repository", async () => {
    const binding = {
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
    const assessment = {
      id: "assessment-1",
      session_id: FIXTURE_SESSION_ID,
      binding_id: "binding-1",
      repository_full_name: "raviganesh-ai/lumen-grove-demo",
      commit: "a".repeat(40),
      inventory: {
        file_count: 9,
        analyzed_file_count: 1,
        languages: [],
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

    const fetchMock = mockFetchSequence([
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization/capabilities`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`, response: [binding] },
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments/binding-1`,
        response: assessment,
      },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/standards`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/architecture-reference`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization`, response: [] },
    ]);

    renderWithProviders(<ModernizationPage />, { sessionId: FIXTURE_SESSION_ID });

    await screen.findAllByText("raviganesh-ai/lumen-grove-demo");

    const createCall = fetchMock.mock.calls.find(([input]) =>
      new URL(input.toString()).pathname.endsWith(
        `/sessions/${FIXTURE_SESSION_ID}/repository-assessments/binding-1`,
      ),
    );
    expect(createCall).toBeDefined();
  });
});
