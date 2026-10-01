import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  Combobox,
  Field,
  Input,
  Link,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  Option,
  Spinner,
  Text,
  Title2,
} from "@fluentui/react-components";
import { ApiError } from "@/services/httpClient";
import { repositoryConnectionApi } from "@/services/repositoryConnectionApi";
import { useSessionContext } from "@/state/SessionContext";
import { ErrorState } from "@/components/ErrorState";
import type { SafeError } from "@/types/common";
import type {
  GitHubMcpConnectionStatus,
  GitHubRepositorySummary,
  RepositoryPurpose,
  RepositoryPurposeBinding,
} from "@/types/repositoryConnection";

const PURPOSE_LABELS: Record<RepositoryPurpose, string> = {
  code: "Code",
  architecture: "Architecture",
  standards: "Standards",
};

function pathsFromInput(value: string): string[] {
  return value
    .split(",")
    .map((path) => path.trim())
    .filter(Boolean);
}

export function RepositoryConnectionPage(): JSX.Element {
  const navigate = useNavigate();
  const { sessionId, missionKind } = useSessionContext();
  // A "Modernize and deliver" mission already told Genie its intent by
  // name on Home - sending it through dependency mapping/standards/IQ
  // first (which exist to *inform* a modernization plan, not to gate it)
  // would be asking it to restate that intent via extra clicks. Go
  // straight to the page that captures what to modernize and to what
  // target; ModernizationPage fills in any missing dependency assessment
  // itself.
  const isModernizationMission = missionKind === "modernize_and_deliver";
  const [status, setStatus] = useState<GitHubMcpConnectionStatus | null>(null);
  const [repositories, setRepositories] = useState<GitHubRepositorySummary[]>([]);
  const [bindings, setBindings] = useState<RepositoryPurposeBinding[]>([]);
  const [selectedRepository, setSelectedRepository] =
    useState<GitHubRepositorySummary | null>(null);
  const [requestedRef, setRequestedRef] = useState("");
  const [includedPaths, setIncludedPaths] = useState("");
  const [excludedPaths, setExcludedPaths] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [searching, setSearching] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<SafeError | null>(null);

  const loadPage = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [connection, existing] = await Promise.all([
        repositoryConnectionApi.getStatus(),
        sessionId ? repositoryConnectionApi.listBindings(sessionId) : Promise.resolve([]),
      ]);
      setStatus(connection);
      setBindings(existing);
    } catch (err) {
      setError(err instanceof ApiError ? err : { message: "Unable to load repository evidence." });
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    void loadPage();
  }, [loadPage]);

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

  const selectedName = selectedRepository?.full_name ?? "";
  const canBind = useMemo(
    () => Boolean(sessionId && selectedRepository && requestedRef.trim() && !saving),
    [sessionId, selectedRepository, requestedRef, saving],
  );

  const handleSearch = useCallback(async () => {
    setSearching(true);
    setError(null);
    try {
      const page = await repositoryConnectionApi.listRepositories(query.trim() || undefined);
      setRepositories(page.repositories);
    } catch (err) {
      setError(err instanceof ApiError ? err : { message: "Unable to list repositories." });
    } finally {
      setSearching(false);
    }
  }, [query]);

  // Auto-filters as the user types - replaces a separate "Search" button
  // next to an already-populated repository list, which was confusing
  // (two controls doing overlapping jobs). Debounced so it doesn't fire a
  // request per keystroke.
  useEffect(() => {
    if (!status?.connected) return;
    const timeout = setTimeout(() => void handleSearch(), 400);
    return () => clearTimeout(timeout);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, status?.connected]);

  const handleRepositorySelect = useCallback(
    (fullName: string) => {
      const selected = repositories.find((repository) => repository.full_name === fullName) ?? null;
      setSelectedRepository(selected);
      setRequestedRef(selected?.default_branch ?? "");
    },
    [repositories],
  );

  const handleBind = useCallback(async () => {
    if (!sessionId || !selectedRepository) return;
    setSaving(true);
    setError(null);
    try {
      const binding = await repositoryConnectionApi.createBinding(sessionId, {
        repository: selectedRepository,
        // Architecture/standards references are now configured once at
        // the platform level (see /configure) - Repository Analysis only
        // ever binds the actual repository being analyzed/modernized.
        purpose: "code",
        requested_ref: requestedRef.trim(),
        included_paths: pathsFromInput(includedPaths),
        excluded_paths: pathsFromInput(excludedPaths),
      });
      setBindings((current) => [
        ...current.filter((item) => item.purpose !== binding.purpose),
        binding,
      ]);
    } catch (err) {
      setError(
        err instanceof ApiError ? err : { message: "Unable to validate and bind the repository." },
      );
    } finally {
      setSaving(false);
    }
  }, [
    sessionId,
    selectedRepository,
    requestedRef,
    includedPaths,
    excludedPaths,
  ]);

  if (!sessionId) {
    return (
      <ErrorState
        error={{ message: "Create a Genie session before configuring repository evidence." }}
        onRetry={() => navigate("/")}
      />
    );
  }

  return (
    <section className="genie-fade-in repository-intake">
      <div>
        <Title2>Repository evidence</Title2>
        <Text block style={{ opacity: 0.72, marginTop: 6 }}>
          Connect the administrator-approved GitHub MCP identity, choose a repository from its
          live repository list, and pin each purpose to an immutable commit before analysis.
        </Text>
      </div>

      <Card className="repository-intake-card">
        <Text weight="semibold" size={400}>1. Connect GitHub</Text>
        <Text size={200} style={{ opacity: 0.7 }}>
          This workspace uses a shared administrator-managed GitHub MCP credential. Selecting
          Connect verifies that identity; Genie never sends its bearer token to this browser.
        </Text>
        {loading ? <Spinner label="Verifying the live connection..." /> : null}
        {status?.connected ? (
          <MessageBar intent="success">
            <MessageBarBody>
              <MessageBarTitle>Connected</MessageBarTitle>
              {status.detail}
            </MessageBarBody>
          </MessageBar>
        ) : null}
        {!loading && !status?.connected && !error ? (
          <MessageBar intent={status?.configured ? "info" : "warning"}>
            <MessageBarBody>
              <MessageBarTitle>{status?.configured ? "Ready to connect" : "Not configured"}</MessageBarTitle>
              {status?.detail ?? "GitHub MCP is not configured."}
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
        <Text weight="semibold" size={400}>2. Select repository</Text>
        <Field label="Repository" required hint={searching ? "Searching..." : undefined}>
          <Combobox
            freeform
            placeholder="Type to filter repositories visible to the connected identity"
            value={selectedName || query}
            selectedOptions={selectedName ? [selectedName] : []}
            disabled={!status?.connected}
            onOptionSelect={(_, data) => handleRepositorySelect(data.optionValue ?? "")}
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
            placeholder="src, docs/architecture"
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
        {selectedRepository ? (
          <Text size={200} style={{ opacity: 0.72 }}>
            Default branch: {selectedRepository.default_branch}.{" "}
            <Link href={selectedRepository.html_url} target="_blank" rel="noreferrer">
              Open repository
            </Link>
          </Text>
        ) : null}
        <Button appearance="primary" disabled={!canBind} onClick={() => void handleBind()}>
          {saving ? "Resolving live commit..." : "Validate and bind repository"}
        </Button>
      </Card>

      <Card className="repository-intake-card">
        <Text weight="semibold" size={400}>3. Confirm immutable evidence</Text>
        {bindings.length === 0 ? (
          <Text size={200} style={{ opacity: 0.7 }}>No repository purposes are bound yet.</Text>
        ) : (
          <div className="repository-bindings">
            {bindings.map((binding) => (
              <div className="repository-binding" key={binding.id}>
                <div>
                  <Text weight="semibold">{PURPOSE_LABELS[binding.purpose]}</Text>
                  <Text block>{binding.repository_full_name}</Text>
                  <Text block size={200} className="repository-commit">
                    {binding.resolved_commit}
                  </Text>
                </div>
                <Badge appearance="filled" color="success">{binding.status}</Badge>
              </div>
            ))}
          </div>
        )}
        <Button
          appearance="secondary"
          disabled={bindings.length === 0}
          onClick={() => navigate(isModernizationMission ? "/modernization" : "/dependency-mapping")}
        >
          {isModernizationMission ? "Continue to modernization plan" : "Continue to dependency mapping"}
        </Button>
      </Card>

      {error ? <ErrorState error={error} onRetry={() => void loadPage()} /> : null}
    </section>
  );
}
