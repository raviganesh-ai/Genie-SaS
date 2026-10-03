import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Link, MessageBar, MessageBarBody, Text } from "@fluentui/react-components";
import { AgentActivityAnimation } from "@/components/AgentActivityAnimation";
import { ErrorState } from "@/components/ErrorState";
import { approvalApi } from "@/services/approvalApi";
import { ApiError } from "@/services/httpClient";
import { modernizationApi } from "@/services/modernizationApi";
import type { SafeError } from "@/types/common";
import type { ApprovalRequest } from "@/types/governance";
import type { ModernizationDeployment } from "@/types/modernization";

/**
 * "What's next" for a Rehost/Replatform plan whose pull request has
 * already been opened: Genie proposes a concrete, evidence-grounded Azure
 * Container Apps deployment strategy, asks for a separate governance
 * decision (billable real infrastructure is a distinct decision from the
 * plan's own PR approval), then actually builds the plan's branch in ACR
 * and deploys it, verifying the live app responds before calling it
 * healthy - never just generating a strategy document and stopping.
 */
export function ModernizationDeploymentPanel({
  sessionId,
  planId,
}: {
  sessionId: string;
  planId: string;
}): JSX.Element {
  const [deployment, setDeployment] = useState<ModernizationDeployment | null>(null);
  const [approval, setApproval] = useState<ApprovalRequest | null>(null);
  const [proposing, setProposing] = useState(false);
  const [proposingStartedAt, setProposingStartedAt] = useState<string | null>(null);
  const [requesting, setRequesting] = useState(false);
  const [deciding, setDeciding] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [executingStartedAt, setExecutingStartedAt] = useState<string | null>(null);
  const [error, setError] = useState<SafeError | null>(null);

  const load = useCallback(async () => {
    try {
      const current = await modernizationApi.getDeployment(sessionId, planId);
      setDeployment(current);
      if (current?.approval_request_id) {
        const approvals = await approvalApi.list(sessionId);
        setApproval(approvals.find((item) => item.id === current.approval_request_id) ?? null);
      } else {
        setApproval(null);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err : { message: "Unable to load the deployment." });
    }
  }, [sessionId, planId]);

  useEffect(() => {
    void load();
  }, [load]);

  const proposeStrategy = useCallback(async () => {
    setProposing(true);
    setProposingStartedAt(new Date().toISOString());
    setError(null);
    try {
      const created = await modernizationApi.proposeDeploymentStrategy(sessionId, planId);
      setDeployment(created);
    } catch (err) {
      setError(
        err instanceof ApiError ? err : { message: "Proposing a deployment strategy failed." },
      );
    } finally {
      setProposing(false);
      setProposingStartedAt(null);
    }
  }, [sessionId, planId]);

  const requestDeployment = useCallback(async () => {
    if (!deployment) return;
    setRequesting(true);
    setError(null);
    try {
      await modernizationApi.requestDeployment(sessionId, planId, deployment.id);
      await load();
    } catch (err) {
      setError(
        err instanceof ApiError ? err : { message: "Requesting deployment approval failed." },
      );
    } finally {
      setRequesting(false);
    }
  }, [sessionId, planId, deployment, load]);

  const decideApproval = useCallback(
    async (decision: "approved" | "rejected") => {
      if (!approval) return;
      setDeciding(true);
      setError(null);
      try {
        await approvalApi.decide(sessionId, approval.id, decision);
        await load();
      } catch (err) {
        setError(
          err instanceof ApiError ? err : { message: "Recording the governance decision failed." },
        );
      } finally {
        setDeciding(false);
      }
    },
    [sessionId, approval, load],
  );

  const executeDeployment = useCallback(async () => {
    if (!deployment) return;
    setExecuting(true);
    setExecutingStartedAt(new Date().toISOString());
    setError(null);
    try {
      const updated = await modernizationApi.executeDeployment(sessionId, planId, deployment.id);
      setDeployment(updated);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err
          : { message: "Building and deploying the real Azure Container App failed." },
      );
      // execute_deployment still persists a "failed" status server-side on
      // error (see ModernizationDeploymentService.execute_deployment) -
      // reload so the card reflects that instead of staying stuck on
      // "deploying".
      await load();
    } finally {
      setExecuting(false);
      setExecutingStartedAt(null);
    }
  }, [sessionId, planId, deployment, load]);

  const isApproved = approval?.status === "approved";
  const isRejected = approval?.status === "rejected";

  return (
    <div className="modernization-deployment-panel">
      <Text weight="semibold">What's next: deploy this to Azure</Text>
      <Text size={200} style={{ display: "block", opacity: 0.72 }}>
        Genie can automatically build this plan's branch and run it as a real Azure Container App,
        then verify it actually responds before calling it done. Today this only works for
        Container Apps targets and public GitHub repositories - other hosting targets stay
        strategy-only for now.
      </Text>
      {error ? <ErrorState error={error} /> : null}
      {!deployment ? (
        <>
          <Button appearance="primary" disabled={proposing} onClick={() => void proposeStrategy()}>
            {proposing ? "Proposing a deployment strategy..." : "Propose a deployment strategy"}
          </Button>
          {proposing ? (
            <AgentActivityAnimation
              label="Azure AI Foundry is reading this plan's Dockerfile and proposing a deployment strategy..."
              startedAt={proposingStartedAt}
              fallbackDetail="This can take a little while - this is still working."
            />
          ) : null}
        </>
      ) : (
        <>
          <div className="modernization-deployment-strategy">
            <div className="dependency-mapping-heading">
              <Text weight="semibold">Proposed Azure Container App</Text>
              <Badge>{deployment.status}</Badge>
            </div>
            <Text size={300} block>{deployment.strategy.rationale}</Text>
            <ul style={{ margin: "4px 0 0", paddingLeft: 20 }}>
              <li><Text size={200}>Resource name: {deployment.strategy.resource_app_name}</Text></li>
              <li><Text size={200}>Container port: {deployment.strategy.container_port}</Text></li>
              <li><Text size={200}>Health check: {deployment.strategy.health_check_path}</Text></li>
              <li>
                <Text size={200}>
                  {deployment.strategy.cpu} vCPU / {deployment.strategy.memory}, {deployment.strategy.min_replicas}-{deployment.strategy.max_replicas} replicas
                </Text>
              </li>
            </ul>
            {deployment.strategy.steps.length > 0 ? (
              <ol style={{ margin: "4px 0 0", paddingLeft: 20 }}>
                {deployment.strategy.steps.map((step, index) => (
                  <li key={index}><Text size={200}>{step}</Text></li>
                ))}
              </ol>
            ) : null}
          </div>
          {deployment.status === "strategy_proposed" || deployment.status === "failed" ? (
            <Button appearance="primary" disabled={requesting} onClick={() => void requestDeployment()}>
              {requesting ? "Requesting approval..." : "Request deployment approval"}
            </Button>
          ) : null}
          {deployment.status === "pending_approval" ? (
            <MessageBar intent={isRejected ? "error" : "warning"}>
              <MessageBarBody>
                <Text weight="semibold" block>
                  {isRejected
                    ? "This deployment's governance approval was rejected - it cannot be deployed."
                    : "Your decision is needed before Genie provisions real Azure resources."}
                </Text>
                {!isRejected && !isApproved && approval ? (
                  <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                    <Button
                      appearance="primary"
                      disabled={deciding}
                      onClick={() => void decideApproval("approved")}
                    >
                      Approve and allow deployment
                    </Button>
                    <Button
                      appearance="secondary"
                      disabled={deciding}
                      onClick={() => void decideApproval("rejected")}
                    >
                      Reject
                    </Button>
                  </div>
                ) : null}
                {isApproved ? (
                  <Button
                    appearance="primary"
                    disabled={executing}
                    style={{ marginTop: 8 }}
                    onClick={() => void executeDeployment()}
                  >
                    {executing ? "Deploying..." : "Deploy to Azure Container Apps"}
                  </Button>
                ) : null}
              </MessageBarBody>
            </MessageBar>
          ) : null}
          {executing ? (
            <AgentActivityAnimation
              label="Building the image in Azure Container Registry and deploying it to Container Apps..."
              startedAt={executingStartedAt}
              fallbackDetail="The real build and deploy can take a few minutes - this is still working."
            />
          ) : null}
          {deployment.status === "healthy" && deployment.health_check_url ? (
            <MessageBar intent="success">
              <MessageBarBody>
                <Text weight="semibold" block>This app is live and responding.</Text>
                <Link href={deployment.health_check_url} target="_blank" rel="noreferrer">
                  Open the deployed app
                </Link>
              </MessageBarBody>
            </MessageBar>
          ) : null}
          {deployment.status === "failed" && deployment.error ? (
            <MessageBar intent="error">
              <MessageBarBody>{deployment.error}</MessageBarBody>
            </MessageBar>
          ) : null}
        </>
      )}
    </div>
  );
}
