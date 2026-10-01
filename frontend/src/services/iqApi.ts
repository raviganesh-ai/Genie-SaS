import { apiFetch } from "./httpClient";
import type {
  IqCandidateStatus,
  IqEvidenceCandidate,
  IqProviderName,
  IqProviderStatus,
} from "@/types/iq";

export const iqApi = {
  providers(): Promise<IqProviderStatus[]> {
    return apiFetch<IqProviderStatus[]>("/iq/providers");
  },

  candidates(sessionId: string): Promise<IqEvidenceCandidate[]> {
    return apiFetch<IqEvidenceCandidate[]>(`/sessions/${sessionId}/iq/candidates`);
  },

  retrieve(
    sessionId: string,
    provider: IqProviderName,
    query: string,
    sensitivity: string,
  ): Promise<IqEvidenceCandidate> {
    return apiFetch<IqEvidenceCandidate>(`/sessions/${sessionId}/iq/retrieve`, {
      method: "POST",
      body: { provider, query, sensitivity },
    });
  },

  review(
    sessionId: string,
    candidateId: string,
    status: IqCandidateStatus,
    comment?: string,
  ): Promise<IqEvidenceCandidate> {
    return apiFetch<IqEvidenceCandidate>(
      `/sessions/${sessionId}/iq/candidates/${candidateId}/review`,
      { method: "POST", body: { status, comment } },
    );
  },

  promote(sessionId: string, candidateId: string): Promise<IqEvidenceCandidate> {
    return apiFetch<IqEvidenceCandidate>(
      `/sessions/${sessionId}/iq/candidates/${candidateId}/promote`,
      { method: "POST" },
    );
  },
};

