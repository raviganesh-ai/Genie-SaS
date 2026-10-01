export type ProductionPromotionStatus =
  | "draft"
  | "rehearsed"
  | "pending_approval"
  | "canary"
  | "completed"
  | "rolled_back"
  | "failed";

export interface ProductionPromotion {
  id: string;
  session_id: string;
  deployment_run_id: string;
  resource_group_name: string;
  backend_app_name: string;
  health_url: string;
  status: ProductionPromotionStatus;
  approval_request_id: string | null;
  rehearsal_latency_ms: number | null;
  candidate_revision_name: string | null;
  previous_revision_name: string | null;
  canary_weight_percent: number;
  rollback_detail: string | null;
  created_at: string;
  updated_at: string;
}

