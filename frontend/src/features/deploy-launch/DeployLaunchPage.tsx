import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Badge, Button, MessageBar, MessageBarBody, MessageBarTitle, Text } from "@fluentui/react-components";
import { useSessionContext } from "@/state/SessionContext";
import { useAsyncResource } from "@/hooks/useAsyncResource";
import { deployLaunchApi } from "@/services/deployLaunchApi";
import { approvalApi } from "@/services/approvalApi";
import { getTraceId } from "@/state/traceRegistry";
import { ApiError } from "@/services/httpClient";
import { PageHeader } from "@/layouts/AppShell";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { NoActiveMissionState } from "@/components/NoActiveMissionState";
import { SectionCard } from "@/components/SectionCard";
import { AgentActivityAnimation } from "@/components/AgentActivityAnimation";
import { useWorkflowEventStream } from "@/hooks/useWorkflowEventStream";
import { DEPLOYMENT_STEP_ORDER, DEPLOYMENT_STEP_NAMES } from "@/types/deployLaunch";
import type {
  DeploymentStepId,
  DeploymentStepResult,
  ProvisionedAgentStatus,
} from "@/types/deployLaunch";
import type { ApprovalRequest } from "@/types/governance";

const POLL_MS = 4000;

const STEP_STATUS_COLORS: Record<DeploymentStepResult["status"], string> = {
  pending: "#8a8f98",
  running: "#d99a2b",
  completed: "#3fa66a",
  failed: "#d1495b",
  skipped: "#8a8f98",
};

// The user-facing status vocabulary is deliberately "Started → In Progress →
// Deployed" for every phase (and per-agent row) rather than generic
// pending/running/completed test jargon.
const STEP_STATUS_LABELS: Record<DeploymentStepResult["status"], string> = {
  pending: "Not Started",
  running: "In Progress…",
  completed: "✅ Deployed",
  failed: "❌ Failed",
  skipped: "Skipped",
};

const AGENT_STATUS_LABELS: Record<ProvisionedAgentStatus["status"], string> = {
  pending: "Queued",
  running: "Deploying…",
  completed: "✅ Deployed",
  failed: "❌ Failed",
  skipped: "Skipped",
};

// Narrative, "gamified" copy for the `AgentActivityAnimation` banner shown
// while a step is actively running (or while the pipeline is still getting
// started) - so the user always sees a concrete "Genie is working with..."
// message rather than a silent, static "Not Started" list. Mirrors the same
// convention used on Requirement Discovery/Workshop.
const STEP_WORKING_LABELS: Record<DeploymentStepId, string> = {
  "validate-deployment-contract": "Genie is validating the complete Azure deployment contract...",
  "generate-access-policy": "Genie is working with the Orchestrator to generate your least-access policy...",
  "provision-foundry-agents": "Genie is working with Azure AI Foundry to deploy your mission agents...",
  "provision-data-layer": "Genie is provisioning the managed-identity Cosmos DB data layer...",
  "validate-data-schema": "Genie is validating the live data schema and continuous backup policy...",
  "deploy-backend-service": "Genie is working with the Orchestrator to deploy your backend service...",
  "sync-frontend-integration": "Genie is wiring your frontend to the newly deployed backend...",
  "deploy-frontend-app": "Genie is publishing your frontend application...",
  "generate-test-suite": "Genie is deriving live acceptance tests from every approved requirement...",
  "execute-test-suite": "Genie is exercising the real deployed prototype before launch...",
  "run-security-scan": "Genie is scanning your backend and frontend for security issues...",
  "security-copilot-scan": "Genie is validating Microsoft security evidence...",
  "finops-cost-report": "Genie is collecting live Azure cost evidence...",
  "launch-mission": "Genie is minting your customer-facing launch link...",
};
const STARTING_LABEL =
  "Genie is working with the Orchestrator to get your deployment started - this can take a minute...";

// A distinct emoji per pipeline step - purely decorative/visual variety for
// the mission flow map and step rows below, mirrors the same convention as
// Triage's `PHASE_ICONS`. Never affects step identity/ordering, which is
// still driven entirely by `DEPLOYMENT_STEP_ORDER`/`DEPLOYMENT_STEP_NAMES`.
const STEP_ICONS: Record<DeploymentStepId, string> = {
  "validate-deployment-contract": "📜",
  "generate-access-policy": "🔐",
  "provision-foundry-agents": "🤖",
  "provision-data-layer": "🗄️",
  "validate-data-schema": "🔎",
  "deploy-backend-service": "⚙️",
  "sync-frontend-integration": "🔗",
  "deploy-frontend-app": "🌐",
  "generate-test-suite": "🧪",
  "execute-test-suite": "✅",
  "run-security-scan": "🛡️",
  "security-copilot-scan": "🔒",
  "finops-cost-report": "💰",
  "launch-mission": "🚀",
};

