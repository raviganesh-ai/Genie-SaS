import { apiFetch } from "./httpClient";
import type {
  ArchitectureReferenceSnapshot,
  StandardsConformanceReport,
  StandardsSnapshot,
} from "@/types/standards";

export const standardsApi = {
  listStandardsSnapshots(sessionId: string): Promise<StandardsSnapshot[]> {
    return apiFetch<StandardsSnapshot[]>(`/sessions/${sessionId}/standards`);
  },
  ingestStandards(sessionId: string, bindingId: string): Promise<StandardsSnapshot> {
    return apiFetch<StandardsSnapshot>(`/sessions/${sessionId}/standards/ingest/${bindingId}`, {
      method: "POST",
    });
  },
  evaluateStandards(
    sessionId: string,
    snapshotId: string,
    assessmentId: string,
  ): Promise<StandardsConformanceReport> {
    return apiFetch<StandardsConformanceReport>(`/sessions/${sessionId}/standards/evaluate`, {
      method: "POST",
      body: { snapshot_id: snapshotId, assessment_id: assessmentId },
    });
  },
  listArchitectureReferenceSnapshots(sessionId: string): Promise<ArchitectureReferenceSnapshot[]> {
    return apiFetch<ArchitectureReferenceSnapshot[]>(
      `/sessions/${sessionId}/architecture-reference`,
    );
  },
  ingestArchitectureReference(
    sessionId: string,
    bindingId: string,
  ): Promise<ArchitectureReferenceSnapshot> {
    return apiFetch<ArchitectureReferenceSnapshot>(
      `/sessions/${sessionId}/architecture-reference/ingest/${bindingId}`,
      { method: "POST" },
    );
  },
};
