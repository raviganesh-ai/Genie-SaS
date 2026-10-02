import { apiFetch } from "./httpClient";
import type { WellArchitectedAnswer } from "@/types/wellArchitected";

export const wellArchitectedApi = {
  /**
   * Asks one Azure Well-Architected Framework pillar or Azure service-level
   * question. The answer is grounded only in real Microsoft Learn documents
   * retrieved live for this exact question - never the model's own trained
   * knowledge alone - and every citation is a real, verified retrieved URL.
   */
  ask(sessionId: string, question: string): Promise<WellArchitectedAnswer> {
    return apiFetch<WellArchitectedAnswer>(`/sessions/${sessionId}/well-architected/ask`, {
      method: "POST",
      body: { question },
    });
  },
};
