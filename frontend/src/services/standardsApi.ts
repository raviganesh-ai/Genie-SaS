import { apiFetch } from "./httpClient";
import type { StandardsConformanceReport, StandardsSnapshot } from "@/types/standards";

export const standardsApi = {
  list(sessionId: string): Promise<StandardsSnapshot[]> {
    return apiFetch<StandardsSnapshot[]>(`/sessions/${sessionId}/standards`);
  },

  ingest(sessionId: string, bindingId: string): Promise<StandardsSnapshot> {
    return apiFetch<StandardsSnapshot>(`/sessions/${sessionId}/standards/ingest/${bindingId}`, {
      method: "POST",
    });
  },

  evaluate(
    sessionId: string,
    snapshotId: string,
    assessmentId: string,
  ): Promise<StandardsConformanceReport> {
    return apiFetch<StandardsConformanceReport>(`/sessions/${sessionId}/standards/evaluate`, {
      method: "POST",
      body: { snapshot_id: snapshotId, assessment_id: assessmentId },
    });
  },
};

