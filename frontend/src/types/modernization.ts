import type { CostEstimate, PricingQuery } from "@/types/discovery";

export interface ModernizationCapability {
  id: string;
  name: string;
  description: string;
  target_label: string | null;
  instruction_template: string;
}

export interface ModernizationProposedComponent {
  id: string;
  name: string;
  responsibility: string;
  extracted: boolean;
  depends_on: string[];
}

export interface ModernizationPlan {
  id: string;
  session_id: string;
  binding_id: string;
  assessment_id: string;
  standards_snapshot_id: string | null;
  repository_full_name: string;
  base_commit: string;
  base_ref: string;
  goal: string;
  capability_id: string | null;
  capability_name: string | null;
  target: string | null;
  architecture_reference_snapshot_id: string | null;
  summary: string;
  rewrite_strategy: string;
  proposed_components: ModernizationProposedComponent[];
  deployment_plan: string[];
  changes: Array<{ path: string; content: string; reason: string }>;
  validation_commands: string[];
  residual_risks: string[];
  rollback: string;
  pricing_queries: PricingQuery[];
  estimated_cost: CostEstimate | null;
  branch_name: string;
  status:
    | "draft"
    | "pending_approval"
    | "approved"
    | "executing"
    | "pull_request_opened"
    | "failed";
  approval_request_id: string | null;
  pull_request_url: string | null;
  created_at: string;
  updated_at: string;
}

export interface ModernizationPlanChatAnswer {
  question: string;
  answer: string;
  referenced_fields: string[];
  generated_at: string;
}
