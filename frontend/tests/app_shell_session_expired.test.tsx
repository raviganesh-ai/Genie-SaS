import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { FluentProvider } from "@fluentui/react-components";
import { genieDarkTheme } from "@/styles/theme";
import { SessionProvider } from "@/state/SessionContext";
import { AppShell } from "@/layouts/AppShell";
import { mockFetchSequence } from "./testUtils";
import { FIXTURE_SESSION_ID, FIXTURE_WORKFLOW_RUN_ID } from "./fixtures";

/** Renders the real app shell + a minimal route tree, so navigating "Start
 * a new mission" -> "/" can be observed landing on an actual different
 * page, instead of just trusting the button's onClick fired. */
function renderAppShell() {
  return render(
    <FluentProvider theme={genieDarkTheme}>
      <MemoryRouter initialEntries={["/requirements"]}>
        <SessionProvider
          initialSessionId={FIXTURE_SESSION_ID}
          initialWorkflowRunId={FIXTURE_WORKFLOW_RUN_ID}
        >
          <Routes>
            <Route path="/" element={<AppShell />}>
              <Route index element={<div>Landing page marker</div>} />
              <Route path="requirements" element={<div>Requirements page marker</div>} />
            </Route>
          </Routes>
        </SessionProvider>
      </MemoryRouter>
    </FluentProvider>,
  );
}

function renderWithSessionOnly() {
  return render(
    <FluentProvider theme={genieDarkTheme}>
      <MemoryRouter initialEntries={["/"]}>
        <SessionProvider initialSessionId={FIXTURE_SESSION_ID}>
          <Routes>
            <Route path="/" element={<AppShell />}>
              <Route index element={<div>Landing page marker</div>} />
              <Route path="repository-connections" element={<div>Repository page marker</div>} />
            </Route>
          </Routes>
        </SessionProvider>
      </MemoryRouter>
    </FluentProvider>,
  );
}

describe("AppShell session-expired handling", () => {
  it("shows a 'session has expired' takeover instead of the page when the workflow run poll 404s as an unknown session", async () => {
    mockFetchSequence([
      {
        match: `/workflows/runs/${FIXTURE_WORKFLOW_RUN_ID}`,
        status: 404,
        response: { detail: `Unknown session id '${FIXTURE_SESSION_ID}'.` },
      },
      { match: "/peer-review/events", response: [] },
    ]);

    renderAppShell();

    await waitFor(() => expect(screen.getByText(/Your session has expired/i)).toBeInTheDocument());
    expect(screen.queryByText(/Requirements page marker/i)).not.toBeInTheDocument();
  });

  it("navigates to the landing page and resets mission state when 'Start a new mission' is clicked", async () => {
    mockFetchSequence([
      {
        match: `/workflows/runs/${FIXTURE_WORKFLOW_RUN_ID}`,
        status: 404,
        response: { detail: `Unknown session id '${FIXTURE_SESSION_ID}'.` },
      },
      { match: "/peer-review/events", response: [] },
    ]);

    renderAppShell();

    await waitFor(() => expect(screen.getByText(/Your session has expired/i)).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: /start a new mission/i }));

    await waitFor(() => expect(screen.getByText(/Landing page marker/i)).toBeInTheDocument());
  });

  it("does not show the takeover when the run poll has not errored", () => {
    mockFetchSequence([
      { match: `/workflows/runs/${FIXTURE_WORKFLOW_RUN_ID}`, response: { workflow_run_id: FIXTURE_WORKFLOW_RUN_ID, workflow_id: "solution-discovery-workflow", session_id: FIXTURE_SESSION_ID, status: "in_progress", waves: [], step_results: [], detail: "" } },
      { match: "/peer-review/events", response: [] },
    ]);

    renderAppShell();

    expect(screen.getByText(/Requirements page marker/i)).toBeInTheDocument();
    expect(screen.queryByText(/Your session has expired/i)).not.toBeInTheDocument();
  });
});

describe("AppShell mission navigation", () => {
  it("disables steps that need a session until one exists, and re-enables them once it does", async () => {
    mockFetchSequence([{ match: "/peer-review/events", response: [] }]);
    renderWithSessionOnly();

    // Repository Analysis only needs a created session (not a running
    // workflow) - FIXTURE_SESSION_ID is set, so it must be a real,
    // clickable link.
    const repoLink = screen.getByRole("link", { name: /repository analysis/i });
    await userEvent.click(repoLink);
    expect(await screen.findByText(/repository page marker/i)).toBeInTheDocument();

    // Architecture (now "UI & Agent Design") needs an active workflow run,
    // which this render has none of - it must not be a clickable link at all.
    expect(screen.queryByRole("link", { name: /ui & agent design/i })).not.toBeInTheDocument();
    expect(screen.getByText("4. UI & Agent Design").closest("[aria-disabled]")).not.toBeNull();
  });

  it("disables every session-gated step when there is no session at all", () => {
    mockFetchSequence([{ match: "/peer-review/events", response: [] }]);
    render(
      <FluentProvider theme={genieDarkTheme}>
        <MemoryRouter initialEntries={["/"]}>
          <SessionProvider>
            <Routes>
              <Route path="/" element={<AppShell />}>
                <Route index element={<div>Landing page marker</div>} />
              </Route>
            </Routes>
          </SessionProvider>
        </MemoryRouter>
      </FluentProvider>,
    );

    expect(screen.queryByRole("link", { name: /repository analysis/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /architecture/i })).not.toBeInTheDocument();
    // Home is always open regardless of session state.
    expect(screen.getByRole("link", { name: /home/i })).toBeInTheDocument();
  });
});
