import { apiFetch } from "./httpClient";
import type {
  PhaseTaskState,
  PhaseTaskStatus,
  TrackedPhase,
} from "@/types/phaseTracking";

export const phaseTrackingApi = {
  list(sessionId: string): Promise<TrackedPhase[]> {
    return apiFetch<TrackedPhase[]>(`/sessions/${sessionId}/phases`);
  },

  update(
    sessionId: string,
    phaseId: string,
    taskId: string,
    request: {
      status: PhaseTaskStatus;
      evidence_uri: string | null;
      detail: string;
    },
  ): Promise<PhaseTaskState> {
    return apiFetch<PhaseTaskState>(
      `/sessions/${sessionId}/phases/${phaseId}/tasks/${taskId}`,
      { method: "PUT", body: request },
    );
  },
};

