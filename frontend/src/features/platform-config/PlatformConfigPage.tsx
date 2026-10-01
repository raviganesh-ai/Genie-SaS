import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  Combobox,
  Dropdown,
  Field,
  Input,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  Option,
  Text,
  Title2,
} from "@fluentui/react-components";
import { Delete24Regular } from "@fluentui/react-icons";
import { ErrorState } from "@/components/ErrorState";
import { ApiError } from "@/services/httpClient";
import { platformConfigApi } from "@/services/platformConfigApi";
import { repositoryConnectionApi } from "@/services/repositoryConnectionApi";
import type { SafeError } from "@/types/common";
import type { PlatformReferencePurpose, PlatformReferenceRepository } from "@/types/platformConfig";
import type { GitHubMcpConnectionStatus, GitHubRepositorySummary } from "@/types/repositoryConnection";

const PURPOSE_LABELS: Record<PlatformReferencePurpose, string> = {
  architecture: "Architecture",
  standards: "Standards",
};

function pathsFromInput(value: string): string[] {
  return value
    .split(",")
    .map((path) => path.trim())
    .filter(Boolean);
}

/**
 * Platform-level (not session-scoped) configuration: an administrator
 * configures one or more opinionated architecture/standards reference
 * repositories here, once - every future mission's design-architecture
 * step and governed modernization plan then uses them automatically,
 * unless that specific session supplies its own override (see
 * RepositoryConnectionPage's "architecture"/"standards" purpose binding,
 * which still works as a per-session override on top of this default).
 */
