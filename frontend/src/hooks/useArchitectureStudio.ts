import { useCallback, useState } from "react";
import { architectureApi } from "@/services/architectureApi";
import { getTraceId, mintTraceId } from "@/state/traceRegistry";
import { ApiError } from "@/services/httpClient";
import { useAsyncResource, type AsyncResourceState } from "./useAsyncResource";
import type { ArchitectureSnapshot } from "@/types/architecture";
import type { SafeError } from "@/types/common";

// Production default: without this, the architecture snapshot is fetched
// exactly once on page mount and never again - if the Architecture
// Designer agent is still running at that moment (the common case, since
// this page is reached immediately after "Proceed to Architecture"), the
// page gets permanently stuck showing its stale "running" status and the
// Approve action never appears, with no recourse but a full manual
// browser refresh. 4000ms matches Deploy & Launch's own (hardcoded,
// always-on) polling interval.
const DEFAULT_POLL_MS = Number(import.meta.env.VITE_ARCHITECTURE_STUDIO_POLL_MS ?? 4000);

export function useArchitectureStudio(
  sessionId: string | null,
  workflowRunId: string | null,
  pollIntervalMs: number = DEFAULT_POLL_MS,
): AsyncResourceState<ArchitectureSnapshot> {
  const fetcher = useCallback(() => {
    if (!sessionId || !workflowRunId) return Promise.reject(new Error("No active workflow run"));
    return architectureApi.get(sessionId, workflowRunId);
  }, [sessionId, workflowRunId]);

  return useAsyncResource(fetcher, [sessionId, workflowRunId], {
    enabled: Boolean(sessionId && workflowRunId),
    pollIntervalMs,
  });
}

export type RedesignGoal =
  | "lower_cost"
  | "higher_security"
  | "faster_mvp"
  | "regulated_industry"
  | "fabric_first";

const REDESIGN_RATIONALE: Record<RedesignGoal, string> = {
  lower_cost: "Requesting a lower-cost architecture alternative.",
  higher_security: "Requesting a higher-security architecture alternative.",
  faster_mvp: "Requesting a faster-to-deliver MVP architecture alternative.",
  regulated_industry: "Requesting a regulated-industry-compliant architecture alternative.",
  fabric_first: "Requesting a Microsoft Fabric-first architecture alternative.",
};

export interface ArchitectureReanalysisController {
  requestAlternative: (goal: RedesignGoal) => Promise<void>;
  requesting: boolean;
  error: SafeError | null;
}

/** Drives the Architecture Studio's reanalysis action buttons. */
export function useArchitectureReanalysis(
  sessionId: string | null,
  workflowRunId: string | null,
): ArchitectureReanalysisController {
  const [requesting, setRequesting] = useState(false);
  const [error, setError] = useState<SafeError | null>(null);

  const requestAlternative = useCallback(
    async (goal: RedesignGoal) => {
      if (!sessionId || !workflowRunId) return;
      const traceId = getTraceId(workflowRunId) ?? mintTraceId();
      setRequesting(true);
      setError(null);
      try {
        await architectureApi.requestAlternative(
          sessionId,
          workflowRunId,
          traceId,
          REDESIGN_RATIONALE[goal],
        );
      } catch (err) {
        setError(
          err instanceof ApiError ? err : { message: "Unable to request an alternative design." },
        );
        throw err;
      } finally {
        setRequesting(false);
      }
    },
    [sessionId, workflowRunId],
  );

  return { requestAlternative, requesting, error };
}
