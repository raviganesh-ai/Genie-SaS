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
  Option,
  Text,
  Title2,
} from "@fluentui/react-components";
import { ErrorState } from "@/components/ErrorState";
import { ApiError } from "@/services/httpClient";
import { modernizationApi } from "@/services/modernizationApi";
import { repositoryConnectionApi } from "@/services/repositoryConnectionApi";
import { architectureReferenceApi, standardsApi } from "@/services/standardsApi";
import { useSessionContext } from "@/state/SessionContext";
import type { SafeError } from "@/types/common";
import type { ModernizationCapability, ModernizationPlan } from "@/types/modernization";
import type { RepositoryAssessment, RepositoryPurposeBinding } from "@/types/repositoryConnection";
import type { ArchitectureReferenceSnapshot, StandardsSnapshot } from "@/types/standards";

const NONE_OPTION = "__none__";

export function ModernizationPage(): JSX.Element {
  const navigate = useNavigate();
  const { sessionId } = useSessionContext();
  const [bindings, setBindings] = useState<RepositoryPurposeBinding[]>([]);
  const [assessments, setAssessments] = useState<RepositoryAssessment[]>([]);
  const [snapshots, setSnapshots] = useState<StandardsSnapshot[]>([]);
  const [architectureReferences, setArchitectureReferences] = useState<
    ArchitectureReferenceSnapshot[]
  >([]);
  const [plans, setPlans] = useState<ModernizationPlan[]>([]);
  const [capabilities, setCapabilities] = useState<ModernizationCapability[]>([]);
  const [bindingId, setBindingId] = useState("");
  const [assessmentId, setAssessmentId] = useState("");
  const [snapshotId, setSnapshotId] = useState("");
  const [architectureReferenceId, setArchitectureReferenceId] = useState("");
  const [capabilityId, setCapabilityId] = useState("");
  const [target, setTarget] = useState("");
  const [working, setWorking] = useState(false);
  const [assessing, setAssessing] = useState(false);
  const [error, setError] = useState<SafeError | null>(null);

  const load = useCallback(async () => {
    if (!sessionId) return;
    setError(null);
    try {
      const [
        allBindings,
        allAssessments,
        allSnapshots,
        allArchitectureReferences,
        allPlans,
        allCapabilities,
      ] = await Promise.all([
        repositoryConnectionApi.listBindings(sessionId),
        repositoryConnectionApi.listAssessments(sessionId),
        standardsApi.list(sessionId),
        architectureReferenceApi.list(sessionId),
        modernizationApi.list(sessionId),
        modernizationApi.capabilities(sessionId),
      ]);
      const codeBindings = allBindings.filter(
        (binding) => binding.purpose === "code" && binding.status === "approved",
      );
      setBindings(codeBindings);
      setSnapshots(allSnapshots);
      setArchitectureReferences(allArchitectureReferences);
      setPlans(allPlans);
      setCapabilities(allCapabilities);
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
        }
        return;
      }
      setAssessments(allAssessments);
      setAssessmentId((current) => current || allAssessments[0]?.id || "");
    } catch (err) {
      setError(err instanceof ApiError ? err : { message: "Unable to load modernization data." });
    }
  }, [sessionId]);

  useEffect(() => {
    void load();
  }, [load]);

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
    setError(null);
    try {
      const plan = await modernizationApi.generate(sessionId, {
        binding_id: bindingId,
        assessment_id: assessmentId,
        standards_snapshot_id: snapshotId || null,
        capability_id: capability.id,
        target: capability.target_label ? target.trim() : null,
        architecture_reference_snapshot_id: architectureReferenceId || null,
      });
      setPlans((current) => [plan, ...current]);
    } catch (err) {
      setError(err instanceof ApiError ? err : { message: "Foundry plan generation failed." });
    } finally {
      setWorking(false);
    }
  }, [
    sessionId,
    bindingId,
    assessmentId,
    snapshotId,
    architectureReferenceId,
    capabilities,
    capabilityId,
    target,
  ]);

  const execute = useCallback(
    async (planId: string) => {
      if (!sessionId) return;
      setWorking(true);
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
      } finally {
        setWorking(false);
      }
    },
    [sessionId],
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
        <Field label="Dependency assessment" hint={assessing ? "Reading the bound repository live..." : undefined}>
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
        <Field
          label="Standards snapshot (optional)"
          hint="Your own opinionated standards to apply. Leave as None and Genie applies its own best-practice judgment."
        >
          <Dropdown
            value={
              snapshots.find((item) => item.id === snapshotId)?.repository_full_name ?? "None"
            }
            selectedOptions={[snapshotId || NONE_OPTION]}
            onOptionSelect={(_, data) =>
              setSnapshotId(data.optionValue === NONE_OPTION ? "" : data.optionValue ?? "")
            }
          >
            <Option value={NONE_OPTION}>None - let Genie decide</Option>
            {snapshots.map((item) => (
              <Option key={item.id} value={item.id}>{item.repository_full_name}</Option>
            ))}
          </Dropdown>
        </Field>
        <Field
          label="Architecture reference (optional)"
          hint="Your own opinionated architecture to align with. Leave as None and Genie decides the architecture itself."
        >
          <Dropdown
            value={
              architectureReferences.find((item) => item.id === architectureReferenceId)
                ?.repository_full_name ?? "None"
            }
            selectedOptions={[architectureReferenceId || NONE_OPTION]}
            onOptionSelect={(_, data) =>
              setArchitectureReferenceId(
                data.optionValue === NONE_OPTION ? "" : data.optionValue ?? "",
              )
            }
          >
            <Option value={NONE_OPTION}>None - let Genie decide</Option>
            {architectureReferences.map((item) => (
              <Option key={item.id} value={item.id}>{item.repository_full_name}</Option>
            ))}
          </Dropdown>
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
        {capabilities.find((item) => item.id === capabilityId)?.target_label ? (
          <Field
            label={capabilities.find((item) => item.id === capabilityId)?.target_label}
            required
          >
            <Input value={target} onChange={(_, data) => setTarget(data.value)} />
          </Field>
        ) : null}
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
      </Card>
      {plans.map((plan) => (
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
          ) : (
            <Button
              appearance="primary"
              disabled={working || plan.status !== "pending_approval"}
              onClick={() => void execute(plan.id)}
            >
              Execute after Governance approval
            </Button>
          )}
        </Card>
      ))}
      {error ? <ErrorState error={error} onRetry={() => void load()} /> : null}
    </section>
  );
}
