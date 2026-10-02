import { useCallback, useEffect, useState } from "react";
import {
  Badge,
  Button,
  Card,
  Dropdown,
  Field,
  Input,
  Option,
  Text,
  Title2,
  Title3,
} from "@fluentui/react-components";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { SectionCard } from "@/components/SectionCard";
import { GovernanceStatusBadge } from "@/components/StatusBadge";
import { statusPalette } from "@/styles/theme";
import { ApiError } from "@/services/httpClient";
import { approvalApi } from "@/services/approvalApi";
import { phaseTrackingApi } from "@/services/phaseTrackingApi";
import { useGovernanceTrace, deriveComplianceState } from "@/hooks/useGovernanceTrace";
import { useSessionContext } from "@/state/SessionContext";
import type { SafeError } from "@/types/common";
import type { PhaseTaskStatus, TrackedPhase, TrackedTask } from "@/types/phaseTracking";
import type {
  ApprovalRequest,
  ApprovalRequestStatus,
  GovernanceEvent,
  GovernanceEventCategory,
} from "@/types/governance";

const STATUSES: PhaseTaskStatus[] = ["pending", "in_progress", "blocked", "completed"];

// Human-readable labels/icons for every real governance event category this
// session can emit (see types/governance.ts's GovernanceEventCategory,
// mirrored 1:1 from the backend's governance_event model) - every category
// must appear here so no real event is ever shown as a raw, unlabeled enum
// value.
const EVENT_CATEGORY_LABELS: Record<GovernanceEventCategory, string> = {
  agent_registration: "🧩 Agent Registered",
  agent_version: "🏷️ Agent Version Recorded",
  agent_lifecycle: "🔄 Agent Lifecycle",
  agent_execution: "🤖 Agent Execution",
  agent_communication: "💬 Agent Communication",
  memory_read: "📖 Memory Read",
  memory_write: "✏️ Memory Write",
  tool_request: "🛠️ Tool Request",
  policy_evaluation: "📜 Policy Evaluation",
  access_denied: "🚫 Access Denied",
  human_checkpoint_confirmation: "✅ Human Checkpoint Confirmed",
};

const APPROVAL_STATUS_COLORS: Record<ApprovalRequestStatus, string> = {
  pending: statusPalette.warning,
  approved: statusPalette.compliant,
  rejected: statusPalette.failed,
  expired: statusPalette.incomplete,
};

function relativeTime(timestamp: string): string {
  const deltaMs = Date.now() - Date.parse(timestamp);
  if (Number.isNaN(deltaMs) || deltaMs < 0) return "";
  if (deltaMs < 1000) return "just now";
  if (deltaMs < 60_000) return `${Math.round(deltaMs / 1000)}s ago`;
  if (deltaMs < 3_600_000) return `${Math.round(deltaMs / 60_000)}m ago`;
  return `${Math.round(deltaMs / 3_600_000)}h ago`;
}

/** A short, real-evidence-only summary of a governance event's own detail
 * payload - never fabricated, just whichever of these common fields the
 * backend actually recorded for that event. */
function eventSummary(detail: Record<string, unknown>): string | null {
  if (typeof detail.output_preview === "string" && detail.output_preview) return detail.output_preview;
  if (typeof detail.reason === "string" && detail.reason) return detail.reason;
  if (typeof detail.step_id === "string" && detail.step_id) return `Step: ${detail.step_id}`;
  if (typeof detail.tool_name === "string" && detail.tool_name) return `Tool: ${detail.tool_name}`;
  return null;
}

function ApprovalRow({
  approval,
  onDecide,
  deciding,
}: {
  approval: ApprovalRequest;
  onDecide: (approval: ApprovalRequest, decision: "approved" | "rejected") => void;
  deciding: boolean;
}): JSX.Element {
  const color = APPROVAL_STATUS_COLORS[approval.status];
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12,
        borderLeft: `3px solid ${color}`,
        padding: "8px 12px",
        background: "rgba(255,255,255,0.03)",
        borderRadius: 4,
      }}
    >
      <div>
        <Text weight="semibold">{approval.checkpoint_id}</Text>
        <Text block size={200} style={{ opacity: 0.75 }}>
          {approval.subject_type} - requested {relativeTime(approval.requested_at)}
        </Text>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Text size={200} style={{ color }}>
          {approval.status}
        </Text>
        {approval.status === "pending" ? (
          <>
            <Button size="small" appearance="primary" disabled={deciding} onClick={() => onDecide(approval, "approved")}>
              Approve
            </Button>
            <Button size="small" appearance="subtle" disabled={deciding} onClick={() => onDecide(approval, "rejected")}>
              Reject
            </Button>
          </>
        ) : null}
      </div>
    </div>
  );
}

function EventRow({ event }: { event: GovernanceEvent }): JSX.Element {
  const summary = eventSummary(event.detail);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2, padding: "6px 0", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 8 }}>
        <Text size={200} weight="semibold">
          {EVENT_CATEGORY_LABELS[event.category]}
        </Text>
        <Text size={100} style={{ opacity: 0.55 }}>
          {relativeTime(event.timestamp)}
        </Text>
      </div>
      {event.agent_id ? (
        <Text size={100} style={{ opacity: 0.7, fontFamily: "monospace" }}>
          {event.agent_id}
        </Text>
      ) : null}
      {summary ? (
        <Text size={200} style={{ opacity: 0.8 }}>
          {summary}
        </Text>
      ) : null}
    </div>
  );
}

