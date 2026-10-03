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
    expect(await screen.findByText("failed")).toBeInTheDocument();
  });

  it("shows the rewrite strategy, proposed architecture graph, deployment plan, constraints, and estimated cost", async () => {
    const plan = {
      ...BASE_PLAN,
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

    expect(await screen.findByText("Rewrite strategy")).toBeInTheDocument();
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
