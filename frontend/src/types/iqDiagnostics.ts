import type { IqProviderName } from "./iq";

/** Development-only diagnostic snapshot for Microsoft Connect / Work IQ.
 * Mirrors the backend's `IqDiagnostics` - every field is a boolean, a
 * count, a safe category label, or a correlation id. Never a token,
 * secret, authorization code, or Microsoft 365 content. */
export interface IqDiagnostics {
  microsoft_connect_enabled: boolean;
  work_iq_enabled: boolean;
  tenant_configured: boolean;
  client_configured: boolean;
  redirect_uri_configured: boolean;
  work_iq_endpoint_configured: boolean;
  connected: boolean;
  mcp_initialized: boolean;
  tools_discovered_count: number | null;
  last_error_category: string | null;
  correlation_id: string;
}

/** Result of the development-only, explicit-action Work IQ validation
 * call. Never persisted and never carries raw Microsoft 365 content -
 * `response_preview` is truncated and `citations` are reference URLs only. */
export interface WorkIqValidationResult {
  success: boolean;
  provider: IqProviderName;
  tool_invoked: string | null;
  response_preview: string | null;
  citations: string[];
  correlation_id: string;
  duration_ms: number;
  error_category: string | null;
  detail: string;
}
