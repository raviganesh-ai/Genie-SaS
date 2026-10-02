import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RepositoryConnectionPage } from "@/features/repository-connections/RepositoryConnectionPage";
import { mockFetchSequence, renderWithProviders } from "./testUtils";
import { FIXTURE_SESSION_ID } from "./fixtures";

const STATUS = {
  configured: true,
  connected: true,
  authentication_mode: "administrator_managed_mcp" as const,
  account_login: "raviganesh-ai",
  server_endpoint: "https://github.example.test/mcp",
  detail: "Connected",
};

const BINDING = {
  id: "binding-1",
  session_id: FIXTURE_SESSION_ID,
  owner_user_id: "owner-1",
  repository_id: 1,
  repository_full_name: "raviganesh-ai/lumen-grove-demo",
  repository_url: "https://github.com/raviganesh-ai/lumen-grove-demo",
  purpose: "code",
  requested_ref: "main",
  resolved_commit: "a".repeat(40),
  included_paths: [],
  excluded_paths: [],
  principal: "raviganesh-ai",
  status: "approved",
  validated_at: "2026-01-01T00:00:00Z",
  created_at: "2026-01-01T00:00:00Z",
};

describe("RepositoryConnectionPage", () => {
  it("sends a modernize_and_deliver mission straight to the modernization plan instead of dependency mapping", async () => {
    mockFetchSequence([
      { match: "/repository-connections/github/status", response: STATUS },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`, response: [BINDING] },
    ]);

    renderWithProviders(<RepositoryConnectionPage />, {
      sessionId: FIXTURE_SESSION_ID,
      missionKind: "modernize_and_deliver",
    });

    const continueButton = await screen.findByRole("button", {
      name: "Continue to modernization plan",
    });
    // The button exists (and is initially disabled) from first render -
    // it only becomes enabled once the async repository-bindings fetch
    // resolves, so this must be awaited rather than asserted immediately
    // after findByRole (which only waits for the element to exist, not
    // for its enabled state) - a race that was flaky on slower CI runners.
    await waitFor(() => expect(continueButton).toBeEnabled());
    expect(
      screen.queryByRole("button", { name: "Continue to dependency mapping" }),
    ).not.toBeInTheDocument();
  });

  it("sends an understand_code mission to dependency mapping as before", async () => {
    mockFetchSequence([
      { match: "/repository-connections/github/status", response: STATUS },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`, response: [BINDING] },
    ]);

    renderWithProviders(<RepositoryConnectionPage />, {
      sessionId: FIXTURE_SESSION_ID,
      missionKind: "understand_code",
    });

    const continueButton = await screen.findByRole("button", {
      name: "Continue to dependency mapping",
    });
    await waitFor(() => expect(continueButton).toBeEnabled());
    expect(
      screen.queryByRole("button", { name: "Continue to modernization plan" }),
    ).not.toBeInTheDocument();
  });

  it("shows platform reference counts and lets the user bind a session-specific architecture override", async () => {
    const user = userEvent.setup();
    const overrideBinding = {
      ...BINDING,
      id: "binding-2",
      purpose: "architecture",
      repository_full_name: "raviganesh-ai/my-opinionated-architecture",
    };
    const snapshot = {
      id: "snapshot-1",
      session_id: FIXTURE_SESSION_ID,
      binding_id: "binding-2",
      repository_full_name: "raviganesh-ai/my-opinionated-architecture",
      commit: "a".repeat(40),
      paths: ["ARCHITECTURE.md"],
      content_hashes: {},
      combined_reference_text: "Use a modular monolith.",
      gaps: [],
      created_at: "2026-01-02T00:00:00Z",
    };
    mockFetchSequence([
      { match: "/repository-connections/github/status", response: STATUS },
      { match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`, response: [BINDING] },
      { match: "/repository-connections/github/repositories", response: { repositories: [{
        repository_id: 2,
        name: "my-opinionated-architecture",
        full_name: "raviganesh-ai/my-opinionated-architecture",
        description: "",
        html_url: "https://github.com/raviganesh-ai/my-opinionated-architecture",
        private: false,
        archived: false,
        default_branch: "main",
        language: null,
        updated_at: null,
      }], total_count: 1, incomplete_results: false, page: 1, per_page: 30 } },
      { match: "/platform-config/reference-repositories", response: [{ id: "ref-1" }] },
      { match: "/platform-config/reference-repositories", response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/architecture-reference`, response: [] },
      { match: `/sessions/${FIXTURE_SESSION_ID}/standards`, response: [] },
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`,
        response: overrideBinding,
      },
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/architecture-reference/ingest/binding-2`,
        response: snapshot,
      },
    ]);

    renderWithProviders(<RepositoryConnectionPage />, {
      sessionId: FIXTURE_SESSION_ID,
      missionKind: "understand_code",
    });

    expect(
      await screen.findByText(/Falls back to your 1 platform-configured architecture reference/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/No standards repository configured anywhere/),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Use a different reference for this mission" }));
    const overrideCombobox = screen.getAllByPlaceholderText(
      "Type to filter repositories visible to the connected identity",
    )[1];
    await user.type(overrideCombobox, "my-opinionated-architecture");
    const option = await screen.findByRole("option", { name: /my-opinionated-architecture/ });
    await user.click(option);
    // Selecting a repository auto-fills "Branch or ref" with its default
    // branch ("main"), so the override can be bound immediately.
    await user.click(screen.getByRole("button", { name: "Use this repository for this mission" }));

    expect(
      await screen.findByText(/This mission uses your own architecture reference/),
    ).toBeInTheDocument();
    expect(screen.getAllByText("raviganesh-ai/my-opinionated-architecture").length).toBeGreaterThan(0);
  });
});