export function PlatformConfigPage(): JSX.Element {
  const navigate = useNavigate();
  const [status, setStatus] = useState<GitHubMcpConnectionStatus | null>(null);
  const [repositories, setRepositories] = useState<GitHubRepositorySummary[]>([]);
  const [configured, setConfigured] = useState<PlatformReferenceRepository[]>([]);
  const [selectedRepository, setSelectedRepository] = useState<GitHubRepositorySummary | null>(null);
  const [query, setQuery] = useState("");
  const [purpose, setPurpose] = useState<PlatformReferencePurpose>("architecture");
  const [requestedRef, setRequestedRef] = useState("");
  const [includedPaths, setIncludedPaths] = useState("");
  const [excludedPaths, setExcludedPaths] = useState("");
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [removingId, setRemovingId] = useState<string | null>(null);
  const [error, setError] = useState<SafeError | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [connectionStatus, configuredRepositories] = await Promise.all([
        repositoryConnectionApi.getStatus(),
        platformConfigApi.list(),
      ]);
      setStatus(connectionStatus);
      setConfigured(configuredRepositories);
    } catch (err) {
      setError(err instanceof ApiError ? err : { message: "Unable to load platform configuration." });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!status?.connected) return;
    const timeout = setTimeout(async () => {
      try {
        const page = await repositoryConnectionApi.listRepositories(query.trim() || undefined);
        setRepositories(page.repositories);
      } catch (err) {
        setError(err instanceof ApiError ? err : { message: "Unable to list repositories." });
      }
    }, 400);
    return () => clearTimeout(timeout);
  }, [query, status?.connected]);

  const handleConnect = useCallback(async () => {
    setConnecting(true);
    setError(null);
    try {
      const connection = await repositoryConnectionApi.connect();
      setStatus(connection);
      const page = await repositoryConnectionApi.listRepositories();
      setRepositories(page.repositories);
    } catch (err) {
      setError(err instanceof ApiError ? err : { message: "Unable to connect to GitHub MCP." });
    } finally {
      setConnecting(false);
    }
  }, []);

  const handleAdd = useCallback(async () => {
    if (!selectedRepository || !requestedRef.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const added = await platformConfigApi.add({
        repository: selectedRepository,
        purpose,
        requested_ref: requestedRef.trim(),
        included_paths: pathsFromInput(includedPaths),
        excluded_paths: pathsFromInput(excludedPaths),
      });
      setConfigured((current) => [added, ...current]);
      setSelectedRepository(null);
      setQuery("");
      setRequestedRef("");
      setIncludedPaths("");
      setExcludedPaths("");
    } catch (err) {
      setError(err instanceof ApiError ? err : { message: "Unable to configure this repository." });
    } finally {
      setSaving(false);
    }
  }, [selectedRepository, purpose, requestedRef, includedPaths, excludedPaths]);

  const handleRemove = useCallback(async (repositoryId: string) => {
    setRemovingId(repositoryId);
    setError(null);
    try {
      await platformConfigApi.remove(repositoryId);
      setConfigured((current) => current.filter((item) => item.id !== repositoryId));
    } catch (err) {
      setError(err instanceof ApiError ? err : { message: "Unable to remove this repository." });
    } finally {
      setRemovingId(null);
    }
  }, []);

  const selectedName = selectedRepository?.full_name ?? "";

  return (
    <section className="genie-fade-in repository-intake">
      <div>
        <Title2>Configure</Title2>
        <Text block style={{ opacity: 0.72, marginTop: 6 }}>
          Configure one or more opinionated architecture/standards reference repositories here,
          once - every future mission uses them automatically when designing an architecture or
          generating a governed modernization plan, unless that specific mission supplies its own
          override.
        </Text>
        <Button
          appearance="secondary"
          onClick={() => navigate(-1)}
          aria-label="Close configure panel and return to where you were"
        >
          ✕ Close
        </Button>
      </div>

      <Card className="repository-intake-card">
        <Text weight="semibold" size={400}>1. Connect GitHub</Text>
        <Text size={200} style={{ opacity: 0.72 }}>
          This workspace uses a shared administrator-managed GitHub MCP credential. Selecting
          Connect verifies that identity; Genie never sends its bearer token to this browser.
        </Text>
        {status ? (
          <MessageBar intent={status.connected ? "success" : status.configured ? "info" : "warning"}>
            <MessageBarBody>
              <MessageBarTitle>
                {status.connected ? "Connected" : status.configured ? "Ready to connect" : "Not configured"}
              </MessageBarTitle>
              {status.detail}
            </MessageBarBody>
          </MessageBar>
        ) : null}
        <Button
          appearance="primary"
          disabled={loading || connecting || !status?.configured}
          onClick={() => void handleConnect()}
        >
          {connecting ? "Connecting..." : status?.connected ? "Reconnect GitHub" : "Connect GitHub"}
        </Button>
      </Card>

      <Card className="repository-intake-card">
        <Text weight="semibold" size={400}>2. Add a reference repository</Text>
        <Field label="Repository" required>
          <Combobox
            freeform
            placeholder="Type to filter repositories visible to the connected identity"
            value={selectedName || query}
            selectedOptions={selectedName ? [selectedName] : []}
            disabled={!status?.connected}
            onOptionSelect={(_, data) => {
              const selected =
                repositories.find((repository) => repository.full_name === data.optionValue) ?? null;
              setSelectedRepository(selected);
              setRequestedRef(selected?.default_branch ?? "");
            }}
            onInput={(event) => {
              setSelectedRepository(null);
              setQuery((event.target as HTMLInputElement).value);
            }}
          >
            {repositories.map((repository) => (
              <Option
                key={repository.repository_id}
                value={repository.full_name}
                disabled={repository.archived}
                text={repository.full_name}
              >
                {repository.full_name}{repository.private ? " (private)" : ""}
              </Option>
            ))}
          </Combobox>
        </Field>
        <Field label="Purpose" required>
          <Dropdown
            value={PURPOSE_LABELS[purpose]}
            selectedOptions={[purpose]}
            onOptionSelect={(_, data) => setPurpose(data.optionValue as PlatformReferencePurpose)}
          >
            {Object.entries(PURPOSE_LABELS).map(([value, label]) => (
              <Option key={value} value={value}>{label}</Option>
            ))}
          </Dropdown>
        </Field>
        <Field label="Branch or ref" required hint="Genie resolves this to a 40-character commit SHA.">
          <Input
            value={requestedRef}
            placeholder="main"
            onChange={(_, data) => setRequestedRef(data.value)}
          />
        </Field>
        <Field label="Included paths" hint="Optional comma-separated repository-relative paths.">
          <Input
            value={includedPaths}
            placeholder="docs/architecture"
            onChange={(_, data) => setIncludedPaths(data.value)}
          />
        </Field>
        <Field label="Excluded paths" hint="Optional comma-separated repository-relative paths.">
          <Input
            value={excludedPaths}
            placeholder="vendor, generated"
            onChange={(_, data) => setExcludedPaths(data.value)}
          />
        </Field>
        <Button
          appearance="primary"
          disabled={!selectedRepository || !requestedRef.trim() || saving}
          onClick={() => void handleAdd()}
        >
          {saving ? "Validating and ingesting..." : "Add reference repository"}
        </Button>
      </Card>

      <Card className="repository-intake-card">
        <Text weight="semibold" size={400}>3. Configured reference repositories</Text>
        {configured.length === 0 ? (
          <Text size={200} style={{ opacity: 0.7 }}>No reference repositories are configured yet.</Text>
        ) : (
          <div className="repository-bindings">
            {configured.map((repository) => (
              <div className="repository-binding" key={repository.id}>
                <div>
                  <Text weight="semibold">{PURPOSE_LABELS[repository.purpose]}</Text>
                  <Text block>{repository.repository_full_name}</Text>
                  <Text block size={200} className="repository-commit">
                    {repository.resolved_commit}
                  </Text>
                  <Text block size={200} style={{ opacity: 0.7 }}>
                    {repository.purpose === "standards"
                      ? `${repository.rules.length} rule(s) from ${repository.paths.length} file(s)`
                      : `${repository.paths.length} file(s)`}
                  </Text>
                </div>
                <Badge appearance="filled" color="success">configured</Badge>
                <Button
                  appearance="subtle"
                  shape="circular"
                  icon={<Delete24Regular />}
                  aria-label={`Remove ${repository.repository_full_name}`}
                  title={`Remove ${repository.repository_full_name}`}
                  disabled={removingId !== null}
                  onClick={() => void handleRemove(repository.id)}
                />
              </div>
            ))}
          </div>
        )}
      </Card>

      {error ? <ErrorState error={error} onRetry={() => void load()} /> : null}
    </section>
  );
}
