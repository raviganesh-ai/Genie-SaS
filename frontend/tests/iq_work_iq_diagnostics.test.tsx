import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { IqCollaborationPage } from "@/features/iq/IqCollaborationPage";
import { mockFetchSequence, renderWithProviders } from "./testUtils";
import { FIXTURE_SESSION_ID } from "./fixtures";

const CONNECTED_STATUS = [
  {
    provider: "work_iq",
    status: "IQ_AVAILABLE",
    connected: true,
    tenant_id: "tenant-1",
    display_name: "Ada Lovelace",
    connected_at: "2026-09-30T00:00:00Z",
    detail: "Connected as Ada Lovelace.",
  },
  {
    provider: "fabric_iq",
    status: "IQ_AUTHENTICATION_REQUIRED",
    connected: false,
    tenant_id: null,
    display_name: null,
    connected_at: null,
    detail: "Not connected.",
  },
];

describe("IqCollaborationPage - Work IQ development diagnostics", () => {
  it("hides the diagnostics panel entirely when the backend returns 404 (production)", async () => {
    mockFetchSequence([
      { match: "/iq/providers", response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/iq/candidates`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/iq/connections`, response: CONNECTED_STATUS },
      { match: `/sessions/${FIXTURE_SESSION_ID}/iq/diagnostics`, status: 404, response: {} },
    ]);

    renderWithProviders(<IqCollaborationPage />, { sessionId: FIXTURE_SESSION_ID });

    await screen.findByText("Connect Microsoft 365");
    expect(screen.queryByText("Work IQ development diagnostics")).not.toBeInTheDocument();
  });

  it("shows diagnostics and disables validation until connected", async () => {
    mockFetchSequence([
      { match: "/iq/providers", response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/iq/candidates`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/iq/connections`, response: [] },
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/iq/diagnostics`,
        response: {
          microsoft_connect_enabled: true,
          work_iq_enabled: true,
          tenant_configured: true,
          client_configured: true,
          redirect_uri_configured: true,
          work_iq_endpoint_configured: true,
          connected: false,
          mcp_initialized: false,
          tools_discovered_count: null,
          last_error_category: null,
          correlation_id: "corr-1",
        },
      },
    ]);

    renderWithProviders(<IqCollaborationPage />, { sessionId: FIXTURE_SESSION_ID });

    expect(await screen.findByText("Work IQ development diagnostics")).toBeInTheDocument();
    const validateButton = screen.getByRole("button", { name: "Run Work IQ validation" });
    expect(validateButton).toBeDisabled();
  });

  it("runs the validation action and shows a sanitized result", async () => {
    const fetchMock = mockFetchSequence([
      { match: "/iq/providers", response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/iq/candidates`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/iq/connections`, response: CONNECTED_STATUS },
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/iq/diagnostics`,
        response: {
          microsoft_connect_enabled: true,
          work_iq_enabled: true,
          tenant_configured: true,
          client_configured: true,
          redirect_uri_configured: true,
          work_iq_endpoint_configured: true,
          connected: true,
          mcp_initialized: true,
          tools_discovered_count: 10,
          last_error_category: null,
          correlation_id: "corr-1",
        },
      },
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/iq/work-iq/validate`,
        response: {
          success: true,
          provider: "work_iq",
          tool_invoked: "ask",
          response_preview: "You have 2 meetings today.",
          citations: ["https://example.test/meeting"],
          correlation_id: "corr-2",
          duration_ms: 123.4,
          error_category: null,
          detail: "Work IQ retrieval succeeded.",
        },
      },
    ]);

    renderWithProviders(<IqCollaborationPage />, { sessionId: FIXTURE_SESSION_ID });

    const validateButton = await screen.findByRole("button", { name: "Run Work IQ validation" });
    await waitFor(() => expect(validateButton).not.toBeDisabled());
    await userEvent.click(validateButton);

    expect(await screen.findByText("Succeeded")).toBeInTheDocument();
    expect(screen.getByText("You have 2 meetings today.")).toBeInTheDocument();
    expect(screen.getByText(/Correlation ID: corr-2/)).toBeInTheDocument();

    expect(
      fetchMock.mock.calls.some(([input, init]) =>
        new URL(input.toString()).pathname.endsWith("/iq/work-iq/validate")
        && init?.method === "POST",
      ),
    ).toBe(true);
  });
});
