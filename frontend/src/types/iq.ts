export type IqProviderName = "work_iq" | "foundry_iq" | "fabric_iq" | "foundry_mcp";
export type IqCapability =
  | "WORK_CONTEXT"
  | "BUSINESS_CONTEXT"
  | "KNOWLEDGE_CONTEXT"
  | "FOUNDRY_CONTEXT";
export type IqStatus =
  | "IQ_AVAILABLE"
  | "IQ_NOT_REQUIRED"
  | "IQ_NOT_CONFIGURED"
  | "IQ_AUTHENTICATION_REQUIRED"
  | "IQ_CONSENT_REQUIRED"
  | "IQ_SESSION_EXPIRED"
  | "IQ_TENANT_MISMATCH"
  | "IQ_PERMISSION_DENIED"
  | "IQ_APPROVAL_REQUIRED"
  | "IQ_UNAVAILABLE"
  | "IQ_TIMEOUT"
  | "IQ_FAILED";
export type IqCandidateStatus =
  | "pending"
  | "confirmed"
  | "rejected"
  | "unresolved"
  | "superseded"
  | "promoted";

/** Providers that require a per-session, per-user "Connect Microsoft 365"
 * delegated OAuth flow (see iqConnectionsApi.ts) rather than a global
 * administrator-managed connection. */
export const DELEGATED_IQ_PROVIDERS: readonly IqProviderName[] = ["work_iq", "fabric_iq"];

export interface IqProviderStatus {
  provider: IqProviderName;
  status: IqStatus;
  enabled: boolean;
  connected: boolean;
  retrieve_tool: string | null;
  available_tools: string[];
  detail: string;
}

export interface IqEvidenceCandidate {
  id: string;
  session_id: string;
  evidence: {
    id: string;
    session_id: string;
    provider: IqProviderName;
    query: string;
    content: unknown;
    citations: string[];
    sensitivity: string;
    authorization_principal: string;
    retrieved_at: string;
    raw_content_hash: string;
  };
  status: IqCandidateStatus;
  review_comment: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
}

