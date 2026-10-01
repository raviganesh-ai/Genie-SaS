export type RuleClassification =
  | "mandatory"
  | "preferred"
  | "advisory"
  | "example"
  | "superseded";

export interface StandardCitation {
  repository_full_name: string;
  commit: string;
  path: string;
  line: number;
  content_hash: string;
}

export interface ArchitectureStandardRule {
  id: string;
  title: string;
  statement: string;
  classification: RuleClassification;
  citation: StandardCitation;
}

export interface StandardsSnapshot {
  id: string;
  session_id: string;
  binding_id: string;
  repository_full_name: string;
  commit: string;
  paths: string[];
  content_hashes: Record<string, string>;
  rules: ArchitectureStandardRule[];
  conflicts: Array<{ rule_ids: string[]; detail: string }>;
  gaps: string[];
  created_at: string;
}

export interface StandardsConformanceReport {
  snapshot_id: string;
  assessment_id: string;
  results: Array<{
    rule_id: string;
    status: "conformant" | "non_conformant" | "not_applicable" | "unresolved";
    matched_node_ids: string[];
    detail: string;
    citation: StandardCitation;
  }>;
  evaluated_at: string;
}

