import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  Dropdown,
  Field,
  Input,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  Option,
  Text,
  Textarea,
  Title2,
} from "@fluentui/react-components";
import { ErrorState } from "@/components/ErrorState";
import { ApiError } from "@/services/httpClient";
import { iqApi } from "@/services/iqApi";
import { iqConnectionsApi } from "@/services/iqConnectionsApi";
import { iqDiagnosticsApi } from "@/services/iqDiagnosticsApi";
import { useSessionContext } from "@/state/SessionContext";
import type { SafeError } from "@/types/common";
import {
  DELEGATED_IQ_PROVIDERS,
  type IqEvidenceCandidate,
  type IqProviderName,
  type IqProviderStatus,
  type IqStatus,
} from "@/types/iq";
import type { IqConnectionStatus } from "@/types/iqConnection";
import type { IqDiagnostics, WorkIqValidationResult } from "@/types/iqDiagnostics";

const PROVIDER_LABELS: Record<IqProviderName, string> = {
  work_iq: "Work IQ",
  foundry_iq: "Foundry IQ",
  fabric_iq: "Fabric IQ",
  foundry_mcp: "Microsoft Foundry MCP",
};

const STATUS_LABELS: Record<IqStatus, string> = {
  IQ_AVAILABLE: "Available",
  IQ_NOT_REQUIRED: "Not required",
  IQ_NOT_CONFIGURED: "Not configured",
  IQ_AUTHENTICATION_REQUIRED: "Not connected",
  IQ_CONSENT_REQUIRED: "Consent required",
  IQ_SESSION_EXPIRED: "Connection expired",
  IQ_TENANT_MISMATCH: "Wrong Microsoft tenant",
  IQ_PERMISSION_DENIED: "Permission denied",
  IQ_APPROVAL_REQUIRED: "Approval required",
  IQ_UNAVAILABLE: "Unavailable",
  IQ_TIMEOUT: "Timed out",
  IQ_FAILED: "Failed",
};

const STATUS_COLORS: Record<IqStatus, "success" | "danger" | "warning" | "subtle"> = {
  IQ_AVAILABLE: "success",
  IQ_NOT_REQUIRED: "subtle",
  IQ_NOT_CONFIGURED: "subtle",
  IQ_AUTHENTICATION_REQUIRED: "warning",
  IQ_CONSENT_REQUIRED: "warning",
  IQ_SESSION_EXPIRED: "warning",
  IQ_TENANT_MISMATCH: "danger",
  IQ_PERMISSION_DENIED: "warning",
  IQ_APPROVAL_REQUIRED: "warning",
  IQ_UNAVAILABLE: "danger",
  IQ_TIMEOUT: "danger",
  IQ_FAILED: "danger",
};

const CALLBACK_STATUS_MESSAGES: Record<string, string> = {
  connected: "Connected to Microsoft 365.",
  authentication_required: "Microsoft sign-in did not complete. Try connecting again.",
  consent_required: "Microsoft requires additional consent for this capability.",
  session_expired: "The connection expired before it could complete. Try again.",
  tenant_mismatch: "That Microsoft account belongs to a different tenant than this deployment.",
  permission_denied: "That Microsoft account does not have permission for this capability.",
};

/** The delegated providers (Work IQ, Fabric IQ) connect per-session through
 * a real Microsoft sign-in redirect - this section is deliberately
 * separate from the generic provider list below, which also includes the
 * administrator-managed providers (Foundry IQ, Foundry MCP). */
function ConnectMicrosoft365Section({
  connections,
  working,
  onConnect,
  onDisconnect,
}: {
  connections: IqConnectionStatus[];
  working: boolean;
  onConnect: (provider: IqProviderName) => void;
  onDisconnect: (provider: IqProviderName) => void;
}): JSX.Element | null {
  if (connections.length === 0) return null;

  return (
    <Card className="repository-intake-card">
      <Text weight="semibold" size={400}>
        Connect Microsoft 365
      </Text>
      <Text size={200} style={{ opacity: 0.72 }}>
        Work IQ and Fabric IQ act under your own signed-in Microsoft identity. Genie never sees
        or stores your Microsoft password, and no Microsoft token is ever sent to this browser.
      </Text>
      <div className="dependency-mapping-stats">
        {connections.map((connection) => (
          <Card key={connection.provider}>
            <Text weight="semibold">{PROVIDER_LABELS[connection.provider]}</Text>
            <Badge color={STATUS_COLORS[connection.status]}>
              {STATUS_LABELS[connection.status]}
            </Badge>
            <Text size={200}>
              {connection.connected
                ? `Connected as ${connection.display_name ?? "a Microsoft 365 user"}.`
                : connection.detail}
            </Text>
            {connection.connected ? (
              <Button disabled={working} onClick={() => onDisconnect(connection.provider)}>
                Disconnect
              </Button>
            ) : (
              <Button
                appearance="primary"
                disabled={working}
                onClick={() => onConnect(connection.provider)}
              >
                Connect {PROVIDER_LABELS[connection.provider]}
              </Button>
            )}
          </Card>
        ))}
      </div>
    </Card>
  );
}

