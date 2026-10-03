import { apiFetch } from "./httpClient";
import type {
  ModernizationCapability,
  ModernizationDeployment,
  ModernizationPlan,
  ModernizationPlanChatAnswer,
} from "@/types/modernization";

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
      standards_snapshot_id?: string | null;
      capability_id: string;
      target: string | null;
      architecture_reference_snapshot_id?: string | null;
      // Optional refinement: regenerate a new, independently approvable
      // plan that incorporates free-text feedback on an earlier plan -
      // see ModernizationPlanChat's "Refine" action.
      previous_plan_id?: string | null;
      refinement_notes?: string | null;
    },
  ): Promise<ModernizationPlan> {
    return apiFetch<ModernizationPlan>(`/sessions/${sessionId}/modernization`, {
      method: "POST",
      body: request,
    });
  },

  ask(sessionId: string, planId: string, message: string): Promise<ModernizationPlanChatAnswer> {
    return apiFetch<ModernizationPlanChatAnswer>(
      `/sessions/${sessionId}/modernization/${planId}/ask`,
      { method: "POST", body: { message } },
    );
  },

  execute(sessionId: string, planId: string): Promise<ModernizationPlan> {
    return apiFetch<ModernizationPlan>(
      `/sessions/${sessionId}/modernization/${planId}/execute`,
      { method: "POST" },
    );
  },

  getDeployment(sessionId: string, planId: string): Promise<ModernizationDeployment | null> {
    return apiFetch<ModernizationDeployment | null>(
      `/sessions/${sessionId}/modernization/${planId}/deployment`,
    );
  },

  proposeDeploymentStrategy(
    sessionId: string,
    planId: string,
  ): Promise<ModernizationDeployment> {
    return apiFetch<ModernizationDeployment>(
      `/sessions/${sessionId}/modernization/${planId}/deployment-strategy`,
      { method: "POST" },
    );
  },

  requestDeployment(
    sessionId: string,
    planId: string,
    deploymentId: string,
  ): Promise<ModernizationDeployment> {
    return apiFetch<ModernizationDeployment>(
      `/sessions/${sessionId}/modernization/${planId}/deployment/${deploymentId}/request`,
      { method: "POST" },
    );
  },

  executeDeployment(
    sessionId: string,
    planId: string,
    deploymentId: string,
  ): Promise<ModernizationDeployment> {
    return apiFetch<ModernizationDeployment>(
      `/sessions/${sessionId}/modernization/${planId}/deployment/${deploymentId}/execute`,
      { method: "POST" },
    );
  },
};