/**
 * A user-facing "stage" is purely a presentation grouping over 1-2 real,
 * always-executed `DEPLOYMENT_STEP_ORDER` entries - nothing is ever
 * skipped or fabricated here, every member step still runs exactly as
 * before. Each internal-only/technical step (a precondition check, or a
 * step whose own result has no narrative value on its own) folds into its
 * neighboring, user-meaningful step instead of claiming its own row, so
 * "Mission Progress" shows a short, readable plan (9 stages) instead of
 * every one of the 12 underlying steps. `members` must list that group's
 * real step ids in execution order; every `DeploymentStepId` in
 * `DEPLOYMENT_STEP_ORDER` must appear in exactly one group (enforced by
 * `test_deploy_launch_stage_groups_cover_every_step` in the test suite).
 */
interface DeployLaunchStage {
  id: string;
  name: string;
  icon: string;
  members: DeploymentStepId[];
}

const STAGE_GROUPS: DeployLaunchStage[] = [
  {
    id: "generate-access-policy",
    name: "Generate Access Policy & Least Access",
    icon: STEP_ICONS["generate-access-policy"],
    members: ["validate-deployment-contract", "generate-access-policy"],
  },
  {
    id: "provision-foundry-agents",
    name: "Deploy Agents to Foundry",
    icon: STEP_ICONS["provision-foundry-agents"],
    members: ["provision-foundry-agents"],
  },
  {
    id: "provision-data-layer",
    name: "Provision Data Layer",
    icon: STEP_ICONS["provision-data-layer"],
    members: ["provision-data-layer", "validate-data-schema"],
  },
  {
    id: "deploy-backend-service",
    name: "Deploy Backend Service",
    icon: STEP_ICONS["deploy-backend-service"],
    members: ["deploy-backend-service"],
  },
  {
    id: "sync-frontend-integration",
    name: "Update Frontend Integrations",
    icon: STEP_ICONS["sync-frontend-integration"],
    members: ["sync-frontend-integration"],
  },
  {
    id: "deploy-frontend-app",
    name: "Deploy Frontend",
    icon: STEP_ICONS["deploy-frontend-app"],
    members: ["deploy-frontend-app"],
  },
  {
    id: "validate-requirements",
    name: "Validate Requirements",
    icon: STEP_ICONS["execute-test-suite"],
    members: ["generate-test-suite", "execute-test-suite"],
  },
  {
    id: "run-security-scan",
    name: "Security Scan (Backend & Frontend)",
    icon: STEP_ICONS["run-security-scan"],
    members: ["run-security-scan"],
  },
  {
    id: "launch-mission",
    name: "Launch",
    icon: STEP_ICONS["launch-mission"],
    members: ["launch-mission"],
  },
];

/** A single user-visible "Mission Progress" row - a `DeploymentStepResult`
 * shape, but for a `DeployLaunchStage` rather than a raw backend step, so
 * it carries its own display `name`/`icon` instead of being looked up via
 * `DEPLOYMENT_STEP_NAMES`/`STEP_ICONS` (which are only defined for real
 * `DeploymentStepId`s, not synthetic stage ids like
 * "validate-requirements"). */
interface DisplayStage {
  id: string;
  name: string;
  icon: string;
  status: DeploymentStepResult["status"];
  detail: string;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
}

/** Collapses the real, per-step status list into `STAGE_GROUPS` rows: a
 * stage is "running" if any member is, "failed" if any member is (even
 * if a later member hasn't started), "completed" only once every member
 * is, and otherwise "pending" - so a user-visible stage never reports
 * "Deployed" while part of its own real work is still outstanding.
 * Surfaces the detail/duration of whichever member is most relevant to
 * what the user would ask "what's happening right now?" - the running
 * member's own detail while in flight, or the last member's once done. */
function buildDisplayStages(steps: DeploymentStepResult[]): DisplayStage[] {
  const byId = new Map(steps.map((step) => [step.step_id, step]));
  return STAGE_GROUPS.map((stage) => {
    const members = stage.members.map((id) => byId.get(id)).filter((step): step is DeploymentStepResult => Boolean(step));
    const failed = members.find((member) => member.status === "failed");
    const running = members.find((member) => member.status === "running");
    const allCompleted = members.length > 0 && members.every((member) => member.status === "completed");
    const status: DeploymentStepResult["status"] = failed
      ? "failed"
      : running
        ? "running"
        : allCompleted
          ? "completed"
          : "pending";
    const startedAt = members.find((member) => member.started_at)?.started_at ?? null;
    const lastCompleted = [...members].reverse().find((member) => member.completed_at);
    const active = failed ?? running ?? (allCompleted ? members[members.length - 1] : undefined);
    return {
      id: stage.id,
      name: stage.name,
      icon: stage.icon,
      status,
      detail: active?.detail ?? "",
      error: failed?.error ?? null,
      started_at: startedAt,
      completed_at: allCompleted ? (lastCompleted?.completed_at ?? null) : null,
    };
  });
}

