import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  Dropdown,
  Field,
  Input,
  Link,
  MessageBar,
  MessageBarBody,
  Option,
  Text,
  Title2,
} from "@fluentui/react-components";
import { AgentActivityAnimation } from "@/components/AgentActivityAnimation";
import { ErrorState } from "@/components/ErrorState";
import { ModernizationArchitectureGraph } from "@/features/modernization/ModernizationArchitectureGraph";
import { approvalApi } from "@/services/approvalApi";
import { ApiError } from "@/services/httpClient";
import { modernizationApi } from "@/services/modernizationApi";
import { platformConfigApi } from "@/services/platformConfigApi";
import { repositoryConnectionApi } from "@/services/repositoryConnectionApi";
import { standardsApi } from "@/services/standardsApi";
import { useSessionContext } from "@/state/SessionContext";
import type { SafeError } from "@/types/common";
import type { ApprovalRequest } from "@/types/governance";
import type { ModernizationCapability, ModernizationPlan } from "@/types/modernization";
import type { RepositoryAssessment, RepositoryPurposeBinding } from "@/types/repositoryConnection";
import type { ArchitectureReferenceSnapshot, StandardsSnapshot } from "@/types/standards";

/** Capabilities whose target is a bounded, well-known set of Azure
 * services rather than open-ended free text - offering these as a
 * dropdown instead of a text box prevents the customer from typing an
 * unsupported/misspelled value Genie would then have to reject or guess
 * at. Every other capability's target space (a specific framework
 * version, a specific evidenced dependency, ...) has no fixed catalog, so
 * those stay free text. */
const CAPABILITY_TARGET_OPTIONS: Record<string, string[]> = {
  rehost_lift_and_shift: [
    "Azure App Service",
    "Azure Container Apps",
    "Azure Kubernetes Service (AKS)",
    "Azure Functions",
  ],
};

