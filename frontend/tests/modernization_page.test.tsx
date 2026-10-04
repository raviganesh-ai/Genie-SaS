import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ModernizationPage } from "@/features/modernization/ModernizationPage";
import { mockFetchSequence, renderWithProviders } from "./testUtils";
import { FIXTURE_SESSION_ID } from "./fixtures";

const BASE_PLAN = {
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
  rewrite_strategy: "Upgrade in place; no architectural change is required.",
  proposed_components: [],
  deployment_plan: ["Merge the draft pull request after review.", "Deploy as usual."],
  changes: [{ path: "README.md", content: "Upgraded.", reason: "evidence-backed" }],
  validation_commands: ["pytest"],
  residual_risks: [],
  rollback: "git revert",
  pricing_queries: [],
  estimated_cost: null,
  branch_name: "genie/modernize-plan1",
  status: "pending_approval",
  approval_request_id: "approval-1",
  pull_request_url: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

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
            name: "Monolith to modular",
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

  it("scopes the dependency assessment to the currently bound repository after a rebind, instead of an old superseded repository's assessment", async () => {
    // Regression test for a real bug found via live UI testing: after a
    // session's "code" purpose binding was rebound from one repository to
    // another, the first repository's binding became "superseded" (and
    // correctly dropped out of the "Code repository" dropdown) but its
    // dependency assessment stayed selected/visible in the "Dependency
    // assessment" dropdown, since that list was never filtered to match
    // the active binding - risking a plan silently generated against the
    // wrong repository's evidence.
    const supersededBinding = {
      id: "binding-1",
      session_id: FIXTURE_SESSION_ID,
      owner_user_id: "owner-1",
      repository_id: 1,
      repository_full_name: "raviganesh-ai/demo-fake-py3.9",
      repository_url: "https://github.com/raviganesh-ai/demo-fake-py3.9",
      purpose: "code",
      requested_ref: "main",
      resolved_commit: "a".repeat(40),
      included_paths: [],
      excluded_paths: [],
      principal: "raviganesh-ai",
      status: "superseded",
      validated_at: "2026-01-01T00:00:00Z",
      created_at: "2026-01-01T00:00:00Z",
    };
    const activeBinding = {
      ...supersededBinding,
      id: "binding-2",
      repository_id: 2,
      repository_full_name: "raviganesh-ai/sample-fake-java",
      repository_url: "https://github.com/raviganesh-ai/sample-fake-java",
      status: "approved",
      created_at: "2026-01-02T00:00:00Z",
    };
    const staleAssessment = {
      id: "assessment-1",
      session_id: FIXTURE_SESSION_ID,
      binding_id: "binding-1",
      repository_full_name: "raviganesh-ai/demo-fake-py3.9",
      commit: "a".repeat(40),
      inventory: {
        file_count: 3,
        analyzed_file_count: 3,
        languages: [],
        manifest_paths: [],
        infrastructure_paths: [],
        workflow_paths: [],
        test_paths: [],
      },
      nodes: [],
      edges: [],
      coverage_gaps: [],
      created_at: "2026-01-01T00:05:00Z",
    };
    const freshAssessment = {
      ...staleAssessment,
      id: "assessment-2",
      binding_id: "binding-2",
      repository_full_name: "raviganesh-ai/sample-fake-java",
      created_at: "2026-01-02T00:05:00Z",
    };

    const fetchMock = mockFetchSequence([
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization/capabilities`, response: [] },
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`,
        response: [supersededBinding, activeBinding],
      },
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments/binding-2`,
        response: freshAssessment,
      },
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments`,
        response: [staleAssessment],
      },
      { match: "/platform-config/reference-repositories", response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/approvals`, response: [] },
    ]);

    renderWithProviders(<ModernizationPage />, { sessionId: FIXTURE_SESSION_ID });

    // The only selectable "Code repository" is the active (non-superseded)
    // binding.
    expect(await screen.findAllByText("raviganesh-ai/sample-fake-java")).not.toHaveLength(0);
    expect(screen.queryByText("raviganesh-ai/demo-fake-py3.9")).not.toBeInTheDocument();

    // A fresh assessment must have been triggered for the *active* binding,
    // never reusing the superseded repository's stale assessment.
    const createCall = fetchMock.mock.calls.find(([input]) =>
      new URL(input.toString()).pathname.endsWith(
        `/sessions/${FIXTURE_SESSION_ID}/repository-assessments/binding-2`,
      ),
    );
    expect(createCall).toBeDefined();
  });

  it("only enables Execute once the plan's governance approval request is actually approved", async () => {
    const plan = { ...BASE_PLAN };
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

    expect(await screen.findByText(/Your decision is needed/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Approve and allow execution/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Reject this plan/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Execute after Governance approval/ })).not
      .toBeInTheDocument();
  });

  it("lets the user approve the plan inline without leaving the page", async () => {
    const user = userEvent.setup();
    const plan = { ...BASE_PLAN };
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
    const approvedApproval = { ...pendingApproval, status: "approved" };

    mockFetchSequence([
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization/capabilities`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments`, response: [] },
      { match: "/platform-config/reference-repositories", response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization`, response: [plan] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/approvals`, response: [pendingApproval] },
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/approvals/approval-1/decide`,
        response: { id: "decision-1", request_id: "approval-1", decision: "approved" },
      },
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization`, response: [plan] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/approvals`, response: [approvedApproval] },
    ]);

    renderWithProviders(<ModernizationPage />, { sessionId: FIXTURE_SESSION_ID });

    const approveButton = await screen.findByRole("button", { name: /Approve and allow execution/ });
    await user.click(approveButton);

    expect(
      await screen.findByRole("button", { name: /Execute after Governance approval/ }),
    ).toBeEnabled();
  });

  it("enables Execute once the plan's governance approval request is approved", async () => {
    const plan = { ...BASE_PLAN };
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

  it("refreshes the plan's displayed state after a failed execute instead of leaving it looking stale", async () => {
    const user = userEvent.setup();
    const plan = { ...BASE_PLAN };
    const failedPlan = { ...plan, status: "failed" };
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
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization`, response: [failedPlan] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/approvals`, response: [approvedApproval] },
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/modernization/plan-1/execute`,
        response: { message: "Modernization plan requires an approved governance decision." },
        status: 400,
      },
    ]);

    renderWithProviders(<ModernizationPage />, { sessionId: FIXTURE_SESSION_ID });

    const executeButton = await screen.findByRole("button", {
      name: /Execute after Governance approval/,
    });
    await user.click(executeButton);

    // The plan card must reflect the server's real post-failure state
    // (reloaded via load()), not keep showing the stale "pending_approval"
    // badge and an enabled Execute button that would just fail again.
    // ("Failed" - human-readable via formatPlanStatus, not the raw
    // "failed" status string, which used to render as unlabeled,
    // oddly-wrapped badge text - see ModernizationPage's status badge fix.)
    expect(await screen.findByText("Failed")).toBeInTheDocument();
  });

  it("shows the rewrite strategy, proposed architecture graph, deployment plan, constraints, and estimated cost", async () => {
    const plan = {
      ...BASE_PLAN,
      // Matches this test's modularization-flavored content below
      // (billing/notifications module boundaries) so the "Rewrite
      // strategy" heading (capability-specific - see
      // rewriteStrategyLabel) is the one actually asserted.
      capability_id: "monolith_modularization",
      rewrite_strategy: "Introduce module boundaries along billing/notifications coupling.",
      proposed_components: [
        {
          id: "billing-module",
          name: "Billing module",
          responsibility: "Owns invoicing and payment logic.",
          extracted: false,
          depends_on: [],
        },
        {
          id: "notifications-service",
          name: "Notifications service",
          responsibility: "Sends transactional emails independently of billing load.",
          extracted: true,
          depends_on: ["billing-module"],
        },
      ],
      deployment_plan: ["Ship behind a feature flag.", "Run the strangler proxy in shadow mode."],
      residual_risks: ["Requires a backward-compatible database migration window."],
      // A real estimated_cost is always derived from at least one
      // pricing_queries entry - an empty array (this fixture's default)
      // means "no Azure cost impact", which the page now renders as a
      // reassuring note instead of this cost card (see
      // ModernizationPage's pricing_queries.length === 0 branch).
      pricing_queries: [
        {
          service_name: "Virtual Machines",
          retail_service_name: "Virtual Machines",
          product_name: "Standard_D2s_v5",
          arm_region_name: "eastus",
          sku_name: "Standard_D2s_v5",
          meter_name: "D2s v5 Compute Hours",
          unit_of_measure: "1 Hour",
          units_per_month: 730,
          assumption: "One always-on P1v3 instance.",
        },
      ],
      estimated_cost: {
        currency_code: "USD",
        region: "eastus",
        monthly_amount: 42.5,
        annual_amount: 510,
        coverage: "complete",
        assumptions: ["One always-on P1v3 instance."],
        source_urls: [],
        retrieved_at: "2026-01-01T00:00:00Z",
      },
    };

    mockFetchSequence([
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization/capabilities`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments`, response: [] },
      { match: "/platform-config/reference-repositories", response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization`, response: [plan] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/approvals`, response: [] },
    ]);

    renderWithProviders(<ModernizationPage />, { sessionId: FIXTURE_SESSION_ID });

    expect(await screen.findByText("Rewrite strategy")).toBeInTheDocument();
    expect(
      screen.getByText("Introduce module boundaries along billing/notifications coupling."),
    ).toBeInTheDocument();
    expect(screen.getByText("Proposed architecture")).toBeInTheDocument();
    expect(
      screen.getByText((_, element) => element?.textContent === "Billing module\nModule"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        (_, element) => element?.textContent === "Notifications service\nExtracted service",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Deployment plan")).toBeInTheDocument();
    expect(screen.getByText("Ship behind a feature flag.")).toBeInTheDocument();
    expect(screen.getByText("Constraints and residual risks")).toBeInTheDocument();
    expect(
      screen.getByText("Requires a backward-compatible database migration window."),
    ).toBeInTheDocument();
    expect(screen.getByText("Estimated cost of modernization")).toBeInTheDocument();
    expect(screen.getByText("$42.50")).toBeInTheDocument();
    expect(screen.getByText("$510.00")).toBeInTheDocument();
  });

  it("shows a reassuring no-cost note instead of 'Unavailable' when the plan has no pricing queries", async () => {
    // BASE_PLAN's pricing_queries is empty, matching a capability like
    // monolith_modularization that doesn't change what's deployed - this
    // must read as "nothing to price", not as a failed pricing lookup.
    const plan = { ...BASE_PLAN };

    mockFetchSequence([
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization/capabilities`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments`, response: [] },
      { match: "/platform-config/reference-repositories", response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization`, response: [plan] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/approvals`, response: [] },
    ]);

    renderWithProviders(<ModernizationPage />, { sessionId: FIXTURE_SESSION_ID });

    expect(await screen.findByText("Estimated cost of modernization")).toBeInTheDocument();
    expect(
      screen.getByText(/No additional Azure cost expected/i),
    ).toBeInTheDocument();
    expect(screen.queryByText("Unavailable")).not.toBeInTheDocument();
    expect(screen.queryByText(/retail pricing coverage/i)).not.toBeInTheDocument();
  });

  it("labels the rewrite_strategy section differently per capability, since each is a genuinely different operation", async () => {
    const cases: Array<[string | null, string]> = [
      ["rehost_lift_and_shift", "Migration strategy"],
      ["dependency_upgrade", "Dependency upgrade rationale"],
      ["strategy_recommendation", "Recommendation rationale"],
      [null, "Strategy rationale"],
    ];

    for (const [capabilityId, expectedLabel] of cases) {
      const plan = { ...BASE_PLAN, capability_id: capabilityId };

      mockFetchSequence([
        { match: `/sessions/${FIXTURE_SESSION_ID}/modernization/capabilities`, response: [] },
        { match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`, response: [] },
        { match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments`, response: [] },
        { match: "/platform-config/reference-repositories", response: [] },
        { match: `/sessions/${FIXTURE_SESSION_ID}/modernization`, response: [plan] },
        { match: `/sessions/${FIXTURE_SESSION_ID}/approvals`, response: [] },
      ]);

      const { unmount } = renderWithProviders(<ModernizationPage />, {
        sessionId: FIXTURE_SESSION_ID,
      });

      expect(await screen.findByText(expectedLabel)).toBeInTheDocument();
      unmount();
    }
  });

  it("shows a clearly-labeled illustrative estimate when the plan has no pricing queries but a resolved baseline", async () => {
    const plan = {
      ...BASE_PLAN,
      pricing_queries: [],
      illustrative_pricing_queries: [
        {
          service_name: "Azure Container Apps",
          arm_region_name: "eastus",
          units_per_month: 730,
          assumption: "One small always-on single-replica container app.",
        },
      ],
      estimated_cost: {
        currency_code: "USD",
        region: "eastus",
        monthly_amount: 12.3,
        annual_amount: 147.6,
        coverage: "complete",
        assumptions: ["One small always-on single-replica container app."],
        source_urls: [],
        retrieved_at: "2026-01-01T00:00:00Z",
        is_illustrative: true,
      },
    };

    mockFetchSequence([
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization/capabilities`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments`, response: [] },
      { match: "/platform-config/reference-repositories", response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization`, response: [plan] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/approvals`, response: [] },
    ]);

    renderWithProviders(<ModernizationPage />, { sessionId: FIXTURE_SESSION_ID });

    expect(await screen.findByText("$12.30")).toBeInTheDocument();
    expect(screen.getByText("$147.60")).toBeInTheDocument();
    expect(screen.getByText(/Illustrative baseline - not a quote/i)).toBeInTheDocument();
    expect(
      screen.getByText(/best-effort estimate of what a typical deployment/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/No additional Azure cost expected/i)).not.toBeInTheDocument();
  });

  it("does not double-number a deployment plan step that already has its own leading ordinal", async () => {
    const plan = {
      ...BASE_PLAN,
      deployment_plan: ["1. Create the module packages.", "2. Move the shared kernel interfaces."],
    };

    mockFetchSequence([
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization/capabilities`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments`, response: [] },
      { match: "/platform-config/reference-repositories", response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization`, response: [plan] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/approvals`, response: [] },
    ]);

    renderWithProviders(<ModernizationPage />, { sessionId: FIXTURE_SESSION_ID });

    expect(await screen.findByText("Create the module packages.")).toBeInTheDocument();
    expect(screen.getByText("Move the shared kernel interfaces.")).toBeInTheDocument();
    expect(screen.queryByText(/^1\.\s*1\./)).not.toBeInTheDocument();
    expect(screen.queryByText("1. Create the module packages.")).not.toBeInTheDocument();
  });

  it("collapses the file-change list behind a toggle once it exceeds the threshold", async () => {
    const changes = Array.from({ length: 9 }, (_, index) => ({
      path: `src/main/java/com/example/Module${index}.java`,
      content: "unused in this test",
      reason: `Relocated class ${index}.`,
    }));
    const plan = { ...BASE_PLAN, changes };

    mockFetchSequence([
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization/capabilities`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments`, response: [] },
      { match: "/platform-config/reference-repositories", response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization`, response: [plan] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/approvals`, response: [] },
    ]);

    const user = userEvent.setup();
    renderWithProviders(<ModernizationPage />, { sessionId: FIXTURE_SESSION_ID });

    expect(await screen.findByText("9 complete file change(s) on genie/modernize-plan1")).toBeInTheDocument();
    expect(screen.getByText("Module0.java", { exact: false })).toBeInTheDocument();
    expect(screen.queryByText("Module8.java", { exact: false })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Show all 9 file changes/i }));
    expect(await screen.findByText("Module8.java", { exact: false })).toBeInTheDocument();
  });

  it("omits the proposed architecture graph when the plan has no components to show", async () => {
    const plan = { ...BASE_PLAN, proposed_components: [] };

    mockFetchSequence([
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization/capabilities`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments`, response: [] },
      { match: "/platform-config/reference-repositories", response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization`, response: [plan] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/approvals`, response: [] },
    ]);

    renderWithProviders(<ModernizationPage />, { sessionId: FIXTURE_SESSION_ID });

    // BASE_PLAN's capability_id is "runtime_upgrade" -> its own tailored
    // heading (see rewriteStrategyLabel), not the generic "Rewrite
    // strategy" text reserved for monolith_modularization.
    expect(await screen.findByText("Runtime upgrade rationale")).toBeInTheDocument();
    expect(screen.queryByText("Proposed architecture")).not.toBeInTheDocument();
  });

  it("lets the user ask a grounded question about an already-generated plan", async () => {
    const user = userEvent.setup();
    const plan = { ...BASE_PLAN };

    const fetchMock = mockFetchSequence([
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization/capabilities`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments`, response: [] },
      { match: "/platform-config/reference-repositories", response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization`, response: [plan] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/approvals`, response: [] },
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/modernization/plan-1/ask`,
        response: {
          question: "Why was this approach chosen?",
          answer: "Because no architectural change was required for a runtime upgrade.",
          referenced_fields: ["rewrite_strategy"],
          generated_at: "2026-01-02T00:00:00Z",
        },
      },
    ]);

    renderWithProviders(<ModernizationPage />, { sessionId: FIXTURE_SESSION_ID });

    const input = await screen.findByPlaceholderText(/Why was the notifications service extracted/i);
    await user.type(input, "Why was this approach chosen?");
    await user.click(screen.getByRole("button", { name: /^Ask Genie$/ }));

    expect(
      await screen.findByText("Because no architectural change was required for a runtime upgrade."),
    ).toBeInTheDocument();
    expect(screen.getByText("rewrite_strategy")).toBeInTheDocument();

    const askCall = fetchMock.mock.calls.find(([input]) =>
      new URL(input.toString()).pathname.endsWith(
        `/sessions/${FIXTURE_SESSION_ID}/modernization/plan-1/ask`,
      ),
    );
    expect(askCall).toBeDefined();
  });

  it("lets the user refine a plan with free-text feedback, producing an additional plan", async () => {
    const user = userEvent.setup();
    const plan = { ...BASE_PLAN };
    const refinedPlan = {
      ...BASE_PLAN,
      id: "plan-2",
      summary: "Upgraded the runtime, keeping retries unchanged.",
      // Distinct from BASE_PLAN's rewrite_strategy so the two plans'
      // content is distinguishable below - otherwise both cards would
      // contain identical text and the collapse assertion couldn't tell
      // which card it actually came from.
      rewrite_strategy: "Keep the existing retry wrapper; only bump the interpreter version.",
      previous_plan_id: "plan-1",
      refinement_notes: "Keep the existing retry behavior unchanged.",
      // Distinct from BASE_PLAN's single README.md change so the diff
      // against the previous plan has something real to show.
      changes: [
        { path: "README.md", content: "Upgraded.", reason: "evidence-backed" },
        { path: "src/retry/RetryPolicy.java", content: "Unchanged logic.", reason: "Preserved as requested." },
      ],
    };

    const fetchMock = mockFetchSequence([
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization/capabilities`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments`, response: [] },
      { match: "/platform-config/reference-repositories", response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization`, response: [plan] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/approvals`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization`, response: refinedPlan },
    ]);

    renderWithProviders(<ModernizationPage />, { sessionId: FIXTURE_SESSION_ID });

    const input = await screen.findByPlaceholderText(/Why was the notifications service extracted/i);
    await user.type(input, "Keep the existing retry behavior unchanged.");
    await user.click(screen.getByRole("button", { name: /Refine this plan/i }));

    expect(
      await screen.findByText("Upgraded the runtime, keeping retries unchanged."),
    ).toBeInTheDocument();

    const generateCall = fetchMock.mock.calls.find(([input, init]) => {
      const matchesUrl = new URL(input.toString()).pathname.endsWith(
        `/sessions/${FIXTURE_SESSION_ID}/modernization`,
      );
      return matchesUrl && (init as RequestInit | undefined)?.method === "POST";
    });
    expect(generateCall).toBeDefined();
    const [, generateInit] = generateCall as unknown as [string, RequestInit];
    const body = JSON.parse(generateInit.body as string);
    expect(body.previous_plan_id).toBe("plan-1");
    expect(body.refinement_notes).toBe("Keep the existing retry behavior unchanged.");

    // The latest (expanded) plan shows a real "what changed" summary -
    // the user's own refinement feedback plus a concrete file diff -
    // instead of requiring the user to mentally compare two full cards.
    expect(await screen.findByText("What changed in this refinement")).toBeInTheDocument();
    expect(
      screen.getByText('Requested: "Keep the existing retry behavior unchanged."'),
    ).toBeInTheDocument();
    expect(
      screen.getAllByText(
        (_, element) => element?.textContent === "Added: src/retry/RetryPolicy.java",
      ).length,
    ).toBeGreaterThan(0);

    // The superseded original plan (BASE_PLAN) collapses by default - its
    // own content must not still be on the page, which is what made the
    // "whole analysis just repeats" (real user feedback).
    expect(
      screen.queryByText("Upgrade in place; no architectural change is required."),
    ).not.toBeInTheDocument();
    // Real user feedback: the old generic "superseded by a newer
    // refinement" note was an unhelpful repeat with no actual content -
    // it's replaced with the same concrete refinement reason and a file
    // diff summary (one file added here, relative to BASE_PLAN's single
    // unmodified README.md).
    expect(
      screen.getByText(
        'Refined because: "Keep the existing retry behavior unchanged." - 1 file(s) added.',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/kept here for governance history/i)).not.toBeInTheDocument();

    // Real user feedback: collapsing only the analysis content but still
    // showing each plan's own governance decision box looked like
    // "repeat of controls" - exactly one decision box (the latest plan's)
    // may be visible while the superseded one is collapsed.
    expect(screen.getAllByText(/Your decision is needed/i)).toHaveLength(1);

    // It stays fully inspectable on demand, though - this is governance
    // history, not deleted data.
    await user.click(screen.getByRole("button", { name: /Show details/i }));
    expect(
      await screen.findByText("Upgrade in place; no architectural change is required."),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/Your decision is needed/i)).toHaveLength(2);
  });

  it("never labels an older, unrelated plan for a different repository/capability as 'superseded' just because a newer plan exists elsewhere in the session", async () => {
    // Regression test for a real bug found via live UI testing: a plan is
    // only a "refinement" of another plan when explicitly linked via
    // previous_plan_id (the user clicked "Refine this plan"). Two
    // independent plans for two different repositories/capabilities that
    // happen to coexist in the same session have no such relationship -
    // the older one must stay fully expanded, not get mislabeled
    // "Superseded by a newer refinement of this plan".
    const nodeDepsPlan = {
      ...BASE_PLAN,
      id: "plan-node-deps",
      repository_full_name: "raviganesh-ai/demo-fake-node-deps",
      capability_id: "dependency_upgrade",
      capability_name: "Dependency upgrade or replacement",
      target: "Replace request/request-promise with axios",
      summary: "Replace deprecated request and request-promise dependencies with axios.",
      pull_request_url: "https://github.com/raviganesh-ai/demo-fake-node-deps/pull/2",
      status: "pull_request_opened",
      created_at: "2026-01-01T00:00:00Z",
    };
    const monolithPlan = {
      ...BASE_PLAN,
      id: "plan-monolith",
      repository_full_name: "raviganesh-ai/fake-monolith",
      capability_id: "monolith_modularization",
      capability_name: "Monolith to modular",
      target: null,
      summary: "Refactor the monolith into a modular monolith with customer/product/order modules.",
      created_at: "2026-01-02T00:00:00Z",
    };

    mockFetchSequence([
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization/capabilities`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments`, response: [] },
      { match: "/platform-config/reference-repositories", response: [] },
      // Newest-first, same ordering ModernizationPage relies on elsewhere.
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization`, response: [monolithPlan, nodeDepsPlan] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/approvals`, response: [] },
    ]);

    renderWithProviders(<ModernizationPage />, { sessionId: FIXTURE_SESSION_ID });

    expect(
      await screen.findByText(
        "Refactor the monolith into a modular monolith with customer/product/order modules.",
      ),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("Replace deprecated request and request-promise dependencies with axios."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Superseded by a newer refinement/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/kept here for governance history/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Show details/i })).not.toBeInTheDocument();
  });

  it("shows the inline Approve/Reject decision immediately after generating a plan, without a full page reload", async () => {
    const user = userEvent.setup();
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
    const capability = {
      id: "monolith_modularization",
      name: "Monolith to modular",
      description: "Introduce internal module boundaries.",
      target_label: null,
      instruction_template: "Refactor the monolith.",
    };
    const newPlan = { ...BASE_PLAN, capability_id: "monolith_modularization" };
    const newApproval = {
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
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization/capabilities`, response: [capability] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`, response: [binding] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments`, response: [assessment] },
      { match: "/platform-config/reference-repositories", response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/approvals`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization`, response: newPlan },
      { match: `/sessions/${FIXTURE_SESSION_ID}/approvals`, response: [newApproval] },
    ]);

    renderWithProviders(<ModernizationPage />, { sessionId: FIXTURE_SESSION_ID });

    const generateButton = await screen.findByRole("button", {
      name: /Generate Foundry modernization plan/,
    });
    await user.click(generateButton);

    // Previously, the page's `approvals` state was only ever populated
    // once on initial load() - the brand-new approval request this plan
    // creates never appeared without a full page reload, so the
    // Approve/Reject buttons silently failed to render even though a
    // decision was in fact needed.
    expect(
      await screen.findByRole("button", { name: /Approve and allow execution/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Reject this plan/ })).toBeInTheDocument();
  });

  it("shows capability-specific post-PR guidance for upgrades and strategy recommendation, not the deployment panel", async () => {
    const cases: Array<[string, string]> = [
      ["runtime_upgrade", "already contains the real runtime/language upgrade"],
      ["framework_upgrade", "already contains the real framework upgrade"],
      ["dependency_upgrade", "already contains the real dependency upgrade"],
      ["strategy_recommendation", "adds a single MODERNIZATION_STRATEGY.md analysis document"],
    ];

    for (const [capabilityId, expectedText] of cases) {
      const plan = {
        ...BASE_PLAN,
        capability_id: capabilityId,
        status: "pull_request_opened",
        pull_request_url: "https://github.com/raviganesh-ai/lumen-grove-demo/pull/3",
      };

      mockFetchSequence([
        { match: `/sessions/${FIXTURE_SESSION_ID}/modernization/capabilities`, response: [] },
        { match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`, response: [] },
        { match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments`, response: [] },
        { match: "/platform-config/reference-repositories", response: [] },
        { match: `/sessions/${FIXTURE_SESSION_ID}/modernization`, response: [plan] },
        { match: `/sessions/${FIXTURE_SESSION_ID}/approvals`, response: [] },
      ]);

      const { unmount } = renderWithProviders(<ModernizationPage />, {
        sessionId: FIXTURE_SESSION_ID,
      });

      expect(await screen.findByText(new RegExp(expectedText, "i"))).toBeInTheDocument();
      // Neither the real-deployment panel nor the walkthrough checklist
      // applies to these capabilities - only the guidance text should
      // explain what happens next.
      expect(screen.queryByText(/Deploy to Azure Container Apps/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/walk through this modularization/i)).not.toBeInTheDocument();
      unmount();
    }
  });

  it("lets the user propose, approve, and execute a real Container Apps deployment for an opened rehost plan", async () => {
    const user = userEvent.setup();
    const plan = {
      ...BASE_PLAN,
      capability_id: "rehost_lift_and_shift",
      capability_name: "Rehost to Azure (lift-and-shift)",
      target: "Azure Container Apps",
      status: "pull_request_opened",
      pull_request_url: "https://github.com/raviganesh-ai/lumen-grove-demo/pull/1",
    };
    const strategy = {
      resource_app_name: "lumen-grove",
      container_port: 8080,
      health_check_path: "/",
      environment_variables: [],
      cpu: 0.5,
      memory: "1Gi",
      min_replicas: 1,
      max_replicas: 3,
      steps: ["Build the image.", "Deploy to Container Apps."],
      rationale: "Dockerfile exposes 8080 with no evidenced health endpoint.",
    };
    const proposedDeployment = {
      id: "deployment-1",
      session_id: FIXTURE_SESSION_ID,
      plan_id: "plan-1",
      strategy,
      status: "strategy_proposed",
      approval_request_id: null,
      image_tag: null,
      container_app_fqdn: null,
      health_check_url: null,
      error: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };
    const pendingDeployment = {
      ...proposedDeployment,
      status: "pending_approval",
      approval_request_id: "deploy-approval-1",
    };
    const pendingDeployApproval = {
      id: "deploy-approval-1",
      checkpoint_id: "modernization-deployment-approval",
      session_id: FIXTURE_SESSION_ID,
      trace_id: "trace-2",
      requested_by_agent_id: "build-agent",
      subject_type: "modernization_deployment",
      subject_id: "deployment-1",
      status: "pending",
      requested_at: "2026-01-01T00:00:00Z",
      expires_at: null,
    };
    const approvedDeployApproval = { ...pendingDeployApproval, status: "approved" };
    const healthyDeployment = {
      ...pendingDeployment,
      status: "healthy",
      image_tag: "acr123.azurecr.io/lumen-grove:plan-1-a",
      container_app_fqdn: "lumen-grove.example.azurecontainerapps.io",
      health_check_url: "https://lumen-grove.example.azurecontainerapps.io/",
    };

    mockFetchSequence([
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization/capabilities`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments`, response: [] },
      { match: "/platform-config/reference-repositories", response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization`, response: [plan] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/approvals`, response: [] },
      { match: "/modernization/plan-1/deployment", response: null },
      {
        match: "/modernization/plan-1/deployment-strategy",
        response: proposedDeployment,
      },
      {
        match: "/modernization/plan-1/deployment/deployment-1/request",
        response: pendingDeployment,
      },
      { match: "/modernization/plan-1/deployment", response: pendingDeployment },
      { match: `/sessions/${FIXTURE_SESSION_ID}/approvals`, response: [pendingDeployApproval] },
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/approvals/deploy-approval-1/decide`,
        response: { id: "decision-2", request_id: "deploy-approval-1", decision: "approved" },
      },
      { match: "/modernization/plan-1/deployment", response: pendingDeployment },
      { match: `/sessions/${FIXTURE_SESSION_ID}/approvals`, response: [approvedDeployApproval] },
      {
        match: "/modernization/plan-1/deployment/deployment-1/execute",
        response: healthyDeployment,
      },
    ]);

    renderWithProviders(<ModernizationPage />, { sessionId: FIXTURE_SESSION_ID });

    const proposeButton = await screen.findByRole("button", {
      name: /Propose a deployment strategy/,
    });
    await user.click(proposeButton);

    expect(await screen.findByText(/Resource name: lumen-grove/)).toBeInTheDocument();

    const requestButton = await screen.findByRole("button", {
      name: /Request deployment approval/,
    });
    await user.click(requestButton);

    const approveButton = await screen.findByRole("button", {
      name: /Approve and allow deployment/,
    });
    await user.click(approveButton);

    const deployButton = await screen.findByRole("button", {
      name: /Deploy to Azure Container Apps/,
    });
    await user.click(deployButton);

    expect(await screen.findByText("This app is live and responding.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open the deployed app/ })).toHaveAttribute(
      "href",
      "https://lumen-grove.example.azurecontainerapps.io/",
    );
  });

  it("shows a local walkthrough checklist instead of a real deployment panel for an opened modularization plan", async () => {
    const plan = {
      ...BASE_PLAN,
      capability_id: "monolith_modularization",
      capability_name: "Monolith to modular",
      target: null,
      status: "pull_request_opened",
      pull_request_url: "https://github.com/raviganesh-ai/lumen-grove-demo/pull/2",
      deployment_plan: ["Ship behind a feature flag.", "Run the strangler proxy in shadow mode."],
    };

    mockFetchSequence([
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization/capabilities`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments`, response: [] },
      { match: "/platform-config/reference-repositories", response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/modernization`, response: [plan] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/approvals`, response: [] },
    ]);

    renderWithProviders(<ModernizationPage />, { sessionId: FIXTURE_SESSION_ID });

    expect(
      await screen.findByText(/What's next: walk through this modularization/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: /Ship behind a feature flag\./ }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/What's next: deploy this to Azure/)).not.toBeInTheDocument();
  });
});
