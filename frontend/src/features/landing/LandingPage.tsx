import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Badge, Button, Dropdown, Input, Option, Text } from "@fluentui/react-components";
import { Delete24Regular } from "@fluentui/react-icons";
import { sessionApi } from "@/services/sessionApi";
import { modelCatalogApi } from "@/services/modelCatalogApi";
import { discoveryApi } from "@/services/discoveryApi";
import { ApiError } from "@/services/httpClient";
import { useSessionContext, type MissionKind } from "@/state/SessionContext";
import { ErrorState } from "@/components/ErrorState";
import type { SafeError } from "@/types/common";
import type { DiscoveryCase } from "@/types/discovery";

type Destination = "/upload" | "/discovery" | "/repository-connections" | "/architecture-studio";

/**
 * What Genie can do, as actual clickable starting points rather than
 * separate "find it in..." prose next to a disconnected set of generic
 * buttons. Each card both explains the capability and *is* the action -
 * clicking one creates a session, records what the user actually asked
 * for (`kind`, read by AppShell to show only the mission-flow steps that
 * apply - see SessionContext.MissionKind), and goes straight to where
 * that work happens.
 */
const CAPABILITIES: Array<{
  kind: MissionKind;
  icon: string;
  title: string;
  description: string;
  destination: Destination;
}> = [
  {
    kind: "discover_requirements",
    icon: "📝",
    title: "Validate your Vision",
    description:
      "Turn transcripts, recordings, documents, and conversations into traceable requirements.",
    destination: "/upload",
  },
  {
    kind: "understand_code",
    icon: "🔗",
    title: "Understand code",
    description:
      "Connect GitHub and map dependencies, integrations, context, standards, and change impact.",
    destination: "/repository-connections",
  },
  {
    kind: "discover_requirements",
    icon: "🏗️",
    title: "Discover a solution",
    description:
      "Turn customer evidence into a persona-led, costed Azure solution and a runnable prototype.",
    destination: "/discovery",
  },
  {
    kind: "modernize_and_deliver",
    icon: "♻️",
    title: "Modernize and deliver",
    description:
      "Generate governed modernization plans, implementation changes, and draft pull requests for an existing repository.",
    destination: "/repository-connections",
  },
];

function defaultSessionTitle(): string {
  return `Session ${new Date().toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })}`;
}

/**
 * Landing page: create or resume a Genie session. This is the single entry
 * point that establishes `sessionId` in SessionContext for every other page.
 */
