import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders, mockFetchSequence } from "./testUtils";
import { FIXTURE_SESSION_ID } from "./fixtures";
import { PhaseTrackingPage } from "@/features/phase-tracking/PhaseTrackingPage";
import type { GovernanceEvent } from "@/types/governance";

function buildEvent(overrides: Partial<GovernanceEvent> = {}): GovernanceEvent {
  return {
    id: "event-1",
    category: "agent_execution",
    session_id: FIXTURE_SESSION_ID,
    trace_id: "trace-1",
    agent_id: "requirements-specialist",
    timestamp: "2026-09-01T12:00:00Z",
    detail: {},
    ...overrides,
  };
}

describe("PhaseTrackingPage (Governance)", () => {
  it("shows real governance events/approvals for a mission with no tracked phases, instead of an empty page", async () => {
    mockFetchSequence([
      {
        match: "/peer-review/events",
        response: [
          buildEvent({ id: "event-1", category: "agent_registration", agent_id: "requirements-specialist" }),
          buildEvent({
            id: "event-2",
            category: "agent_execution",
            detail: { step_id: "analyze-requirements", output_preview: "Extracted 6 requirements." },
          }),
        ],
      },
      { match: "/approvals", response: [] },
      { match: "/phases", response: [] },
    ]);

    renderWithProviders(<PhaseTrackingPage />, { sessionId: FIXTURE_SESSION_ID });

    expect(await screen.findByText("Governance")).toBeInTheDocument();
    expect(await screen.findByText(/🧩 Agent Registered/)).toBeInTheDocument();
    expect(await screen.findByText(/🤖 Agent Execution/)).toBeInTheDocument();
    expect(screen.getByText("Extracted 6 requirements.")).toBeInTheDocument();
    expect(screen.getByText("Compliant")).toBeInTheDocument();
    // A mission with no tracked phases (e.g. discover_requirements) must
    // not render the modernization-only phase tracker section at all.
    expect(screen.queryByText("Modernization phase tracking")).not.toBeInTheDocument();
  });

  it("shows a warning compliance state and lets the user approve a pending checkpoint", async () => {
    const fetchMock = mockFetchSequence([
      { match: "/peer-review/events", response: [] },
      {
        match: "/approvals",
        response: [
          {
            id: "approval-1",
            checkpoint_id: "nonproduction-release-approval",
            session_id: FIXTURE_SESSION_ID,
            trace_id: "trace-1",
            requested_by_agent_id: "release-agent",
            subject_type: "nonproduction_release",
            subject_id: "run-1",
            status: "pending",
            requested_at: "2026-09-01T12:00:00Z",
            expires_at: null,
          },
        ],
      },
      { match: "/phases", response: [] },
      {
        match: "/decide",
        response: {
          id: "decision-1",
          request_id: "approval-1",
          decision: "approved",
          decided_by: "user",
          decided_at: "2026-09-01T12:01:00Z",
          rationale: "",
        },
      },
    ]);

    renderWithProviders(<PhaseTrackingPage />, { sessionId: FIXTURE_SESSION_ID });

    expect(await screen.findByText("Attention Required")).toBeInTheDocument();
    const approveButton = await screen.findByRole("button", { name: /^Approve$/i });
    await userEvent.click(approveButton);

    await waitFor(() => {
      const decideCall = fetchMock.mock.calls.find((call) => String(call[0]).endsWith("/decide"));
      expect(decideCall).toBeDefined();
      const [, init] = decideCall as unknown as [string, RequestInit];
      const body = JSON.parse(init.body as string);
      expect(body.decision).toBe("approved");
    });
  });

  it("additionally shows the modernization phase tracker for a mission that has tracked phases", async () => {
    mockFetchSequence([
      { match: "/peer-review/events", response: [] },
      { match: "/approvals", response: [] },
      {
        match: "/phases",
        response: [
          {
            id: "phase-1",
            name: "Discover & Assess",
            tasks: [
              {
                definition: { id: "task-1", name: "Inventory the repository" },
                state: {
                  id: "task-state-1",
                  session_id: FIXTURE_SESSION_ID,
                  phase_id: "phase-1",
                  task_id: "task-1",
                  status: "pending",
                  evidence_uri: null,
                  evidence_provider: null,
                  evidence_verified_at: null,
                  evidence_reference: null,
                  detail: "",
                  updated_by: "genie",
                  updated_at: "2026-09-01T12:00:00Z",
                },
              },
            ],
          },
        ],
      },
    ]);

    renderWithProviders(<PhaseTrackingPage />, { sessionId: FIXTURE_SESSION_ID });

    expect(await screen.findByText("Modernization phase tracking")).toBeInTheDocument();
    expect(await screen.findByText("Discover & Assess")).toBeInTheDocument();
    expect(screen.getByText("Inventory the repository")).toBeInTheDocument();
  });
});
