import { apiFetch } from "./httpClient";
import type {
  CreateRepositoryBindingRequest,
  GitHubMcpConnectionStatus,
  GitHubRepositoryPage,
  RepositoryChatAnswer,
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

  /**
   * Asks one free-text question about an already-completed assessment
   * (code analysis) - answered strictly from that assessment's
   * deterministic dependency/component graph, never general knowledge.
   */
  askAboutAssessment(
    sessionId: string,
    assessmentId: string,
    message: string,
  ): Promise<RepositoryChatAnswer> {
    return apiFetch<RepositoryChatAnswer>(
      `/sessions/${sessionId}/repository-assessments/${assessmentId}/ask`,
      { method: "POST", body: { message } },
    );
  },
};
