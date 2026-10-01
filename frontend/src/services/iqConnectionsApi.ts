import { apiFetch, getApiBaseUrl } from "./httpClient";
import type { IqProviderName } from "@/types/iq";
import type { IqConnectionStatus } from "@/types/iqConnection";

/**
 * Delegated Microsoft 365 connect/disconnect. Unlike every other Genie API
 * call, `buildStartUrl` is never `fetch`-ed - the caller must navigate the
 * whole browser there (`window.location.href = ...`) so Microsoft's own
 * sign-in redirect chain can complete. Genie's backend is the only place
 * that ever exchanges the resulting authorization code for a token; the
 * browser only ever sees a final redirect back with a status query
 * parameter, never a token.
 */
export const iqConnectionsApi = {
  status(sessionId: string): Promise<IqConnectionStatus[]> {
    return apiFetch<IqConnectionStatus[]>(`/sessions/${sessionId}/iq/connections`);
  },

  buildStartUrl(sessionId: string, provider: IqProviderName): string {
    const url = new URL(`iq/connections/${provider}/start`, `${getApiBaseUrl()}/`);
    url.searchParams.set("session_id", sessionId);
    return url.toString();
  },

  disconnect(sessionId: string, provider: IqProviderName): Promise<void> {
    return apiFetch<void>(`/sessions/${sessionId}/iq/connections/${provider}/disconnect`, {
      method: "POST",
    });
  },
};
