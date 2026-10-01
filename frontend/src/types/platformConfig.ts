import type { ArchitectureStandardRule, StandardsConflict } from "./standards";

export type PlatformReferencePurpose = "architecture" | "standards";

/**
 * One administrator-configured reference repository, applied automatically
 * to every future mission's design-architecture step and governed
 * modernization plan (unless that session supplies its own override) - see
 * backend app.platform_config.models' docstring. There may be more than one
 * repository per purpose; all are combined when consumed.
 */
export interface PlatformReferenceRepository {
  id: string;
  repository_id: number;
  repository_full_name: string;
  repository_url: string;
  purpose: PlatformReferencePurpose;
  requested_ref: string;
  resolved_commit: string;
  included_paths: string[];
  excluded_paths: string[];
  principal: string;
  configured_by_user_id: string;
  paths: string[];
  content_hashes: Record<string, string>;
  gaps: string[];
  combined_reference_text: string | null;
  rules: ArchitectureStandardRule[];
  conflicts: StandardsConflict[];
  created_at: string;
}
