import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { IqCollaborationPage } from "@/features/iq/IqCollaborationPage";
import { mockFetchSequence, renderWithProviders } from "./testUtils";
import { FIXTURE_SESSION_ID } from "./fixtures";

const WORK_IQ_NOT_CONNECTED = {
  provider: "work_iq",
  status: "IQ_AUTHENTICATION_REQUIRED",
  connected: false,
  tenant_id: null,
  display_name: null,
  connected_at: null,
  detail: "Not connected. Start Connect Microsoft 365 to use this capability.",
};

const FABRIC_IQ_NOT_CONNECTED = {
  ...WORK_IQ_NOT_CONNECTED,
  provider: "fabric_iq",
};

const WORK_IQ_CONNECTED = {
  provider: "work_iq",
  status: "IQ_AVAILABLE",
  connected: true,
  tenant_id: "tenant-1",
  display_name: "Ada Lovelace",
  connected_at: "2026-09-30T00:00:00Z",
  detail: "Connected as Ada Lovelace.",
};

describe("IqCollaborationPage - Connect Microsoft 365", () => {
  const locationMock: { href: string } = { href: "" };

  beforeEach(() => {
    locationMock.href = "";
    // jsdom does not implement real navigation - stub `window.location`
    // with a plain assignable object so clicking Connect can be observed
    // as "the browser was told to navigate to this exact URL" without
    // actually navigating.
    vi.stubGlobal("location", locationMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows both delegated providers as not connected, then navigates the whole page on Connect", async () => {
    mockFetchSequence([
      { match: "/iq/providers", response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/iq/candidates`, response: [] },
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/iq/connections`,
        response: [WORK_IQ_NOT_CONNECTED, FABRIC_IQ_NOT_CONNECTED],
      },
      { match: `/sessions/${FIXTURE_SESSION_ID}/iq/diagnostics`, status: 404, response: {} },
    ]);

    renderWithProviders(<IqCollaborationPage />, { sessionId: FIXTURE_SESSION_ID });

    expect(await screen.findByText("Connect Microsoft 365")).toBeInTheDocument();
    expect(screen.getAllByText("Not connected")).toHaveLength(2);

    await userEvent.click(screen.getByRole("button", { name: "Connect Work IQ" }));

    expect(locationMock.href).toContain(`/iq/connections/work_iq/start`);
    expect(locationMock.href).toContain(`session_id=${FIXTURE_SESSION_ID}`);
  });

  it("shows a success banner and reloads status after returning from the Microsoft sign-in redirect", async () => {
    mockFetchSequence([
      { match: "/iq/providers", response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/iq/candidates`, response: [] },
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/iq/connections`,
        response: [WORK_IQ_CONNECTED, FABRIC_IQ_NOT_CONNECTED],
      },
      { match: `/sessions/${FIXTURE_SESSION_ID}/iq/diagnostics`, status: 404, response: {} },
    ]);

    renderWithProviders(<IqCollaborationPage />, {
      sessionId: FIXTURE_SESSION_ID,
      route: "/iq-collaboration?iq_connect=connected&provider=work_iq",
    });

    await waitFor(() =>
      expect(screen.getByText(/Connected to Microsoft 365\./i)).toBeInTheDocument(),
    );
    expect(await screen.findByText("Connected as Ada Lovelace.")).toBeInTheDocument();
  });

  it("disconnects a connected provider", async () => {
    const fetchMock = mockFetchSequence([
      { match: "/iq/providers", response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/iq/candidates`, response: [] },
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/iq/connections`,
        response: [WORK_IQ_CONNECTED, FABRIC_IQ_NOT_CONNECTED],
      },
      { match: `/sessions/${FIXTURE_SESSION_ID}/iq/diagnostics`, status: 404, response: {} },
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/iq/connections/work_iq/disconnect`,
        status: 204,
        response: undefined,
      },
    ]);

    renderWithProviders(<IqCollaborationPage />, { sessionId: FIXTURE_SESSION_ID });

    const disconnectButton = await screen.findByRole("button", { name: "Disconnect" });
    await userEvent.click(disconnectButton);

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input, init]) =>
          new URL(input.toString()).pathname.endsWith("/iq/connections/work_iq/disconnect")
          && init?.method === "POST",
        ),
      ).toBe(true),
    );
  });
});
