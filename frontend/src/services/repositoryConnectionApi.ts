import { apiFetch } from "./httpClient";
import type {
  CreateRepositoryBindingRequest,
  GitHubMcpConnectionStatus,
  GitHubRepositoryPage,
  RepositoryPurposeBinding,
  RepositoryAssessment,
} from "@/types/repositoryConnection";

export const repositoryConnectionApi = {
  getStatus(): Promise<GitHubMcpConnectionStatus> {
    return apiFetch<GitHubMcpConnectionStatus>("/repository-connections/github/status");
  },

  connect(): Promise<GitHubMcpConnectionStatus> {
    return apiFetch<GitHubMcpConnectionStatus>("/repository-connections/github/connect", {
      method: "POST",
    });
  },

  listRepositories(query?: string): Promise<GitHubRepositoryPage> {
    return apiFetch<GitHubRepositoryPage>("/repository-connections/github/repositories", {
      query: { query, page: 1, per_page: 50 },
    });
  },

  listBindings(sessionId: string): Promise<RepositoryPurposeBinding[]> {
    return apiFetch<RepositoryPurposeBinding[]>(
      `/sessions/${sessionId}/repository-bindings`,
    );
  },

  createBinding(
    sessionId: string,
    request: CreateRepositoryBindingRequest,
  ): Promise<RepositoryPurposeBinding> {
    return apiFetch<RepositoryPurposeBinding>(
      `/sessions/${sessionId}/repository-bindings`,
      { method: "POST", body: request },
    );
  },

  listAssessments(sessionId: string): Promise<RepositoryAssessment[]> {
    return apiFetch<RepositoryAssessment[]>(`/sessions/${sessionId}/repository-assessments`);
  },

  createAssessment(sessionId: string, bindingId: string): Promise<RepositoryAssessment> {
    return apiFetch<RepositoryAssessment>(
      `/sessions/${sessionId}/repository-assessments/${bindingId}`,
      { method: "POST" },
    );
  },
};
