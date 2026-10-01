import { useCallback, useEffect, useState } from "react";
import {
  Badge,
  Button,
  Card,
  Dropdown,
  Field,
  Input,
  Option,
  Spinner,
  Text,
  Title2,
} from "@fluentui/react-components";
import { ErrorState } from "@/components/ErrorState";
import { ApiError } from "@/services/httpClient";
import { phaseTrackingApi } from "@/services/phaseTrackingApi";
import { useSessionContext } from "@/state/SessionContext";
import type { SafeError } from "@/types/common";
import type { PhaseTaskStatus, TrackedPhase, TrackedTask } from "@/types/phaseTracking";

const STATUSES: PhaseTaskStatus[] = ["pending", "in_progress", "blocked", "completed"];

function TaskEditor({
  sessionId,
  phaseId,
  task,
  onSaved,
}: {
  sessionId: string;
  phaseId: string;
  task: TrackedTask;
  onSaved: () => Promise<void>;
}): JSX.Element {
  const [taskStatus, setTaskStatus] = useState<PhaseTaskStatus>(task.state.status);
  const [evidenceUri, setEvidenceUri] = useState(task.state.evidence_uri ?? "");
  const [detail, setDetail] = useState(task.state.detail);
  const [saving, setSaving] = useState(false);

  const save = useCallback(async () => {
    setSaving(true);
    try {
      await phaseTrackingApi.update(sessionId, phaseId, task.definition.id, {
        status: taskStatus,
        evidence_uri: evidenceUri.trim() || null,
        detail: detail.trim(),
      });
      await onSaved();
    } finally {
      setSaving(false);
    }
  }, [detail, evidenceUri, onSaved, phaseId, sessionId, task.definition.id, taskStatus]);

  return (
    <Card>
      <Text weight="semibold">{task.definition.name}</Text>
      <Badge appearance="outline">{task.state.status}</Badge>
      {task.state.evidence_provider ? (
        <Badge appearance="filled" color="success">
          Verified by {task.state.evidence_provider}
        </Badge>
      ) : null}
      <Field label="Status">
        <Dropdown
          value={taskStatus}
          selectedOptions={[taskStatus]}
          onOptionSelect={(_, data) =>
            setTaskStatus((data.optionValue ?? "pending") as PhaseTaskStatus)
          }
        >
          {STATUSES.map((value) => (
            <Option key={value} value={value}>
              {value}
            </Option>
          ))}
        </Dropdown>
      </Field>
      <Field
        label="Live evidence URI"
        hint="Use a GitHub commit, Genie repository binding, or Azure ARM resource URI."
      >
        <Input value={evidenceUri} onChange={(_, data) => setEvidenceUri(data.value)} />
      </Field>
      <Field label="Evidence or blocker detail">
        <Input value={detail} onChange={(_, data) => setDetail(data.value)} />
      </Field>
      <Button appearance="primary" disabled={saving} onClick={() => void save()}>
        {saving ? "Saving..." : "Update task"}
      </Button>
    </Card>
  );
}

export function PhaseTrackingPage(): JSX.Element {
  const { sessionId } = useSessionContext();
  const [phases, setPhases] = useState<TrackedPhase[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<SafeError | null>(null);

  const load = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    setError(null);
    try {
      setPhases(await phaseTrackingApi.list(sessionId));
    } catch (err) {
      setError(err instanceof ApiError ? err : { message: "Unable to load phase tracking." });
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!sessionId) {
    return <ErrorState error={{ message: "Create a session before tracking phases." }} />;
  }
  if (error) return <ErrorState error={error} />;

  return (
    <div className="genie-fade-in">
      <Title2>Modernization phase tracking</Title2>
      <Text block>
        Phases advance in order. Completion requires evidence that Genie resolves against
        GitHub, Azure Resource Manager, or its durable session store.
      </Text>
      {loading ? <Spinner label="Loading phases..." /> : null}
      {phases.map((phase) => (
        <section key={phase.id} style={{ marginTop: 24 }}>
          <Title2>{phase.name}</Title2>
          <div style={{ display: "grid", gap: 12, marginTop: 12 }}>
            {phase.tasks.map((task) => (
              <TaskEditor
                key={task.definition.id}
                sessionId={sessionId}
                phaseId={phase.id}
                task={task}
                onSaved={load}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
