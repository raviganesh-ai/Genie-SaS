import type { IqProviderName, IqStatus } from "./iq";

/** Per-session, per-provider delegated connection status. Mirrors the
 * backend's `IqConnectionStatus` - never carries a token, refresh token,
 * authorization code, or client secret. */
export interface IqConnectionStatus {
  provider: IqProviderName;
  status: IqStatus;
  connected: boolean;
  tenant_id: string | null;
  display_name: string | null;
  connected_at: string | null;
  detail: string;
}
