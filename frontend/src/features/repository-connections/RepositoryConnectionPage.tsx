import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  Combobox,
  Dropdown,
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
import { platformConfigApi } from "@/services/platformConfigApi";
import { repositoryConnectionApi } from "@/services/repositoryConnectionApi";
import { standardsApi } from "@/services/standardsApi";
import { useSessionContext } from "@/state/SessionContext";
import { ErrorState } from "@/components/ErrorState";
import type { SafeError } from "@/types/common";
import type {
  GitHubMcpConnectionStatus,
  GitHubRepositorySummary,
  RepositoryPurpose,
  RepositoryPurposeBinding,
} from "@/types/repositoryConnection";
import type { ArchitectureReferenceSnapshot, StandardsSnapshot } from "@/types/standards";

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

/** Applied when the user leaves "Excluded paths" blank - without this,
 * a real repository's generated/dependency/cache directories (easily
 * hundreds of extra files and directory-listing round-trips) get read
 * just like source code, making an assessment take many times longer
 * than necessary for no analytical benefit. The user can still override
 * this by typing their own excluded paths. */
const DEFAULT_EXCLUDED_PATHS = [
  "node_modules",
  ".git",
  "dist",
  "build",
  "__pycache__",
  ".venv",
  "venv",
  "vendor",
  "target",
  "bin",
  "obj",
  ".pytest_cache",
  ".ruff_cache",
  ".mypy_cache",
];

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

  // Platform-level (/configure) reference repo counts - shown read-only so
  // the customer can see what Genie will actually fall back to for this
  // mission, never a silent default.
  const [platformArchitectureCount, setPlatformArchitectureCount] = useState<number | null>(null);
  const [platformStandardsCount, setPlatformStandardsCount] = useState<number | null>(null);
  // Any session-scoped override already created for THIS mission (most
  // recent snapshot, if more than one was ever ingested) - takes
  // precedence over the platform default, and is always shown alongside
  // it so the effective choice is never hidden.
  const [sessionArchitectureSnapshot, setSessionArchitectureSnapshot] =
    useState<ArchitectureReferenceSnapshot | null>(null);
  const [sessionStandardsSnapshot, setSessionStandardsSnapshot] = useState<StandardsSnapshot | null>(null);
  const [overrideExpanded, setOverrideExpanded] = useState(false);
  const [overridePurpose, setOverridePurpose] = useState<"architecture" | "standards">("architecture");
  const [overrideQuery, setOverrideQuery] = useState("");
  const [overrideSelectedRepository, setOverrideSelectedRepository] =
    useState<GitHubRepositorySummary | null>(null);
  const [overrideRef, setOverrideRef] = useState("");
  const [overrideIncludedPaths, setOverrideIncludedPaths] = useState("");
  const [overrideExcludedPaths, setOverrideExcludedPaths] = useState("");
  const [overrideSaving, setOverrideSaving] = useState(false);
  const [overrideError, setOverrideError] = useState<SafeError | null>(null);

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
    // The architecture/standards reference banner is supplementary, never-
    // blocking context - a failure here (e.g. platform-config or standards
    // being briefly unavailable) must never prevent the core repository-
    // binding flow above from working, so it is intentionally a separate,
    // independently-failing fetch rather than bundled into the same
    // Promise.all as the critical path.
    try {
      const [architectureRepos, standardsRepos, sessionArchSnapshots, sessionStdSnapshots] =
        await Promise.all([
          platformConfigApi.list("architecture"),
          platformConfigApi.list("standards"),
          sessionId ? standardsApi.listArchitectureReferenceSnapshots(sessionId) : Promise.resolve([]),
          sessionId ? standardsApi.listStandardsSnapshots(sessionId) : Promise.resolve([]),
        ]);
      setPlatformArchitectureCount(architectureRepos.length);
      setPlatformStandardsCount(standardsRepos.length);
      const latestArchSnapshot = [...sessionArchSnapshots].sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      )[0];
      const latestStdSnapshot = [...sessionStdSnapshots].sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      )[0];
      setSessionArchitectureSnapshot(latestArchSnapshot ?? null);
      setSessionStandardsSnapshot(latestStdSnapshot ?? null);
    } catch {
      // Supplementary banner only - the core flow above already loaded
      // successfully (or reported its own error) independent of this.
      setPlatformArchitectureCount(null);
      setPlatformStandardsCount(null);
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

  const overrideFilteredRepositories = useMemo(
    () =>
      repositories.filter((repository) =>
        repository.full_name.toLowerCase().includes(overrideQuery.toLowerCase()),
      ),
    [repositories, overrideQuery],
  );
  const overrideSelectedName = overrideSelectedRepository?.full_name ?? "";
  const canBindOverride = useMemo(
    () => Boolean(sessionId && overrideSelectedRepository && overrideRef.trim() && !overrideSaving),
    [sessionId, overrideSelectedRepository, overrideRef, overrideSaving],
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
        excluded_paths:
          pathsFromInput(excludedPaths).length > 0
            ? pathsFromInput(excludedPaths)
            : DEFAULT_EXCLUDED_PATHS,
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

  const handleOverrideRepositorySelect = useCallback(
    (fullName: string) => {
      const selected = repositories.find((repository) => repository.full_name === fullName) ?? null;
      setOverrideSelectedRepository(selected);
      setOverrideRef(selected?.default_branch ?? "");
    },
    [repositories],
  );

  const handleOverrideBind = useCallback(async () => {
    if (!sessionId || !overrideSelectedRepository) return;
    setOverrideSaving(true);
    setOverrideError(null);
    try {
      const binding = await repositoryConnectionApi.createBinding(sessionId, {
        repository: overrideSelectedRepository,
        purpose: overridePurpose,
        requested_ref: overrideRef.trim(),
        included_paths: pathsFromInput(overrideIncludedPaths),
        excluded_paths:
          pathsFromInput(overrideExcludedPaths).length > 0
            ? pathsFromInput(overrideExcludedPaths)
            : DEFAULT_EXCLUDED_PATHS,
      });
      setBindings((current) => [
        ...current.filter((item) => item.purpose !== binding.purpose),
        binding,
      ]);
      if (overridePurpose === "architecture") {
        const snapshot = await standardsApi.ingestArchitectureReference(sessionId, binding.id);
        setSessionArchitectureSnapshot(snapshot);
      } else {
        const snapshot = await standardsApi.ingestStandards(sessionId, binding.id);
        setSessionStandardsSnapshot(snapshot);
      }
      setOverrideSelectedRepository(null);
      setOverrideQuery("");
      setOverrideRef("");
      setOverrideIncludedPaths("");
      setOverrideExcludedPaths("");
    } catch (err) {
      setOverrideError(
        err instanceof ApiError
          ? err
          : { message: "Unable to bind and use this repository for this mission." },
      );
    } finally {
      setOverrideSaving(false);
    }
  }, [
    sessionId,
    overrideSelectedRepository,
    overridePurpose,
    overrideRef,
    overrideIncludedPaths,
    overrideExcludedPaths,
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
        <Field
          label="Excluded paths"
          hint="Optional comma-separated repository-relative paths. Leave blank and Genie skips common noise (node_modules, .git, dist, build, __pycache__, .venv, vendor, and similar) automatically."
        >
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
        <Text weight="semibold" size={400}>3. Architecture &amp; standards reference</Text>
        <MessageBar intent={sessionArchitectureSnapshot ? "success" : platformArchitectureCount ? "info" : "warning"}>
          <MessageBarBody>
            <MessageBarTitle>Architecture reference</MessageBarTitle>
            {sessionArchitectureSnapshot ? (
              <>
                This mission uses your own architecture reference -{" "}
                <strong>{sessionArchitectureSnapshot.repository_full_name}</strong> - instead of{" "}
                {platformArchitectureCount ? `the ${platformArchitectureCount} platform-configured repositor${platformArchitectureCount === 1 ? "y" : "ies"}` : "the platform default"}.
              </>
            ) : platformArchitectureCount ? (
              <>Falls back to your {platformArchitectureCount} platform-configured architecture reference repositor{platformArchitectureCount === 1 ? "y" : "ies"} (see /configure).</>
            ) : (
              <>No architecture reference configured anywhere - Genie will apply its own best-practice judgment.</>
            )}
          </MessageBarBody>
        </MessageBar>
        <MessageBar intent={sessionStandardsSnapshot ? "success" : platformStandardsCount ? "info" : "warning"}>
          <MessageBarBody>
            <MessageBarTitle>Standards reference</MessageBarTitle>
            {sessionStandardsSnapshot ? (
              <>
                This mission uses your own standards reference -{" "}
                <strong>{sessionStandardsSnapshot.repository_full_name}</strong> - instead of{" "}
                {platformStandardsCount ? `the ${platformStandardsCount} platform-configured repositor${platformStandardsCount === 1 ? "y" : "ies"}` : "the platform default"}.
              </>
            ) : platformStandardsCount ? (
              <>Falls back to your {platformStandardsCount} platform-configured standards repositor{platformStandardsCount === 1 ? "y" : "ies"} (see /configure).</>
            ) : (
              <>No standards repository configured anywhere - Genie will apply its own best-practice judgment.</>
            )}
          </MessageBarBody>
        </MessageBar>
        <Button appearance="secondary" onClick={() => setOverrideExpanded((current) => !current)}>
          {overrideExpanded ? "Hide" : "Use a different reference for this mission"}
        </Button>
        {overrideExpanded ? (
          <div className="repository-override-form">
            <Field label="Purpose" required>
              <Dropdown
                value={overridePurpose === "architecture" ? "Architecture" : "Standards"}
                selectedOptions={[overridePurpose]}
                onOptionSelect={(_, data) =>
                  setOverridePurpose((data.optionValue as "architecture" | "standards") ?? "architecture")
                }
              >
                <Option value="architecture">Architecture</Option>
                <Option value="standards">Standards</Option>
              </Dropdown>
            </Field>
            <Field label="Repository" required>
              <Combobox
                freeform
                placeholder="Type to filter repositories visible to the connected identity"
                value={overrideSelectedName || overrideQuery}
                selectedOptions={overrideSelectedName ? [overrideSelectedName] : []}
                disabled={!status?.connected}
                onOptionSelect={(_, data) => handleOverrideRepositorySelect(data.optionValue ?? "")}
                onInput={(event) => {
                  setOverrideSelectedRepository(null);
                  setOverrideQuery((event.target as HTMLInputElement).value);
                }}
              >
                {overrideFilteredRepositories.map((repository) => (
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
            <Field label="Branch or ref" required>
              <Input
                value={overrideRef}
                placeholder="main"
                onChange={(_, data) => setOverrideRef(data.value)}
              />
            </Field>
            <Field label="Included paths" hint="Optional comma-separated repository-relative paths.">
              <Input
                value={overrideIncludedPaths}
                placeholder="docs/architecture"
                onChange={(_, data) => setOverrideIncludedPaths(data.value)}
              />
            </Field>
            <Field label="Excluded paths" hint="Optional comma-separated repository-relative paths.">
              <Input
                value={overrideExcludedPaths}
                placeholder="vendor, generated"
                onChange={(_, data) => setOverrideExcludedPaths(data.value)}
              />
            </Field>
            {overrideError ? <ErrorState error={overrideError} /> : null}
            <Button appearance="primary" disabled={!canBindOverride} onClick={() => void handleOverrideBind()}>
              {overrideSaving ? "Binding and ingesting..." : "Use this repository for this mission"}
            </Button>
          </div>
        ) : null}
      </Card>

      <Card className="repository-intake-card">
        <Text weight="semibold" size={400}>4. Confirm immutable evidence</Text>
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
