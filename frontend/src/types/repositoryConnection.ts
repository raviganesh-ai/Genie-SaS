export type RepositoryPurpose = "code" | "architecture" | "standards";

export interface GitHubMcpConnectionStatus {
  configured: boolean;
  connected: boolean;
  authentication_mode: "administrator_managed_mcp";
  account_login: string | null;
  server_endpoint: string | null;
  detail: string;
}

export interface GitHubRepositorySummary {
  repository_id: number;
  name: string;
  full_name: string;
  description: string;
  html_url: string;
  private: boolean;
  archived: boolean;
  default_branch: string;
  language: string | null;
  updated_at: string | null;
}

export interface GitHubRepositoryPage {
  repositories: GitHubRepositorySummary[];
  total_count: number;
  incomplete_results: boolean;
  page: number;
  per_page: number;
}

export interface RepositoryPurposeBinding {
  id: string;
  session_id: string;
  owner_user_id: string;
  repository_id: number;
  repository_full_name: string;
  repository_url: string;
  purpose: RepositoryPurpose;
  requested_ref: string;
  resolved_commit: string;
  included_paths: string[];
  excluded_paths: string[];
  principal: string;
  status: "validated" | "approved" | "expired" | "superseded";
  validated_at: string;
  created_at: string;
}

export interface CreateRepositoryBindingRequest {
  repository: GitHubRepositorySummary;
  purpose: RepositoryPurpose;
  requested_ref: string;
  included_paths: string[];
  excluded_paths: string[];
}

export type DependencyNodeType =
  | "repository"
  | "source_file"
  | "manifest"
  | "package"
  | "integration_endpoint";

export interface DependencyNode {
  id: string;
  type: DependencyNodeType;
  name: string;
  version: string | null;
  path: string | null;
  attributes: Record<string, unknown>;
}

export interface DependencyEdge {
  id: string;
  source: string;
  target: string;
  type: "contains" | "declares" | "depends_on" | "imports" | "integrates_with";
  confidence: number;
  evidence: Array<{
    repository_full_name: string;
    commit: string;
    path: string;
    excerpt: string | null;
  }>;
}

export interface RepositoryAssessment {
  id: string;
  session_id: string;
  binding_id: string;
  repository_full_name: string;
  commit: string;
  inventory: {
    file_count: number;
    analyzed_file_count: number;
    languages: string[];
    manifest_paths: string[];
    infrastructure_paths: string[];
    workflow_paths: string[];
    test_paths: string[];
  };
  nodes: DependencyNode[];
  edges: DependencyEdge[];
  coverage_gaps: Array<{ category: string; detail: string; paths: string[] }>;
  created_at: string;
}