/**
 * The real-time Responsible AI governance overview for this session -
 * overall compliance status, every pending/decided approval checkpoint,
 * and the live agent registration/execution/memory/tool/policy event
 * trace (`useGovernanceTrace`, backed by real `/peer-review/events` and
 * `/approvals` data). Shown for EVERY mission kind - not just
 * modernization - so a `discover_requirements`/prototype mission's own
 * Governance page always has real content instead of appearing "skipped".
 * The modernization-specific phase/task tracker below it is additive and
 * only renders once this session actually has tracked phases.
 */
function GovernanceOverview({ sessionId }: { sessionId: string }): JSX.Element {
  const { data, loading, error, refresh } = useGovernanceTrace(sessionId);
  const [decidingId, setDecidingId] = useState<string | null>(null);
  const [decisionError, setDecisionError] = useState<string | null>(null);

  const handleDecide = useCallback(
    async (approval: ApprovalRequest, decision: "approved" | "rejected") => {
      setDecidingId(approval.id);
      setDecisionError(null);
      try {
        await approvalApi.decide(sessionId, approval.id, decision);
        refresh();
      } catch (err) {
        setDecisionError((err as ApiError).message ?? "Unable to record the approval decision.");
      } finally {
        setDecidingId(null);
      }
    },
    [sessionId, refresh],
  );

  if (loading && !data) return <LoadingState label="Loading governance trace..." />;
  if (error) return <ErrorState error={error} onRetry={refresh} />;

  const events = data?.events ?? [];
  const approvals = data?.approvals ?? [];
  const complianceState = deriveComplianceState(events, approvals);
  const sortedApprovals = [...approvals].sort(
    (a, b) => Date.parse(b.requested_at) - Date.parse(a.requested_at),
  );
  const sortedEvents = [...events]
    .sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp))
    .slice(0, 50);

  return (
    <>
      <SectionCard title="Overall governance status" action={<GovernanceStatusBadge state={complianceState} />}>
        <Text size={200} style={{ opacity: 0.8 }}>
          Derived live from every recorded governance event and approval checkpoint for this
          session - never a fabricated or placeholder status.
        </Text>
      </SectionCard>

      <SectionCard title={`Approval checkpoints (${approvals.length})`}>
        {decisionError ? (
          <Text size={200} style={{ color: statusPalette.failed, display: "block", marginBottom: 8 }}>
            {decisionError}
          </Text>
        ) : null}
        {sortedApprovals.length === 0 ? (
          <Text size={200} style={{ opacity: 0.7 }}>
            No approval checkpoints have been requested yet.
          </Text>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {sortedApprovals.map((approval) => (
              <ApprovalRow
                key={approval.id}
                approval={approval}
                onDecide={handleDecide}
                deciding={decidingId === approval.id}
              />
            ))}
          </div>
        )}
      </SectionCard>

      <SectionCard title={`Governance event trace (${events.length})`}>
        {sortedEvents.length === 0 ? (
          <Text size={200} style={{ opacity: 0.7 }}>
            No governance events recorded yet - agent registration, execution, memory, and
            policy events will appear here as Genie's agents start working.
          </Text>
        ) : (
          <div style={{ maxHeight: 420, overflowY: "auto" }}>
            {sortedEvents.map((event) => (
              <EventRow key={event.id} event={event} />
            ))}
          </div>
        )}
      </SectionCard>
    </>
  );
}

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

function ModernizationPhaseTracker({ sessionId }: { sessionId: string }): JSX.Element | null {
  const [phases, setPhases] = useState<TrackedPhase[]>([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<SafeError | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setPhases(await phaseTrackingApi.list(sessionId));
    } catch (err) {
      setError(err instanceof ApiError ? err : { message: "Unable to load phase tracking." });
    } finally {
      setLoading(false);
      setLoaded(true);
    }
  }, [sessionId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) return <ErrorState error={error} onRetry={load} />;
  if (loading && !loaded) return <LoadingState label="Loading phases..." />;
  // Modernization phase tracking only applies to missions that actually
  // have tracked phases (e.g. modernize_and_deliver) - showing an empty
  // "Modernization phase tracking" section for every other mission kind is
  // exactly the "Governance was skipped" gap this page now fixes.
  if (phases.length === 0) return null;

  return (
    <>
      <Title3 style={{ display: "block", marginTop: 24, marginBottom: 8 }}>
        Modernization phase tracking
      </Title3>
      <Text block style={{ marginBottom: 12, opacity: 0.8 }}>
        Phases advance in order. Completion requires evidence that Genie resolves against
        GitHub, Azure Resource Manager, or its durable session store.
      </Text>
      {phases.map((phase) => (
        <section key={phase.id} style={{ marginTop: 24 }}>
          <Title3>{phase.name}</Title3>
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
    </>
  );
}

export function PhaseTrackingPage(): JSX.Element {
  const { sessionId } = useSessionContext();

  if (!sessionId) {
    return <ErrorState error={{ message: "Create a session before tracking governance." }} />;
  }

  return (
    <div className="genie-fade-in">
      <Title2>Governance</Title2>
      <Text block style={{ marginBottom: 16, opacity: 0.8 }}>
        Real-time Responsible AI oversight for this mission: approval checkpoints, the live
        agent governance event trace, and (for modernization missions) phase/task evidence
        tracking.
      </Text>
      <GovernanceOverview sessionId={sessionId} />
      <ModernizationPhaseTracker sessionId={sessionId} />
    </div>
  );
}

