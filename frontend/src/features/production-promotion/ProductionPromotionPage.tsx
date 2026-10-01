import { useCallback, useEffect, useState } from "react";
import {
  Badge,
  Button,
  Card,
  Field,
  Input,
  MessageBar,
  MessageBarBody,
  Text,
  Title2,
} from "@fluentui/react-components";
import { ErrorState } from "@/components/ErrorState";
import { approvalApi } from "@/services/approvalApi";
import { deployLaunchApi } from "@/services/deployLaunchApi";
import { ApiError } from "@/services/httpClient";
import { productionPromotionApi } from "@/services/productionPromotionApi";
import { useSessionContext } from "@/state/SessionContext";
import type { SafeError } from "@/types/common";
import type { ProductionPromotion } from "@/types/productionPromotion";

export function ProductionPromotionPage(): JSX.Element {
  const { sessionId } = useSessionContext();
  const [deploymentRunId, setDeploymentRunId] = useState("");
  const [resourceGroupName, setResourceGroupName] = useState("");
  const [backendAppName, setBackendAppName] = useState("");
  const [healthUrl, setHealthUrl] = useState("");
  const [promotions, setPromotions] = useState<ProductionPromotion[]>([]);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<SafeError | null>(null);

  const load = useCallback(async () => {
    if (!sessionId) return;
    setError(null);
    try {
      const [runs, records] = await Promise.all([
        deployLaunchApi.list(sessionId),
        productionPromotionApi.list(sessionId),
      ]);
      const completedRun = runs.find((run) => run.status === "completed");
      setDeploymentRunId((value) => value || completedRun?.id || "");
      setPromotions(records);
    } catch (err) {
      setError(err instanceof ApiError ? err : { message: "Unable to load promotion state." });
    }
  }, [sessionId]);

  useEffect(() => {
    void load();
  }, [load]);

  const perform = useCallback(
    async (operation: () => Promise<ProductionPromotion>) => {
      setWorking(true);
      setError(null);
      try {
        await operation();
        await load();
      } catch (err) {
        setError(err instanceof ApiError ? err : { message: "Production operation failed." });
      } finally {
        setWorking(false);
      }
    },
    [load],
  );

  if (!sessionId) {
    return <ErrorState error={{ message: "Create a session before production promotion." }} />;
  }

  return (
    <div className="genie-fade-in">
      <Title2>Production promotion</Title2>
      <Text block>
        Register the protected Container App target, rehearse against live evidence, approve the
        release, then shift canary traffic with automatic rollback.
      </Text>
      {error ? (
        <MessageBar intent="error">
          <MessageBarBody>{error.message}</MessageBarBody>
        </MessageBar>
      ) : null}
      <Card style={{ marginTop: 16 }}>
        <Field label="Completed non-production run id">
          <Input value={deploymentRunId} readOnly />
        </Field>
        <Field label="Configured production resource group">
          <Input
            value={resourceGroupName}
            onChange={(_, data) => setResourceGroupName(data.value)}
          />
        </Field>
        <Field label="Production backend Container App name">
          <Input value={backendAppName} onChange={(_, data) => setBackendAppName(data.value)} />
        </Field>
        <Field label="Production health URL">
          <Input value={healthUrl} onChange={(_, data) => setHealthUrl(data.value)} />
        </Field>
        <Button
          appearance="primary"
          disabled={
            working ||
            !deploymentRunId ||
            !resourceGroupName.trim() ||
            !backendAppName.trim() ||
            !healthUrl.trim()
          }
          onClick={() =>
            void perform(() =>
              productionPromotionApi.create(sessionId, {
                deployment_run_id: deploymentRunId,
                resource_group_name: resourceGroupName.trim(),
                backend_app_name: backendAppName.trim(),
                health_url: healthUrl.trim(),
              }),
            )
          }
        >
          Register live production target
        </Button>
      </Card>
      {promotions.map((promotion) => (
        <Card key={promotion.id} style={{ marginTop: 16 }}>
          <Text weight="semibold">{promotion.backend_app_name}</Text>
          <Badge appearance="outline">{promotion.status}</Badge>
          <Text block>{promotion.health_url}</Text>
          {promotion.rollback_detail ? (
            <MessageBar intent="error">
              <MessageBarBody>{promotion.rollback_detail}</MessageBarBody>
            </MessageBar>
          ) : null}
          {promotion.status === "draft" ? (
            <Button
              disabled={working}
              onClick={() =>
                void perform(() => productionPromotionApi.rehearse(sessionId, promotion.id))
              }
            >
              Run live rehearsal and request approval
            </Button>
          ) : null}
          {promotion.status === "pending_approval" && promotion.approval_request_id ? (
            <Button
              disabled={working}
              onClick={() =>
                void (async () => {
                  setWorking(true);
                  try {
                    await approvalApi.decide(
                      sessionId,
                      promotion.approval_request_id ?? "",
                      "approved",
                      "Human production promotion decision.",
                    );
                    await perform(() =>
                      productionPromotionApi.promote(sessionId, promotion.id),
                    );
                  } catch (err) {
                    setError(
                      err instanceof ApiError
                        ? err
                        : { message: "Production approval or promotion failed." },
                    );
                    setWorking(false);
                  }
                })()
              }
            >
              Approve and execute canary
            </Button>
          ) : null}
        </Card>
      ))}
    </div>
  );
}

