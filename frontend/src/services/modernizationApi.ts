import { apiFetch } from "./httpClient";
import type { ModernizationCapability, ModernizationPlan } from "@/types/modernization";

export const modernizationApi = {
  list(sessionId: string): Promise<ModernizationPlan[]> {
    return apiFetch<ModernizationPlan[]>(`/sessions/${sessionId}/modernization`);
  },

  capabilities(sessionId: string): Promise<ModernizationCapability[]> {
    return apiFetch<ModernizationCapability[]>(
      `/sessions/${sessionId}/modernization/capabilities`,
    );
  },

  generate(
    sessionId: string,
    request: {
      binding_id: string;
      assessment_id: string;
      standards_snapshot_id: string;
      capability_id: string;
      target: string | null;
    },
  ): Promise<ModernizationPlan> {
    return apiFetch<ModernizationPlan>(`/sessions/${sessionId}/modernization`, {
      method: "POST",
      body: request,
    });
  },

  execute(sessionId: string, planId: string): Promise<ModernizationPlan> {
    return apiFetch<ModernizationPlan>(
      `/sessions/${sessionId}/modernization/${planId}/execute`,
      { method: "POST" },
    );
  },
};