/** Development-only diagnostics + the explicit, one-shot Work IQ
 * validation action. The backend returns 404 for both routes outside
 * development/test (see app/api/iq_diagnostics.py) - this component
 * simply stops rendering itself when that happens, so a production
 * deployment never shows a confusing "not found" panel. */
function WorkIqDevelopmentDiagnosticsSection({ sessionId }: { sessionId: string }): JSX.Element | null {
  const [available, setAvailable] = useState(true);
  const [diagnostics, setDiagnostics] = useState<IqDiagnostics | null>(null);
  const [validationResult, setValidationResult] = useState<WorkIqValidationResult | null>(null);
  const [validating, setValidating] = useState(false);
  const [diagnosticsError, setDiagnosticsError] = useState<string | null>(null);

  const loadDiagnostics = useCallback(async () => {
    try {
      setDiagnostics(await iqDiagnosticsApi.diagnostics(sessionId));
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setAvailable(false);
        return;
      }
      setDiagnosticsError(
        err instanceof ApiError ? err.message : "Unable to load IQ diagnostics.",
      );
    }
  }, [sessionId]);

  useEffect(() => {
    void loadDiagnostics();
  }, [loadDiagnostics]);

  const runValidation = useCallback(async () => {
    setValidating(true);
    setDiagnosticsError(null);
    try {
      setValidationResult(await iqDiagnosticsApi.validateWorkIq(sessionId));
      await loadDiagnostics();
    } catch (err) {
      setDiagnosticsError(
        err instanceof ApiError ? err.message : "Work IQ validation request failed.",
      );
    } finally {
      setValidating(false);
    }
  }, [sessionId, loadDiagnostics]);

  if (!available) return null;

  return (
    <Card className="repository-intake-card">
      <Text weight="semibold" size={400}>
        Work IQ development diagnostics
      </Text>
      <Text size={200} style={{ opacity: 0.72 }}>
        Development-only. Never shows a token, secret, or Microsoft 365 content - configuration
        presence and safe status only.
      </Text>
      {diagnostics ? (
        <div className="dependency-mapping-stats">
          <Card>
            <Text size={200}>Work IQ enabled</Text>
            <Badge color={diagnostics.work_iq_enabled ? "success" : "subtle"}>
              {diagnostics.work_iq_enabled ? "Yes" : "No"}
            </Badge>
          </Card>
          <Card>
            <Text size={200}>Tenant / client / redirect configured</Text>
            <Badge
              color={
                diagnostics.tenant_configured &&
                diagnostics.client_configured &&
                diagnostics.redirect_uri_configured
                  ? "success"
                  : "warning"
              }
            >
              {[
                diagnostics.tenant_configured ? "Tenant" : null,
                diagnostics.client_configured ? "Client" : null,
                diagnostics.redirect_uri_configured ? "Redirect" : null,
              ]
                .filter(Boolean)
                .join(", ") || "None"}
            </Badge>
          </Card>
          <Card>
            <Text size={200}>Connected session</Text>
            <Badge color={diagnostics.connected ? "success" : "subtle"}>
              {diagnostics.connected ? "Yes" : "No"}
            </Badge>
          </Card>
          <Card>
            <Text size={200}>MCP initialized / tools discovered</Text>
            <Badge color={diagnostics.mcp_initialized ? "success" : "subtle"}>
              {diagnostics.mcp_initialized
                ? `Yes (${diagnostics.tools_discovered_count ?? 0} tools)`
                : "No"}
            </Badge>
          </Card>
          {diagnostics.last_error_category ? (
            <Card>
              <Text size={200}>Last error category</Text>
              <Badge color="warning">{diagnostics.last_error_category}</Badge>
            </Card>
          ) : null}
        </div>
      ) : null}
      <Button
        appearance="primary"
        disabled={validating || !diagnostics?.connected}
        onClick={() => void runValidation()}
      >
        {validating ? "Running Work IQ validation..." : "Run Work IQ validation"}
      </Button>
      {validationResult ? (
        <Card className="repository-intake-card">
          <div className="dependency-mapping-heading">
            <Text weight="semibold">{validationResult.success ? "Succeeded" : "Failed"}</Text>
            <Badge color={validationResult.success ? "success" : "danger"}>
              {validationResult.error_category ?? "ok"}
            </Badge>
          </div>
          <Text size={200}>Tool invoked: {validationResult.tool_invoked ?? "none"}</Text>
          {validationResult.response_preview ? (
            <pre className="iq-evidence-content">{validationResult.response_preview}</pre>
          ) : null}
          {validationResult.citations.length > 0 ? (
            <Text size={200}>Citations: {validationResult.citations.length}</Text>
          ) : null}
          <Text size={200}>
            Correlation ID: {validationResult.correlation_id} | Duration:{" "}
            {validationResult.duration_ms.toFixed(0)} ms
          </Text>
        </Card>
      ) : null}
      {diagnosticsError ? <Text style={{ color: "#e07070" }}>{diagnosticsError}</Text> : null}
    </Card>
  );
}