export function ModernizationPage(): JSX.Element {
  const navigate = useNavigate();
  const { sessionId } = useSessionContext();
  const [bindings, setBindings] = useState<RepositoryPurposeBinding[]>([]);
  const [assessments, setAssessments] = useState<RepositoryAssessment[]>([]);
  const [plans, setPlans] = useState<ModernizationPlan[]>([]);
  const [capabilities, setCapabilities] = useState<ModernizationCapability[]>([]);
  // A plan's own `status` stays "pending_approval" for its entire
  // lifetime up to execution - the actual approve/reject decision lives
  // on a separate ApprovalRequest record (see Governance/"Track all
  // phases and evidence"). Fetching these lets the page show each plan's
  // *real* approval state and gate "Execute" on it actually being
  // approved, instead of enabling the button the moment a plan merely
  // requests approval (previously fired at the backend and failed with a
  // 400 - a real, confusing bug found via live testing).
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  // Whether an administrator has configured a platform-level
  // architecture/standards reference (see /configure) - shown read-only so
  // the customer can see Genie is actually using what they configured,
  // instead of a misleading "None - let Genie decide" session-override
  // control that never reflected the platform default (see the bug report
  // this replaced).
  const [platformArchitectureCount, setPlatformArchitectureCount] = useState<number | null>(null);
  const [platformStandardsCount, setPlatformStandardsCount] = useState<number | null>(null);
  const [bindingId, setBindingId] = useState("");
  const [assessmentId, setAssessmentId] = useState("");
  const [capabilityId, setCapabilityId] = useState("");
  const [target, setTarget] = useState("");
  const [working, setWorking] = useState(false);
  // Both the Foundry Build Agent plan-generation call and the subsequent
  // branch/push/PR execution are real, often 30-45+ second operations
  // (confirmed via live testing) - without a visible animation, the only
  // feedback was the button going gray/disabled, which looked frozen/stuck
  // rather than actively working (see the AgentActivityAnimation already
  // used for the auto dependency assessment below, for the same reason).
  // Tracked separately (not just one shared label) so the animation shows
  // up next to whichever action is actually in flight - generation in the
  // form card, execution under the specific plan being executed.
  const [generatingStartedAt, setGeneratingStartedAt] = useState<string | null>(null);
  const [executingPlanId, setExecutingPlanId] = useState<string | null>(null);
  const [executingStartedAt, setExecutingStartedAt] = useState<string | null>(null);
  // Tracks which approval request an inline Approve/Reject click is
  // currently deciding, so the user can make that governance call-to-action
  // directly on this page (see the decide() callback below) instead of
  // needing to understand/navigate to a separate Governance page just to
  // unblock their own plan.
  const [decidingApprovalId, setDecidingApprovalId] = useState<string | null>(null);
  const [assessing, setAssessing] = useState(false);
  const [assessingStartedAt, setAssessingStartedAt] = useState<string | null>(null);
  const [error, setError] = useState<SafeError | null>(null);

  const load = useCallback(async () => {
    if (!sessionId) return;
    setError(null);
    try {
      const [
        allBindings,
        allAssessments,
        allPlans,
        allCapabilities,
        architectureRepos,
        standardsRepos,
        allApprovals,
      ] = await Promise.all([
        repositoryConnectionApi.listBindings(sessionId),
        repositoryConnectionApi.listAssessments(sessionId),
        modernizationApi.list(sessionId),
        modernizationApi.capabilities(sessionId),
        platformConfigApi.list("architecture"),
        platformConfigApi.list("standards"),
        approvalApi.list(sessionId),
      ]);
      setApprovals(allApprovals);
      const codeBindings = allBindings.filter(
        (binding) => binding.purpose === "code" && binding.status === "approved",
      );
      setBindings(codeBindings);
      setPlans(allPlans);
      setCapabilities(allCapabilities);
      setPlatformArchitectureCount(architectureRepos.length);
      setPlatformStandardsCount(standardsRepos.length);
      setBindingId((current) => current || codeBindings[0]?.id || "");
      setCapabilityId((current) => current || allCapabilities[0]?.id || "");
      // A "Modernize and deliver" mission can reach this page straight
      // from Repository Analysis, before anyone has run a dependency
      // assessment on the bound repository. Rather than blocking plan
      // generation on a manual detour through Dependency Mapping for an
      // ask the user already made, run it here automatically the first
      // time it's missing.
      const firstBindingId = codeBindings[0]?.id ?? "";
      if (allAssessments.length === 0 && firstBindingId) {
        setAssessments([]);
        setAssessing(true);
        setAssessingStartedAt(new Date().toISOString());
        try {
          const created = await repositoryConnectionApi.createAssessment(sessionId, firstBindingId);
          setAssessments([created]);
          setAssessmentId((current) => current || created.id);
        } catch (err) {
          setError(
            err instanceof ApiError ? err : { message: "The live repository assessment failed." },
          );
        } finally {
          setAssessing(false);
          setAssessingStartedAt(null);
        }
        return;
      }
      setAssessments(allAssessments);
      setAssessmentId((current) => current || allAssessments[0]?.id || "");
    } catch (err) {
      setError(err instanceof ApiError ? err : { message: "Unable to load modernization data." });
    }
  }, [sessionId]);

  const [sessionArchitectureSnapshot, setSessionArchitectureSnapshot] =
    useState<ArchitectureReferenceSnapshot | null>(null);
  const [sessionStandardsSnapshot, setSessionStandardsSnapshot] = useState<StandardsSnapshot | null>(null);

  const loadSessionOverrides = useCallback(async () => {
    if (!sessionId) return;
    // Independent of `load()` above (never bundled into its Promise.all,
    // and never able to block it) - a session-specific override is
    // supplementary context on top of the platform default, not required
    // for the page to function; see Repository evidence's identical
    // override feature for where these are created.
    try {
      const [archSnapshots, stdSnapshots] = await Promise.all([
        standardsApi.listArchitectureReferenceSnapshots(sessionId),
        standardsApi.listStandardsSnapshots(sessionId),
      ]);
      const latestArch = [...archSnapshots].sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      )[0];
      const latestStd = [...stdSnapshots].sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      )[0];
      setSessionArchitectureSnapshot(latestArch ?? null);
      setSessionStandardsSnapshot(latestStd ?? null);
    } catch {
      setSessionArchitectureSnapshot(null);
      setSessionStandardsSnapshot(null);
    }
  }, [sessionId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void loadSessionOverrides();
  }, [loadSessionOverrides]);

  const generate = useCallback(async () => {
    const capability = capabilities.find((item) => item.id === capabilityId);
    if (
      !sessionId ||
      !bindingId ||
      !assessmentId ||
      !capability ||
      (capability.target_label && !target.trim())
    ) return;
    setWorking(true);
    setGeneratingStartedAt(new Date().toISOString());
    setError(null);
    try {
      const plan = await modernizationApi.generate(sessionId, {
        binding_id: bindingId,
        assessment_id: assessmentId,
        // A session-specific override (see Repository evidence's "Use a
        // different reference for this mission") takes precedence when
        // present; otherwise null correctly falls back to whatever is
        // configured at the platform level (see /configure) - this is
        // never a silent swap, the banner below always shows which one
        // is actually in effect.
        standards_snapshot_id: sessionStandardsSnapshot?.id ?? null,
        capability_id: capability.id,
        target: capability.target_label ? target.trim() : null,
        architecture_reference_snapshot_id: sessionArchitectureSnapshot?.id ?? null,
      });
      setPlans((current) => [plan, ...current]);
    } catch (err) {
      setError(err instanceof ApiError ? err : { message: "Foundry plan generation failed." });
    } finally {
      setWorking(false);
      setGeneratingStartedAt(null);
    }
  }, [
    sessionId,
    bindingId,
    assessmentId,
    capabilities,
    capabilityId,
    target,
    sessionArchitectureSnapshot,
    sessionStandardsSnapshot,
  ]);

  const execute = useCallback(
    async (planId: string) => {
      if (!sessionId) return;
      setWorking(true);
      setExecutingPlanId(planId);
      setExecutingStartedAt(new Date().toISOString());
      setError(null);
      try {
        const plan = await modernizationApi.execute(sessionId, planId);
        setPlans((current) => current.map((item) => (item.id === plan.id ? plan : item)));
      } catch (err) {
        setError(
          err instanceof ApiError
            ? err
            : { message: "Approved branch and pull-request execution failed." },
        );
        // A failed execute still moves the plan server-side (e.g. to
        // "failed" - see ModernizationService.execute_plan's except
        // branch), but the local plans state above is never updated on
        // the error path, so without this the card would keep showing a
        // stale "pending_approval" badge and an enabled Execute button
        // even though retrying would immediately fail again for the same
        // reason. Reload so the displayed state always matches reality.
        void load();
      } finally {
        setWorking(false);
        setExecutingPlanId(null);
        setExecutingStartedAt(null);
      }
    },
    [sessionId, load],
  );

  const decide = useCallback(
    async (approvalId: string, decision: "approved" | "rejected") => {
      if (!sessionId) return;
      setDecidingApprovalId(approvalId);
      setError(null);
      try {
        await approvalApi.decide(sessionId, approvalId, decision);
        await load();
      } catch (err) {
        setError(
          err instanceof ApiError ? err : { message: "Recording the governance decision failed." },
        );
      } finally {
        setDecidingApprovalId(null);
      }
    },
    [sessionId, load],
  );

  if (!sessionId) {
    return <ErrorState error={{ message: "Create a session before modernization." }} />;
  }

  return (
    <section className="genie-fade-in repository-intake">
      <div>
        <Title2>Governed Modernization</Title2>
        <Text block style={{ opacity: 0.72, marginTop: 6 }}>
          Azure AI Foundry generates the plan. Genie requires approval before creating a dedicated
          branch, pushing complete files, or opening a draft pull request.
        </Text>
        <Button appearance="secondary" onClick={() => navigate("/phases")}>
          Track all phases and evidence
        </Button>
      </div>
      <Card className="repository-intake-card">
        <Field label="Code repository">
          <Dropdown
            value={bindings.find((item) => item.id === bindingId)?.repository_full_name ?? ""}
            selectedOptions={bindingId ? [bindingId] : []}
            onOptionSelect={(_, data) => setBindingId(data.optionValue ?? "")}
          >
            {bindings.map((item) => (
              <Option key={item.id} value={item.id}>{item.repository_full_name}</Option>
            ))}
          </Dropdown>
        </Field>
        <Field
          label="Dependency assessment"
          hint={assessing ? "Reading the bound repository live..." : undefined}
        >
          <Dropdown
            value={
              assessing
                ? "Reading immutable repository..."
                : assessments.find((item) => item.id === assessmentId)?.repository_full_name ?? ""
            }
            selectedOptions={assessmentId ? [assessmentId] : []}
            onOptionSelect={(_, data) => setAssessmentId(data.optionValue ?? "")}
            disabled={assessing}
          >
            {assessments.map((item) => (
              <Option key={item.id} value={item.id}>{item.repository_full_name}</Option>
            ))}
          </Dropdown>
        </Field>
        {assessing ? (
          <AgentActivityAnimation
            label="Reading each file live from GitHub..."
            startedAt={assessingStartedAt}
            fallbackDetail="Larger repositories can take several minutes - this is still working."
          />
        ) : null}
        <Field
          label="Standards and architecture reference"
          hint="Configured once for the whole platform in ⚙️ Configure, or overridden per-mission on Repository evidence - this plan always uses whichever is shown below."
        >
          <MessageBar intent={sessionArchitectureSnapshot || platformArchitectureCount ? "success" : "info"}>
            <MessageBarBody>
              {sessionArchitectureSnapshot ? (
                <Text block>
                  Using your own architecture reference for this mission -{" "}
                  {sessionArchitectureSnapshot.repository_full_name} - instead of{" "}
                  {platformArchitectureCount ? `the ${platformArchitectureCount} platform-configured repositor${platformArchitectureCount === 1 ? "y" : "ies"}` : "the platform default"}.
                </Text>
              ) : platformArchitectureCount ? (
                <Text block>
                  Using {platformArchitectureCount} platform-configured architecture reference
                  repositor{platformArchitectureCount === 1 ? "y" : "ies"}.
                </Text>
              ) : (
                <Text block>No architecture reference configured - Genie will apply its own best-practice judgment.</Text>
              )}
              {sessionStandardsSnapshot ? (
                <Text block>
                  Using your own standards reference for this mission -{" "}
                  {sessionStandardsSnapshot.repository_full_name} - instead of{" "}
                  {platformStandardsCount ? `the ${platformStandardsCount} platform-configured repositor${platformStandardsCount === 1 ? "y" : "ies"}` : "the platform default"}.
                </Text>
              ) : platformStandardsCount ? (
                <Text block>
                  Using {platformStandardsCount} platform-configured standards repositor
                  {platformStandardsCount === 1 ? "y" : "ies"}.
                </Text>
              ) : (
                <Text block>No standards repository configured - Genie will apply its own best-practice judgment.</Text>
              )}
            </MessageBarBody>
          </MessageBar>
        </Field>
        <Field
          label="Modernization capability"
          hint={capabilities.find((item) => item.id === capabilityId)?.description}
          required
        >
          <Dropdown
            value={capabilities.find((item) => item.id === capabilityId)?.name ?? ""}
            selectedOptions={capabilityId ? [capabilityId] : []}
            onOptionSelect={(_, data) => {
              setCapabilityId(data.optionValue ?? "");
              setTarget("");
            }}
          >
            {capabilities.map((item) => (
              <Option key={item.id} value={item.id}>{item.name}</Option>
            ))}
          </Dropdown>
        </Field>
        {(() => {
          const selectedCapability = capabilities.find((item) => item.id === capabilityId);
          if (!selectedCapability?.target_label) return null;
          const boundedOptions = CAPABILITY_TARGET_OPTIONS[selectedCapability.id];
          return (
            <Field label={selectedCapability.target_label} required>
              {boundedOptions ? (
                <Dropdown
                  value={target}
                  selectedOptions={target ? [target] : []}
                  onOptionSelect={(_, data) => setTarget(data.optionValue ?? "")}
                >
                  {boundedOptions.map((option) => (
                    <Option key={option} value={option}>{option}</Option>
                  ))}
                </Dropdown>
              ) : (
                <Input value={target} onChange={(_, data) => setTarget(data.value)} />
              )}
            </Field>
          );
        })()}
        <Button
          appearance="primary"
          disabled={
            working ||
            assessing ||
            !bindingId ||
            !assessmentId ||
            !capabilityId ||
            Boolean(
              capabilities.find((item) => item.id === capabilityId)?.target_label &&
              !target.trim(),
            )
          }
          onClick={() => void generate()}
        >
          Generate Foundry modernization plan
        </Button>
        {generatingStartedAt ? (
          <AgentActivityAnimation
            label="Azure AI Foundry is generating the modernization plan..."
            startedAt={generatingStartedAt}
            fallbackDetail="Larger repositories and more complex plans can take several minutes - this is still working."
          />
        ) : null}
      </Card>
      {plans.map((plan) => {
        // A plan's own `status` field stays "pending_approval" for its
        // entire lifetime up to execution (see
        // ModernizationService.execute_plan) - the real approve/reject
        // decision lives on this separate ApprovalRequest, which Execute
        // is actually gated on server-side.
        const approval = approvals.find((item) => item.id === plan.approval_request_id);
        const isApproved = approval?.status === "approved";
        const isRejected = approval?.status === "rejected";
        const isDeciding = decidingApprovalId === approval?.id;
        const cost = plan.estimated_cost;
        const currencyFormatter = cost
          ? new Intl.NumberFormat("en-US", {
              style: "currency",
              currency: cost.currency_code,
              maximumFractionDigits: 2,
            })
          : null;
        const formatCost = (amount: number | null) =>
          amount === null || !currencyFormatter ? "Unavailable" : currencyFormatter.format(amount);
        return (
          <Card className="repository-intake-card" key={plan.id}>
            <div className="dependency-mapping-heading">
              <Text weight="semibold">{plan.summary}</Text>
              <Badge>{plan.status}</Badge>
            </div>
            <Text size={200} className="repository-commit">{plan.base_commit}</Text>
            <Text block>
              {plan.capability_name ?? "Legacy modernization plan"}
              {plan.target ? `: ${plan.target}` : ""}
            </Text>
            {plan.rewrite_strategy ? (
              <div>
                <Text weight="semibold">Rewrite strategy</Text>
                <Text block size={300}>{plan.rewrite_strategy}</Text>
              </div>
            ) : null}
            {plan.proposed_components.length > 0 ? (
              <ModernizationArchitectureGraph components={plan.proposed_components} />
            ) : null}
            {plan.deployment_plan.length > 0 ? (
              <div>
                <Text weight="semibold">Deployment plan</Text>
                <ol style={{ margin: "4px 0 0", paddingLeft: 20 }}>
                  {plan.deployment_plan.map((step, index) => (
                    <li key={index}><Text size={300}>{step}</Text></li>
                  ))}
                </ol>
              </div>
            ) : null}
            {plan.residual_risks.length > 0 ? (
              <div>
                <Text weight="semibold">Constraints and residual risks</Text>
                <ul style={{ margin: "4px 0 0", paddingLeft: 20 }}>
                  {plan.residual_risks.map((risk, index) => (
                    <li key={index}><Text size={300}>{risk}</Text></li>
                  ))}
                </ul>
              </div>
            ) : null}
            {cost ? (
              <div className="modernization-cost">
                <div className="dependency-mapping-heading">
                  <Text weight="semibold">Estimated cost of modernization</Text>
                  <Badge appearance="outline">{cost.coverage} retail pricing coverage</Badge>
                </div>
                <div style={{ display: "flex", gap: 24 }}>
                  <div>
                    <Text size={200} style={{ opacity: 0.72 }}>Estimated monthly</Text>
                    <Text size={500} weight="bold" block>{formatCost(cost.monthly_amount)}</Text>
                  </div>
                  <div>
                    <Text size={200} style={{ opacity: 0.72 }}>Estimated annual</Text>
                    <Text size={500} weight="bold" block>{formatCost(cost.annual_amount)}</Text>
                  </div>
                </div>
                {cost.assumptions.length > 0 ? (
                  <ul style={{ margin: "4px 0 0", paddingLeft: 20 }}>
                    {cost.assumptions.map((assumption, index) => (
                      <li key={index}><Text size={200} style={{ opacity: 0.72 }}>{assumption}</Text></li>
                    ))}
                  </ul>
                ) : null}
                <Text size={200} style={{ opacity: 0.55 }}>
                  Azure consumption estimate only; implementation, support, taxes, and negotiated
                  discounts are excluded.
                </Text>
              </div>
            ) : null}
            <Text>{plan.changes.length} complete file change(s) on {plan.branch_name}</Text>
            {plan.changes.map((change) => (
              <div className="standards-rule" key={change.path}>
                <Badge>file</Badge>
                <div><Text>{change.path}</Text><Text block size={200}>{change.reason}</Text></div>
              </div>
            ))}
            {plan.pull_request_url ? (
              <Link href={plan.pull_request_url} target="_blank" rel="noreferrer">
                Open draft pull request
              </Link>
            ) : plan.status === "pending_approval" && !isApproved ? (
              <MessageBar intent={isRejected ? "error" : "warning"}>
                <MessageBarBody>
                  <Text weight="semibold" block>
                    {isRejected
                      ? "This plan's governance approval was rejected - it cannot be executed."
                      : "Your decision is needed before this plan can be executed."}
                  </Text>
                  {!isRejected && approval ? (
                    <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                      <Button
                        appearance="primary"
                        disabled={isDeciding}
                        onClick={() => void decide(approval.id, "approved")}
                      >
                        Approve and allow execution
                      </Button>
                      <Button
                        appearance="secondary"
                        disabled={isDeciding}
                        onClick={() => void decide(approval.id, "rejected")}
                      >
                        Reject this plan
                      </Button>
                    </div>
                  ) : null}
                  <Text size={200} style={{ display: "block", marginTop: 8 }}>
                    <Link onClick={() => navigate("/phases")}>View the full governance trace</Link>
                  </Text>
                </MessageBarBody>
              </MessageBar>
            ) : (
              <>
                <Button
                  appearance="primary"
                  disabled={working || plan.status !== "pending_approval"}
                  onClick={() => void execute(plan.id)}
                >
                  Execute after Governance approval
                </Button>
                {executingPlanId === plan.id ? (
                  <AgentActivityAnimation
                    label="Creating the branch, pushing files, and opening the draft pull request..."
                    startedAt={executingStartedAt}
                    fallbackDetail="This can take a little while - this is still working."
                  />
                ) : null}
              </>
            )}
          </Card>
        );
      })}
      {error ? <ErrorState error={error} onRetry={() => void load()} /> : null}
    </section>
  );
}
