import { apiFetch } from "./httpClient";
import type { IqDiagnostics, WorkIqValidationResult } from "@/types/iqDiagnostics";

/**
 * Development-only diagnostics and the explicit, one-shot Work IQ
 * validation action. The backend hard-gates both routes to 404 outside
 * development/test environments (see `app/api/iq_diagnostics.py`), so a
 * production deployment simply never exposes this capability - the
 * frontend does not need its own environment check to hide it safely,
 * only to avoid showing a confusing 404 in the UI (see
 * `IqCollaborationPage.tsx`, which treats a 404 here as "not available").
 */
export const iqDiagnosticsApi = {
  diagnostics(sessionId: string): Promise<IqDiagnostics> {
    return apiFetch<IqDiagnostics>(`/sessions/${sessionId}/iq/diagnostics`);
  },

  validateWorkIq(sessionId: string): Promise<WorkIqValidationResult> {
    return apiFetch<WorkIqValidationResult>(`/sessions/${sessionId}/iq/work-iq/validate`, {
      method: "POST",
    });
  },
};