export function LandingPage(): JSX.Element {
  const navigate = useNavigate();
  const { setSessionId, setMissionKind, setSelectedModelDeploymentRef } = useSessionContext();
  const [title, setTitle] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<SafeError | null>(null);
  const [models, setModels] = useState<string[]>([]);
  const [loadingModels, setLoadingModels] = useState(true);
  const [modelsError, setModelsError] = useState<SafeError | null>(null);
  const [selectedModel, setSelectedModel] = useState<string | null>(null);
  const [savedDiscoveries, setSavedDiscoveries] = useState<DiscoveryCase[]>([]);
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    setLoadingModels(true);
    modelCatalogApi
      .getAvailable()
      .then((catalog) => {
        if (!mounted) return;
        setModels(catalog.available_models);
        setSelectedModel(catalog.default_model);
      })
      .catch((err) => {
        if (!mounted) return;
        setModelsError(err instanceof ApiError ? err : { message: "Unable to load available models." });
      })
      .finally(() => {
        if (mounted) setLoadingModels(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    let mounted = true;
    discoveryApi
      .list()
      .then((cases) => {
        if (mounted) setSavedDiscoveries(cases);
      })
      .catch(() => undefined);
    return () => {
      mounted = false;
    };
  }, []);

  const handleCreate = useCallback(async (destination: Destination, kind: MissionKind) => {
    setCreating(true);
    setError(null);
    try {
      // A session name is a nice-to-have, not a precondition for acting -
      // auto-name it so clicking a capability always works immediately.
      const session = await sessionApi.create(title.trim() || defaultSessionTitle());
      setSessionId(session.id);
      setMissionKind(kind);
      setSelectedModelDeploymentRef(selectedModel);
      navigate(destination);
    } catch (err) {
      setError(err instanceof ApiError ? err : { message: "Unable to create a session." });
    } finally {
      setCreating(false);
    }
  }, [title, selectedModel, setSelectedModelDeploymentRef, setSessionId, setMissionKind, navigate]);

  const handleDeleteDiscovery = useCallback(async (item: DiscoveryCase) => {
    setDeletingSessionId(item.session_id);
    setError(null);
    try {
      await discoveryApi.delete(item.session_id);
      setSavedDiscoveries((cases) => cases.filter((saved) => saved.id !== item.id));
    } catch (err) {
      setError(err instanceof ApiError ? err : { message: "Unable to delete Discovery." });
    } finally {
      setDeletingSessionId(null);
    }
  }, []);

  return (
    <div className="genie-fade-in" style={{ maxWidth: 820, margin: "8vh auto", textAlign: "center" }}>
      <Text
        weight="bold"
        size={900}
        style={{
          display: "block",
          backgroundImage: "linear-gradient(135deg, #6ba3ea 0%, #a3c4f3 100%)",
          backgroundClip: "text",
          WebkitBackgroundClip: "text",
          color: "transparent",
          letterSpacing: -0.5,
        }}
      >
        Genie
      </Text>
      <Text size={400} style={{ display: "block", opacity: 0.85, marginTop: 6, marginBottom: 8 }}>
        Your Agentic Experience Center
      </Text>
      <Text size={300} style={{ display: "block", opacity: 0.65, marginBottom: 24 }}>
        Choose what you want Genie to do. Each option starts a mission and takes you straight there.
      </Text>

      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 10,
          alignItems: "center",
          justifyContent: "center",
          marginBottom: 24,
        }}
      >
        <Input
          placeholder="Name this session (optional)"
          value={title}
          onChange={(_, data) => setTitle(data.value)}
          style={{ width: 240 }}
        />
        <Dropdown
          placeholder={loadingModels ? "Loading models..." : "Select a model"}
          value={selectedModel ?? ""}
          selectedOptions={selectedModel ? [selectedModel] : []}
          disabled={loadingModels || models.length === 0 || creating}
          onOptionSelect={(_, data) => setSelectedModel(data.optionValue ?? null)}
          style={{ width: 200 }}
        >
          {models.map((model) => (
            <Option key={model} value={model}>
              {model}
            </Option>
          ))}
        </Dropdown>
        {creating ? (
          <Text size={200} style={{ opacity: 0.7 }}>
            Creating session...
          </Text>
        ) : null}
      </div>

      <section style={{ textAlign: "left" }} aria-labelledby="genie-capabilities">
        <Text id="genie-capabilities" weight="semibold" size={500} block>
          What Genie can do
        </Text>
        <Text size={200} style={{ opacity: 0.7 }} block>
          Click any card to start there - you can open other steps from the sidebar as your mission unlocks them.
        </Text>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
            gap: 12,
            marginTop: 14,
          }}
        >
          {CAPABILITIES.map((capability) => (
            <button
              key={capability.title}
              type="button"
              disabled={creating}
              onClick={() => void handleCreate(capability.destination, capability.kind)}
              style={{
                padding: 16,
                borderRadius: 10,
                border: "1px solid #232a33",
                backgroundColor: "rgba(19, 25, 33, 0.45)",
                textAlign: "left",
                cursor: creating ? "not-allowed" : "pointer",
                fontFamily: "inherit",
                color: "inherit",
                transition: "border-color 120ms ease, transform 120ms ease",
              }}
              onMouseEnter={(event) => {
                event.currentTarget.style.borderColor = "#2f83e0";
              }}
              onMouseLeave={(event) => {
                event.currentTarget.style.borderColor = "#232a33";
              }}
            >
              <span style={{ fontSize: 22 }} aria-hidden="true">
                {capability.icon}
              </span>
              <Text weight="semibold" size={300} block style={{ marginTop: 6 }}>
                {capability.title}
              </Text>
              <Text size={200} style={{ opacity: 0.75, display: "block", marginTop: 6 }}>
                {capability.description}
              </Text>
            </button>
          ))}
        </div>
      </section>

      {modelsError ? <ErrorState error={modelsError} /> : null}
      {error ? <ErrorState error={error} /> : null}

      {savedDiscoveries.length > 0 ? (
        <section style={{ marginTop: 32, textAlign: "left", borderTop: "1px solid #232a33", paddingTop: 20 }}>
          <Text weight="semibold" size={400}>Resume Discover Requirements</Text>
          <div style={{ display: "grid", gap: 8, marginTop: 12 }}>
            {savedDiscoveries.map((item) => (
              <div
                key={item.id}
                style={{
                  display: "grid",
                  gridTemplateColumns: "minmax(0, 1fr) auto auto",
                  alignItems: "center",
                  gap: 12,
                  padding: "12px 0",
                  borderBottom: "1px solid #232a33",
                }}
              >
                <div>
                  <Text weight="semibold" style={{ display: "block" }}>
                    Discover Requirements revision {item.analysis_revision}
                  </Text>
                  <Text size={200} style={{ opacity: 0.7 }}>
                    Updated {new Date(item.updated_at).toLocaleString()} · {item.source_upload_ids.length} source file(s)
                  </Text>
                </div>
                <Badge appearance="outline">{item.status.replace(/_/g, " ")}</Badge>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <Button
                    disabled={deletingSessionId === item.session_id}
                    onClick={() => {
                      setSessionId(item.session_id);
                      setMissionKind("discover_requirements");
                      setSelectedModelDeploymentRef(item.model_deployment_ref);
                      navigate("/discovery");
                    }}
                  >
                    Resume
                  </Button>
                  <Button
                    appearance="subtle"
                    shape="circular"
                    icon={<Delete24Regular />}
                    aria-label={`Delete Discover Requirements revision ${item.analysis_revision}`}
                    title={`Delete Discover Requirements revision ${item.analysis_revision}`}
                    disabled={deletingSessionId !== null}
                    onClick={() => void handleDeleteDiscovery(item)}
                  />
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
