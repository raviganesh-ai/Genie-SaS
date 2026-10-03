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
            id: "monolith_modularization",
            name: "Monolith to modular monolith",
            description: "Introduce internal module boundaries.",
            target_label: null,
            instruction_template: "Refactor the monolith.",
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
        match: "/platform-config/reference-repositories",
        response: [],
      },
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/modernization`,
        response: [],
      },
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/approvals`,
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
      { match: "/platform-config/reference-repositories", response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/approvals`, response: [] },
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

  it("only enables Execute once the plan's governance approval request is actually approved", async () => {
    const plan = {
      id: "plan-1",
      session_id: FIXTURE_SESSION_ID,
      binding_id: "binding-1",
      assessment_id: "assessment-1",
      repository_full_name: "raviganesh-ai/lumen-grove-demo",
      base_commit: "a".repeat(40),
      base_ref: "main",
      goal: "Upgrade the runtime.",
      capability_id: "runtime_upgrade",
      capability_name: "Language or runtime upgrade",
      target: "Python 3.12",
      summary: "Upgraded the runtime.",
      changes: [{ path: "README.md", content: "Upgraded.", reason: "evidence-backed" }],
      validation_commands: ["pytest"],
      residual_risks: [],
      rollback: "git revert",
      branch_name: "genie/modernize-plan1",
      status: "pending_approval",
      approval_request_id: "approval-1",
      pull_request_url: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };
    const pendingApproval = {
      id: "approval-1",
      checkpoint_id: "modernization-pr-approval",
      session_id: FIXTURE_SESSION_ID,
      trace_id: "trace-1",
      requested_by_agent_id: "build-agent",
      subject_type: "modernization_plan",
      subject_id: "plan-1",
      status: "pending",
      requested_at: "2026-01-01T00:00:00Z",
      expires_at: null,
    };

    mockFetchSequence([
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization/capabilities`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments`, response: [] },
      { match: "/platform-config/reference-repositories", response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization`, response: [plan] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/approvals`, response: [pendingApproval] },
    ]);

    renderWithProviders(<ModernizationPage />, { sessionId: FIXTURE_SESSION_ID });

    expect(await screen.findByText(/Awaiting Governance approval/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Execute after Governance approval/ })).not
      .toBeInTheDocument();
  });

  it("enables Execute once the plan's governance approval request is approved", async () => {
    const plan = {
      id: "plan-1",
      session_id: FIXTURE_SESSION_ID,
      binding_id: "binding-1",
      assessment_id: "assessment-1",
      repository_full_name: "raviganesh-ai/lumen-grove-demo",
      base_commit: "a".repeat(40),
      base_ref: "main",
      goal: "Upgrade the runtime.",
      capability_id: "runtime_upgrade",
      capability_name: "Language or runtime upgrade",
      target: "Python 3.12",
      summary: "Upgraded the runtime.",
      changes: [{ path: "README.md", content: "Upgraded.", reason: "evidence-backed" }],
      validation_commands: ["pytest"],
      residual_risks: [],
      rollback: "git revert",
      branch_name: "genie/modernize-plan1",
      status: "pending_approval",
      approval_request_id: "approval-1",
      pull_request_url: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };
    const approvedApproval = {
      id: "approval-1",
      checkpoint_id: "modernization-pr-approval",
      session_id: FIXTURE_SESSION_ID,
      trace_id: "trace-1",
      requested_by_agent_id: "build-agent",
      subject_type: "modernization_plan",
      subject_id: "plan-1",
      status: "approved",
      requested_at: "2026-01-01T00:00:00Z",
      expires_at: null,
    };

    mockFetchSequence([
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization/capabilities`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments`, response: [] },
      { match: "/platform-config/reference-repositories", response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization`, response: [plan] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/approvals`, response: [approvedApproval] },
    ]);

    renderWithProviders(<ModernizationPage />, { sessionId: FIXTURE_SESSION_ID });

    const executeButton = await screen.findByRole("button", {
      name: /Execute after Governance approval/,
    });
    expect(executeButton).toBeEnabled();
  });
});