/** The first not-yet-completed member step of a stage - what a "Retry"
 * click on that stage's row should resume from, so retrying "Provision
 * Data Layer" after a schema-validation failure doesn't needlessly
 * re-provision the Cosmos account that already succeeded. */
function firstIncompleteMember(stageId: string, steps: DeploymentStepResult[]): DeploymentStepId | null {
  const stage = STAGE_GROUPS.find((candidate) => candidate.id === stageId);
  if (!stage) return null;
  const byId = new Map(steps.map((step) => [step.step_id, step]));
  const incomplete = stage.members.find((id) => byId.get(id)?.status !== "completed");
  return incomplete ?? stage.members[stage.members.length - 1];
}

/** A short "12s"/"1m 4s" duration readout between a step's real started_at
 * and completed_at timestamps - omitted entirely when either is missing so
 * no fabricated timing is ever shown. */
function formatDuration(startedAt: string | null, completedAt: string | null): string | null {
  if (!startedAt || !completedAt) return null;
  const deltaMs = Date.parse(completedAt) - Date.parse(startedAt);
  if (!Number.isFinite(deltaMs) || deltaMs < 0) return null;
  const totalSeconds = Math.round(deltaMs / 1000);
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}m ${seconds}s`;
}

type FlowNodeState = "complete" | "active" | "failed" | "locked";

/** One glowing status node in the mission flow map - reuses the exact same
 * node/connector visual language (`genie-stage-node-*`, `genie-stage-line-active`)
 * as the AppShell sidebar and Triage panel's control-flow map, so the "skill
 * tree" motif reads identically everywhere it appears in Genie. */
function FlowMapNode({ icon, label, state }: { icon: string; label: string; state: FlowNodeState }): JSX.Element {
  const nodeClass =
    state === "complete"
      ? "genie-stage-node-complete"
      : state === "active"
        ? "genie-stage-node-active"
        : state === "failed"
          ? undefined
          : "genie-stage-node-locked";
  const borderColor =
    state === "complete" ? "#3fa66a" : state === "active" ? "#d99a2b" : state === "failed" ? "#d1495b" : "#2a323d";
  const backgroundColor =
    state === "complete"
      ? "rgba(63, 166, 106, 0.15)"
      : state === "active"
        ? "rgba(217, 154, 43, 0.15)"
        : state === "failed"
          ? "rgba(209, 73, 91, 0.15)"
          : "#161c24";
  return (
    <div
      className={nodeClass}
      title={label}
      aria-label={label}
      style={{
        position: "relative",
        flexShrink: 0,
        width: 36,
        height: 36,
        borderRadius: "50%",
        border: `2px solid ${borderColor}`,
        backgroundColor,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: 16,
      }}
    >
      {icon}
      {state === "complete" ? (
        <span
          style={{
            position: "absolute",
            bottom: -3,
            right: -3,
            width: 15,
            height: 15,
            borderRadius: "50%",
            backgroundColor: "#3fa66a",
            color: "#0b0f14",
            fontSize: 9,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          ✓
        </span>
      ) : null}
    </div>
  );
}

/** Connector segment between two flow map nodes; animates a traveling
 * stripe while the mission is actively flowing into the next node. */
function FlowMapConnector({ state }: { state: FlowNodeState }): JSX.Element {
  return (
    <div
      className={state === "active" ? "genie-stage-line-active" : undefined}
      style={{
        flex: 1,
        height: 3,
        minWidth: 10,
        margin: "0 2px",
        borderRadius: 2,
        backgroundColor:
          state === "complete" ? "#3fa66a" : state === "failed" ? "#d1495b" : state === "locked" ? "#232a33" : undefined,
        opacity: state === "locked" ? 0.6 : 1,
      }}
    />
  );
}

/** Horizontal "skill tree" style overview of all nine Deploy & Launch
 * phases - a compact, game-like map of the whole mission at a glance,
 * complementing (not replacing) the detailed per-step list below it.
 * Callers pass already-adjusted `steps` (see `displaySteps` in
 * `DeployLaunchPage`, which optimistically reports the single next
 * not-yet-started step as "running" while the mission is active) so this
 * map and the detailed step-row list below always agree on which step is
 * currently "live". */
function MissionFlowMap({ steps }: { steps: DisplayStage[] }): JSX.Element {
  return (
    <div style={{ display: "flex", alignItems: "center", width: "100%", padding: "4px 2px" }}>
      {steps.map((step, index) => {
        const state: FlowNodeState =
          step.status === "completed"
            ? "complete"
            : step.status === "failed"
              ? "failed"
              : step.status === "running"
                ? "active"
                : "locked";
        const isLast = index === steps.length - 1;
        const nextState: FlowNodeState =
          step.status === "completed" && steps[index + 1]?.status === "running" ? "active" : state;
        return (
          <div key={step.id} style={{ display: "flex", alignItems: "center", flex: isLast ? "0 0 auto" : 1 }}>
            <FlowMapNode icon={step.icon} label={step.name} state={state} />
            {!isLast ? <FlowMapConnector state={nextState} /> : null}
          </div>
        );
      })}
    </div>
  );
}

function AgentRow({ agent }: { agent: ProvisionedAgentStatus }): JSX.Element {
  const color = STEP_STATUS_COLORS[agent.status];
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12,
        borderLeft: `3px solid ${color}`,
        padding: "6px 10px",
        background: "rgba(255,255,255,0.03)",
        borderRadius: 4,
      }}
    >
      <Text size={200} weight="semibold">
        {agent.agent_name}
      </Text>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        {agent.foundry_agent_name ? (
          <Text size={200} style={{ opacity: 0.75, fontFamily: "monospace" }}>
            {agent.foundry_agent_name}
          </Text>
        ) : null}
        <Text size={200} style={{ color }}>
          {AGENT_STATUS_LABELS[agent.status]}
        </Text>
      </div>
    </div>
  );
}

function StepRow({
  step,
  agents,
  onRetry,
  isRetrying,
}: {
  step: DisplayStage;
  agents?: ProvisionedAgentStatus[];
  onRetry?: (stageId: string) => Promise<void>;
  isRetrying?: boolean;
}): JSX.Element {
  const color = STEP_STATUS_COLORS[step.status];
  const duration = formatDuration(step.started_at, step.completed_at);
  const isRunning = step.status === "running";
  return (
    <div
      className={isRunning ? "genie-agent-activity" : undefined}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 4,
        border: `1px solid ${color}`,
        borderRadius: 6,
        padding: "8px 12px",
        boxShadow: isRunning ? "0 0 0 1px rgba(217, 154, 43, 0.25), 0 0 14px 1px rgba(217, 154, 43, 0.18)" : "none",
        transition: "box-shadow 200ms ease, border-color 200ms ease",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <Text size={300} weight="semibold">
          <span aria-hidden="true" style={{ marginRight: 8 }}>
            {step.icon}
          </span>
          {step.name}
        </Text>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {duration ? (
            <Text size={100} style={{ opacity: 0.55, fontFamily: "monospace" }}>
              {duration}
            </Text>
          ) : null}
          <Text size={200} style={{ color }}>
            {STEP_STATUS_LABELS[step.status]}
          </Text>
          {step.status === "failed" && onRetry ? (
            <Button
              size="small"
              appearance="subtle"
              disabled={isRetrying}
              onClick={() => void onRetry(step.id)}
              style={{ marginLeft: 8 }}
            >
              {isRetrying ? "Retrying..." : "Retry"}
            </Button>
          ) : null}
        </div>
      </div>
      {step.detail ? (
        <Text size={200} style={{ opacity: 0.8, whiteSpace: "pre-wrap" }}>
          {step.detail}
        </Text>
      ) : null}
      {step.error ? (
        <Text size={200} style={{ color: "#d1495b" }}>
          {step.error}
        </Text>
      ) : null}
      {agents && agents.length > 0 ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 4 }}>
          {agents.map((agent) => (
            <AgentRow key={agent.agent_name} agent={agent} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

/**
 * The real Deploy & Launch pipeline: nine named, code-driven steps
 * (`DEPLOYMENT_STEP_ORDER`) executed by the backend's
 * `DeploymentPipelineService` against real Azure SDKs. A named governance
 * approval is required before a new non-production release. The backend
 * also self-heals any not-yet-finished
 * upstream workflow step (e.g. build-solution/test-generation) by resuming
 * the same run before running the pipeline.
 */
export function DeployLaunchPage(): JSX.Element {
  const navigate = useNavigate();
  const { sessionId, workflowRunId } = useSessionContext();

  const runsFetcher = useCallback(
    () => (sessionId ? deployLaunchApi.list(sessionId) : Promise.reject(new Error("No active session"))),
    [sessionId],
  );
  const { data: runs, loading, error, refresh } = useAsyncResource(runsFetcher, [sessionId], {
    enabled: Boolean(sessionId),
    pollIntervalMs: POLL_MS,
  });

  const activeRun = useMemo(() => {
    if (!runs || runs.length === 0) return null;
    return [...runs].sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  }, [runs]);

  const { events: liveEvents, connected: liveConnected } = useWorkflowEventStream(sessionId);
  const lastLiveEvent = liveEvents[liveEvents.length - 1] ?? null;
  useEffect(() => {
    if (lastLiveEvent?.event_type === "step_completed" || lastLiveEvent?.event_type === "step_failed") {
      refresh();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastLiveEvent]);

  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [releaseApproval, setReleaseApproval] = useState<ApprovalRequest | null>(null);
  const [approvalWorking, setApprovalWorking] = useState(false);

  // A client-side network hiccup on the start() call (e.g. a slow/lost
  // response) does not mean the pipeline itself failed to kick off - the
  // request may well have reached the server and created the run. Once
  // polling proves a non-failed run actually exists for this mission, the
  // stale "couldn't reach the backend" banner must not keep showing over a
  // run that is actually in progress or has already succeeded.
  useEffect(() => {
    if (startError && activeRun && activeRun.status !== "failed") {
      setStartError(null);
    }
  }, [startError, activeRun]);

  const handleStart = useCallback(async () => {
    if (!sessionId || !workflowRunId) return;
    setStarting(true);
    setStartError(null);
    const traceId = getTraceId(workflowRunId) ?? undefined;
    
    // When retrying after a failure, resume from the first failed step instead of starting from the beginning
    let resumeFromStep: string | undefined;
    if (activeRun?.status === "failed") {
      const firstFailedStep = activeRun.steps.find((step) => step.status === "failed");
      if (firstFailedStep) {
        resumeFromStep = firstFailedStep.step_id;
      }
    }
    
    try {
      await deployLaunchApi.start(
        sessionId,
        workflowRunId,
        traceId,
        resumeFromStep,
        resumeFromStep ? undefined : releaseApproval?.id,
      );
      refresh();
    } catch (err) {
      setStartError((err as ApiError).message ?? "Failed to start Deploy & Launch.");
    } finally {
      setStarting(false);
    }
  }, [sessionId, workflowRunId, activeRun, refresh, releaseApproval]);

  const requestReleaseApproval = useCallback(async () => {
    if (!sessionId || !workflowRunId) return;
    setApprovalWorking(true);
    setStartError(null);
    try {
      setReleaseApproval(
        await deployLaunchApi.requestApproval(
          sessionId,
          workflowRunId,
          getTraceId(workflowRunId) ?? undefined,
        ),
      );
    } catch (err) {
      setStartError((err as ApiError).message ?? "Unable to request release approval.");
    } finally {
      setApprovalWorking(false);
    }
  }, [sessionId, workflowRunId]);

  const decideReleaseApproval = useCallback(
    async (decision: "approved" | "rejected") => {
      if (!sessionId || !releaseApproval) return;
      setApprovalWorking(true);
      try {
        await approvalApi.decide(
          sessionId,
          releaseApproval.id,
          decision,
          "Human non-production release decision.",
        );
        setReleaseApproval({ ...releaseApproval, status: decision });
      } catch (err) {
        setStartError((err as ApiError).message ?? "Unable to record release decision.");
      } finally {
        setApprovalWorking(false);
      }
    },
    [releaseApproval, sessionId],
  );

  // The full step roster, shown to the user immediately - even before a run
  // has actually started - so they see the whole plan up front ("Not
  // Started" for every step) rather than a generic spinner, then watch each
  // step's status update in place as the pipeline actually executes.
  const steps: DeploymentStepResult[] = useMemo(
    () =>
      DEPLOYMENT_STEP_ORDER.map(
        (stepId) =>
          activeRun?.steps.find((candidate) => candidate.step_id === stepId) ?? {
            step_id: stepId,
            name: DEPLOYMENT_STEP_NAMES[stepId],
            status: "pending" as const,
            detail: "",
            error: null,
            started_at: null,
            completed_at: null,
          },
      ),
    [activeRun],
  );

  // Drives both the activity banner and the optimistic "next step is
  // running" override below. Deliberately also covers the pre-run window -
  // `runs` has loaded but no run exists yet - because the page auto-starts
  // the pipeline in that exact state (see the auto-start effect above), and
  // `starting` is only true while the POST itself is in flight. Without
  // that third clause the page falls back to a silent wall of "Not Started"
  // twice: once before the auto-start effect fires, and again between
  // `handleStart` clearing `starting` and the `refresh()` result landing.
  const isPipelineActive =
    !startError &&
    activeRun?.status !== "failed" &&
    (starting || activeRun?.status === "running" || (!!runs && !activeRun));

  // Deploy & Launch's own `start()` first self-heals any not-yet-finished
  // upstream workflow step (e.g. build-solution resumed because Workshop's
  // "Proceed" is a client-side gesture, not a wait for the backend's own,
  // slower official step completion - see pipeline_service.py's
  // `_ensure_upstream_steps_completed`) BEFORE this pipeline's own nine
  // steps begin - real step 1 genuinely cannot start until that resume
  // finishes, which can legitimately take minutes for a full build
  // regeneration. Past a short grace window, treat "every one of our own
  // steps is still pending" as evidence we are still waiting on that
  // upstream work, not evidence step 1 is "about to start any second" -
  // otherwise the optimistic override below keeps lying (a step 1 badge
  // stuck on "In Progress" for many minutes while genie-orchestrator is
  // actually still finishing an earlier mission phase).
  const noOwnStepHasStartedYet = steps.every((step) => step.status === "pending");
  const runAgeMs = activeRun ? Date.now() - Date.parse(activeRun.created_at) : 0;
  const awaitingUpstreamStep = isPipelineActive && noOwnStepHasStartedYet && runAgeMs > 20_000;

  // What the user actually sees rendered (flow map + step-row list): while
  // the mission is genuinely in motion, the single next not-yet-started step
  // is optimistically shown as "In Progress" rather than "Not Started" -
  // Genie really is working on it server-side the moment the prior step
  // completes (or from the very start for step 1), the backend's own status
  // field for it just hasn't flipped to "running" yet (that requires its
  // first `step_started` event/poll to land). Never overrides a real
  // completed/failed/running status - purely fills the "about to start"
  // gap so the whole page never looks frozen on a wall of "Not Started".
  // Also applies during `awaitingUpstreamStep` (step 1 is genuinely next in
  // line even though Deploy & Launch is still waiting on an earlier mission
  // step to resume) - the activity banner above already states plainly that
  // Genie is finishing that earlier step first, so showing step 1 as "In
  // Progress" here isn't dishonest, just optimistic about ordering. In that
  // specific case its row also gets an explanatory `detail` line so a long
  // wait (a full build regeneration can take minutes) reads as "still
  // working on something upstream" rather than "frozen on step 1".
  const displaySteps = useMemo(() => {
    if (!isPipelineActive) return steps;
    const nextIndex = steps.findIndex(
      (step) => step.status !== "completed" && step.status !== "failed" && step.status !== "running",
    );
    if (nextIndex === -1) return steps;
    return steps.map((step, index) => {
      if (index !== nextIndex) return step;
      if (awaitingUpstreamStep) {
        return {
          ...step,
          status: "running" as const,
          detail: "Waiting on an earlier mission step to finish first - this can take a minute or two.",
        };
      }
      return { ...step, status: "running" as const };
    });
  }, [steps, isPipelineActive, awaitingUpstreamStep]);

  // The user-visible "Mission Progress" rows/count/bar are derived from
  // the same `displaySteps` the activity banner below uses, just grouped
  // into `STAGE_GROUPS` first - so "X/9 Stages Complete" always matches
  // exactly what's rendered (never a mismatched "X/12" against a visibly
  // shorter list of rows).
  const displayStages = useMemo(() => buildDisplayStages(displaySteps), [displaySteps]);
  const completedStageCount = useMemo(
    () => displayStages.filter((stage) => stage.status === "completed").length,
    [displayStages],
  );
  const stageProgressPct = Math.round((completedStageCount / displayStages.length) * 100);

  // Drives the gamified "Genie is working with..." activity banner: while
  // the pipeline is genuinely in motion (either the start() request is
  // still in flight, or a run exists and is running) but no error/failure
  // is showing, surface the currently-running step's narrative label (or a
  // generic "getting started" label before the first step has flipped to
  // running) so the user always sees concrete evidence of progress instead
  // of a silent, static "Not Started" list. While genuinely still waiting
  // on an earlier mission step (see `awaitingUpstreamStep`), show an
  // honest "finishing an earlier step" message instead of falsely
  // attributing activity to this pipeline's own step 1 - the real,
  // still-live event text below this label (`AgentActivityAnimation`'s own
  // `events` prop) already shows what is actually happening.
  const runningStep = useMemo(() => displaySteps.find((step) => step.status === "running") ?? null, [displaySteps]);
  const activityLabel = awaitingUpstreamStep
    ? "Genie is finishing an earlier mission step before Deploy & Launch's own steps can begin..."
    : !activeRun
      ? // No run record exists yet - naming step 1's
        // specific work here would claim progress that has not begun.
        STARTING_LABEL
      : runningStep
        ? STEP_WORKING_LABELS[runningStep.step_id]
        : STARTING_LABEL;

  // Opens the mission's real, deployed launch URL in a brand-new browser
  // tab/window - never navigates the Genie platform itself away from this
  // page. `noopener,noreferrer` prevents the newly opened page from getting
  // a handle back to this window (standard tab-nabbing protection).
  const handleLaunch = useCallback(() => {
    if (!activeRun?.launch_url) return;
    window.open(activeRun.launch_url, "_blank", "noopener,noreferrer");
  }, [activeRun]);

  const [retryingStep, setRetryingStep] = useState<DeploymentStepId | null>(null);
  const [retryError, setRetryError] = useState<string | null>(null);

  const handleRetryStep = useCallback(
    async (stepId: DeploymentStepId) => {
      if (!sessionId || !workflowRunId) return;
      setRetryingStep(stepId);
      setRetryError(null);
      const traceId = getTraceId(workflowRunId) ?? undefined;
      try {
        await deployLaunchApi.start(sessionId, workflowRunId, traceId, stepId);
        refresh();
      } catch (err) {
        setRetryError((err as ApiError).message ?? `Failed to retry ${DEPLOYMENT_STEP_NAMES[stepId]}.`);
      } finally {
        setRetryingStep(null);
      }
    },
    [sessionId, workflowRunId, refresh],
  );

  // A "Retry" click on a user-visible stage row resumes from that stage's
  // first not-yet-completed real step - e.g. retrying "Provision Data
  // Layer" after a schema-validation failure resumes from
  // `validate-data-schema`, not from `provision-data-layer` again, so a
  // Cosmos account that already provisioned successfully isn't needlessly
  // recreated.
  const handleRetryStage = useCallback(
    async (stageId: string) => {
      const resumeFrom = firstIncompleteMember(stageId, steps);
      if (!resumeFrom) return;
      await handleRetryStep(resumeFrom);
    },
    [steps, handleRetryStep],
  );

  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const handleDownload = useCallback(async () => {
    if (!sessionId || !activeRun) return;
    setDownloading(true);
    setDownloadError(null);
    try {
      const { blob, filename } = await deployLaunchApi.download(sessionId, activeRun.id);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setDownloadError((err as ApiError).message ?? "Failed to download the build.");
    } finally {
      setDownloading(false);
    }
  }, [sessionId, activeRun]);

  if (!sessionId || !workflowRunId) {
    return (
      <NoActiveMissionState
        title="Deploy & Launch"
        message="Complete the UI & Agent Design workshop from an active mission run before deploying."
      />
    );
  }

  return (
    <div>
      <PageHeader
        title="Deploy & Launch"
        subtitle="Verifies every approved requirement, repairs gaps automatically, then deploys the governed prototype and mints its launch link."
      />
      {loading && !runs ? <LoadingState label="Loading Deploy & Launch status..." /> : null}
      {error ? <ErrorState error={error} onRetry={refresh} /> : null}

      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {!activeRun ? (
          <SectionCard title="Non-production release approval">
            {startError ? (
              <MessageBar intent="warning" layout="multiline" style={{ marginBottom: 12 }}>
                <MessageBarBody>
                  <MessageBarTitle>Deploy & Launch</MessageBarTitle>
                  {startError}
                </MessageBarBody>
              </MessageBar>
            ) : null}
            <div style={{ display: "flex", gap: 8 }}>
              {!releaseApproval ? (
                <Button
                  appearance="primary"
                  disabled={approvalWorking}
                  onClick={() => void requestReleaseApproval()}
                >
                  Request release approval
                </Button>
              ) : null}
              {releaseApproval?.status === "pending" ? (
                <>
                  <Button
                    appearance="primary"
                    disabled={approvalWorking}
                    onClick={() => void decideReleaseApproval("approved")}
                  >
                    Approve
                  </Button>
                  <Button
                    disabled={approvalWorking}
                    onClick={() => void decideReleaseApproval("rejected")}
                  >
                    Reject
                  </Button>
                </>
              ) : null}
              {releaseApproval?.status === "approved" ? (
                <Button appearance="primary" disabled={starting} onClick={() => void handleStart()}>
                  {starting ? "Starting..." : "Start approved deployment"}
                </Button>
              ) : null}
            </div>
          </SectionCard>
        ) : null}

        {activeRun?.status === "failed" ? (
          <SectionCard title="Deploy & Launch Failed">
            <Button appearance="primary" disabled={starting} onClick={() => void handleStart()}>
              {starting ? "Starting..." : "Retry Deploy & Launch"}
            </Button>
          </SectionCard>
        ) : null}

        {isPipelineActive ? (
          <AgentActivityAnimation label={activityLabel} events={liveEvents} startedAt={activeRun?.created_at} />
        ) : null}

        {activeRun?.fidelity_report ? (
          <SectionCard
            title="Requirement Validation"
            action={
              <Badge
                shape="rounded"
                style={{
                  backgroundColor:
                    activeRun.fidelity_report.status === "passed"
                      ? "#3fa66a"
                      : activeRun.fidelity_report.status === "failed"
                        ? "#d1495b"
                        : "#2f83e0",
                  color: "#0b0f14",
                }}
              >
                {activeRun.fidelity_report.pass_percent}% passed
              </Badge>
            }
          >
            <Text size={200} style={{ opacity: 0.7 }}>
              See the Requirement Validation tab for full per-requirement evidence.
            </Text>
          </SectionCard>
        ) : null}

        {activeRun?.status === "completed" ? (
          <SectionCard title="Production promotion">
            <Button appearance="primary" onClick={() => navigate("/production-promotion")}>
              Rehearse and promote to production
            </Button>
          </SectionCard>
        ) : null}

        <SectionCard
          title="🎮 Mission Progress"
          action={
            <Badge
              shape="rounded"
              style={{ backgroundColor: stageProgressPct === 100 ? "#3fa66a" : "#2f83e0", color: "#0b0f14" }}
            >
              {completedStageCount}/{displayStages.length} Stages Complete
            </Badge>
          }
        >
          <MissionFlowMap steps={displayStages} />
          <div
            style={{
              height: 8,
              borderRadius: 4,
              backgroundColor: "#232a33",
              overflow: "hidden",
              marginTop: 12,
              marginBottom: 16,
            }}
          >
            <div
              className="genie-xp-bar"
              style={{
                height: "100%",
                width: `${stageProgressPct}%`,
                backgroundColor: stageProgressPct === 100 ? "#3fa66a" : "#2f83e0",
              }}
            />
          </div>
          {retryError ? (
            <MessageBar intent="warning" layout="multiline" style={{ marginBottom: 12 }}>
              <MessageBarBody>
                <MessageBarTitle>Retry Failed</MessageBarTitle>
                {retryError}
              </MessageBarBody>
            </MessageBar>
          ) : null}
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {displayStages.map((stage) => {
              const agents = stage.id === "provision-foundry-agents" ? activeRun?.provisioned_agents ?? [] : undefined;
              const stageMembers = STAGE_GROUPS.find((group) => group.id === stage.id)?.members ?? [];
              return (
                <StepRow
                  key={stage.id}
                  step={stage}
                  agents={agents}
                  onRetry={handleRetryStage}
                  isRetrying={retryingStep !== null && stageMembers.includes(retryingStep)}
                />
              );
            })}
          </div>
        </SectionCard>

        {activeRun ? (
          <>
            {activeRun.status === "completed" && activeRun.launch_url ? (
              <SectionCard title="🎉 Mission Launched!" highlight>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
                  <span className="genie-sparkle" aria-hidden="true" style={{ fontSize: 22 }}>
                    🧞
                  </span>
                  <Badge shape="rounded" style={{ backgroundColor: "#3fa66a", color: "#0b0f14" }}>
                    ✅ Deployment Complete
                  </Badge>
                  <span className="genie-sparkle" aria-hidden="true" style={{ fontSize: 18 }}>
                    ✨
                  </span>
                </div>
                <Text size={300} style={{ display: "block", marginBottom: 12 }}>
                  Your solution is live at:{" "}
                  <a href={activeRun.launch_url} target="_blank" rel="noreferrer">
                    {activeRun.launch_url}
                  </a>
                </Text>
                {downloadError ? <ErrorState error={{ message: downloadError }} /> : null}
                <div style={{ display: "flex", gap: 8 }}>
                  <Button appearance="primary" onClick={handleLaunch}>
                    Launch
                  </Button>
                  <Button disabled={downloading} onClick={() => void handleDownload()}>
                    {downloading ? "Preparing download..." : "Download Code & Access Policy"}
                  </Button>
                </div>
              </SectionCard>
            ) : null}
          </>
        ) : null}

        {!liveConnected && activeRun && activeRun.status === "running" ? (
          <Text size={200} style={{ opacity: 0.6 }}>
            Live updates disconnected - still polling every {POLL_MS / 1000}s.
          </Text>
        ) : null}
      </div>
    </div>
  );
}
