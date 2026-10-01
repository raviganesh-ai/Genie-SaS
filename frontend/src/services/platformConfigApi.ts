import { apiFetch } from "./httpClient";
import type { PlatformReferencePurpose, PlatformReferenceRepository } from "@/types/platformConfig";
import type { GitHubRepositorySummary } from "@/types/repositoryConnection";

export const platformConfigApi = {
  list(purpose?: PlatformReferencePurpose): Promise<PlatformReferenceRepository[]> {
    return apiFetch<PlatformReferenceRepository[]>("/platform-config/reference-repositories", {
      query: purpose ? { purpose } : undefined,
    });
  },

  add(request: {
    repository: GitHubRepositorySummary;
    purpose: PlatformReferencePurpose;
    requested_ref: string;
    included_paths: string[];
    excluded_paths: string[];
  }): Promise<PlatformReferenceRepository> {
    return apiFetch<PlatformReferenceRepository>("/platform-config/reference-repositories", {
      method: "POST",
      body: request,
    });
  },

  remove(repositoryId: string): Promise<void> {
    return apiFetch<void>(`/platform-config/reference-repositories/${repositoryId}`, {
      method: "DELETE",
    });
  },
};