export function IqCollaborationPage(): JSX.Element {
  const navigate = useNavigate();
  const { sessionId } = useSessionContext();
  const [searchParams, setSearchParams] = useSearchParams();
  const [providers, setProviders] = useState<IqProviderStatus[]>([]);
  const [connections, setConnections] = useState<IqConnectionStatus[]>([]);
  const [candidates, setCandidates] = useState<IqEvidenceCandidate[]>([]);
  const [provider, setProvider] = useState<IqProviderName>("work_iq");
  const [query, setQuery] = useState("");
  const [sensitivity, setSensitivity] = useState("confidential");
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<SafeError | null>(null);
  const [callbackMessage, setCallbackMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!sessionId) return;
    setError(null);
    try {
      const [providerStatuses, evidenceCandidates, connectionStatuses] = await Promise.all([
        iqApi.providers(),
        iqApi.candidates(sessionId),
        iqConnectionsApi.status(sessionId).catch(() => [] as IqConnectionStatus[]),
      ]);
      setProviders(providerStatuses);
      setCandidates(evidenceCandidates);
      setConnections(connectionStatuses);
      const availableProvider =
        connectionStatuses.find((item) => item.connected)?.provider ??
        providerStatuses.find((item) => item.status === "IQ_AVAILABLE")?.provider;
      if (availableProvider) setProvider(availableProvider);
    } catch (err) {
      setError(err instanceof ApiError ? err : { message: "Unable to load IQ providers." });
    }
  }, [sessionId]);

  useEffect(() => {
    void load();
  }, [load]);

  // Reads the one-time redirect status Genie's backend attaches after the
  // Microsoft sign-in round trip completes (see app/api/iq_connections.py),
  // shows it once, then clears the query string and refreshes connection
  // status - the redirect itself never carries a token, only this status.
  useEffect(() => {
    const status = searchParams.get("iq_connect");
    if (!status) return;
    setCallbackMessage(CALLBACK_STATUS_MESSAGES[status] ?? `Connection status: ${status}`);
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);
        next.delete("iq_connect");
        next.delete("provider");
        return next;
      },
      { replace: true },
    );
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs once per redirect return, not on every load() identity change.
  }, [searchParams]);

  const handleConnect = useCallback(
    (targetProvider: IqProviderName) => {
      if (!sessionId) return;
      // Full browser navigation, not a fetch call - Microsoft's sign-in
      // page must render in this tab. See iqConnectionsApi.buildStartUrl.
      window.location.href = iqConnectionsApi.buildStartUrl(sessionId, targetProvider);
    },
    [sessionId],
  );

  const handleDisconnect = useCallback(
    async (targetProvider: IqProviderName) => {
      if (!sessionId) return;
      setWorking(true);
      setError(null);
      try {
        await iqConnectionsApi.disconnect(sessionId, targetProvider);
        await load();
      } catch (err) {
        setError(err instanceof ApiError ? err : { message: "Unable to disconnect." });
      } finally {
        setWorking(false);
      }
    },
    [sessionId, load],
  );

  const retrieve = useCallback(async () => {
    if (!sessionId || !query.trim()) return;
    setWorking(true);
    setError(null);
    try {
      const candidate = await iqApi.retrieve(
        sessionId,
        provider,
        query.trim(),
        sensitivity.trim(),
      );
      setCandidates((current) => [candidate, ...current]);
    } catch (err) {
      setError(err instanceof ApiError ? err : { message: "Live IQ retrieval failed." });
    } finally {
      setWorking(false);
    }
  }, [sessionId, provider, query, sensitivity]);

  const updateCandidate = useCallback(
    async (candidateId: string, action: "confirm" | "reject" | "promote") => {
      if (!sessionId) return;
      setWorking(true);
      setError(null);
      try {
        const updated =
          action === "promote"
            ? await iqApi.promote(sessionId, candidateId)
            : await iqApi.review(
                sessionId,
                candidateId,
                action === "confirm" ? "confirmed" : "rejected",
              );
        setCandidates((current) =>
          current.map((candidate) => (candidate.id === updated.id ? updated : candidate)),
        );
      } catch (err) {
        setError(err instanceof ApiError ? err : { message: "IQ evidence action failed." });
      } finally {
        setWorking(false);
      }
    },
    [sessionId],
  );

  if (!sessionId) {
    return <ErrorState error={{ message: "Create a session before using IQ collaboration." }} />;
  }

  // A provider can be selected for retrieval once it is genuinely usable -
  // either a delegated provider this session has connected, or a static
  // (administrator-managed) provider the backend reports IQ_AVAILABLE.
  const isProviderReady = (candidate: IqProviderStatus | IqConnectionStatus): boolean =>
    DELEGATED_IQ_PROVIDERS.includes(candidate.provider)
      ? connections.some((item) => item.provider === candidate.provider && item.connected)
      : candidate.status === "IQ_AVAILABLE";

  return (
    <section className="genie-fade-in repository-intake">
      <div>
        <Title2>IQ Collaboration</Title2>
        <Text block style={{ opacity: 0.72, marginTop: 6 }}>
          Retrieve authorized workplace, knowledge, and semantic evidence through validated MCP
          capabilities. Evidence requires human confirmation before shared-memory promotion.
        </Text>
      </div>
      {callbackMessage ? (
        <MessageBar intent={callbackMessage.startsWith("Connected") ? "success" : "warning"}>
          <MessageBarBody>
            <MessageBarTitle>Microsoft 365 connection</MessageBarTitle>
            {callbackMessage}
          </MessageBarBody>
        </MessageBar>
      ) : null}
      <ConnectMicrosoft365Section
        connections={connections}
        working={working}
        onConnect={handleConnect}
        onDisconnect={(targetProvider) => void handleDisconnect(targetProvider)}
      />
      <WorkIqDevelopmentDiagnosticsSection sessionId={sessionId} />
      <div className="dependency-mapping-stats">
        {providers
          .filter((item) => !DELEGATED_IQ_PROVIDERS.includes(item.provider))
          .map((item) => (
            <Card key={item.provider}>
              <Text weight="semibold">{PROVIDER_LABELS[item.provider]}</Text>
              <Badge color={STATUS_COLORS[item.status]}>{STATUS_LABELS[item.status]}</Badge>
              <Text size={200}>{item.detail}</Text>
            </Card>
          ))}
      </div>
      <Card className="repository-intake-card">
        <Field label="Provider" required>
          <Dropdown
            value={PROVIDER_LABELS[provider]}
            selectedOptions={[provider]}
            onOptionSelect={(_, data) => setProvider(data.optionValue as IqProviderName)}
          >
            {providers.map((item) => (
              <Option key={item.provider} value={item.provider} disabled={!isProviderReady(item)}>
                {PROVIDER_LABELS[item.provider]}
              </Option>
            ))}
          </Dropdown>
        </Field>
        <Field label="Evidence purpose or question" required>
          <Textarea value={query} onChange={(_, data) => setQuery(data.value)} />
        </Field>
        <Field label="Sensitivity classification" required>
          <Input
            value={sensitivity}
            onChange={(_, data) => setSensitivity(data.value)}
          />
        </Field>
        <Button
          appearance="primary"
          disabled={working || !query.trim() || !providers.some(isProviderReady)}
          onClick={() => void retrieve()}
        >
          Retrieve live authorized evidence
        </Button>
      </Card>
      {candidates.map((candidate) => (
        <Card className="repository-intake-card" key={candidate.id}>
          <div className="dependency-mapping-heading">
            <Text weight="semibold">{PROVIDER_LABELS[candidate.evidence.provider]}</Text>
            <Badge>{candidate.status}</Badge>
          </div>
          <Text>{candidate.evidence.query}</Text>
          <pre className="iq-evidence-content">
            {JSON.stringify(candidate.evidence.content, null, 2)}
          </pre>
          <Text size={200}>
            Citations: {candidate.evidence.citations.length} | Hash:{" "}
            {candidate.evidence.raw_content_hash}
          </Text>
          <div className="repository-search-row">
            <Button
              disabled={working || candidate.status !== "pending"}
              onClick={() => void updateCandidate(candidate.id, "confirm")}
            >
              Confirm evidence
            </Button>
            <Button
              disabled={working || candidate.status !== "pending"}
              onClick={() => void updateCandidate(candidate.id, "reject")}
            >
              Reject
            </Button>
            <Button
              appearance="primary"
              disabled={working || candidate.status !== "confirmed"}
              onClick={() => void updateCandidate(candidate.id, "promote")}
            >
              Promote to shared memory
            </Button>
          </div>
        </Card>
      ))}
      <Button appearance="secondary" onClick={() => navigate("/modernization")}>
        Continue to Governed Modernization
      </Button>
      {error ? <ErrorState error={error} onRetry={() => void load()} /> : null}
    </section>
  );
}
