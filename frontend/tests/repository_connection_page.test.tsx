import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
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
    expect(continueButton).toBeEnabled();
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

    expect(
      await screen.findByRole("button", { name: "Continue to dependency mapping" }),
    ).toBeEnabled();
    expect(
      screen.queryByRole("button", { name: "Continue to modernization plan" }),
    ).not.toBeInTheDocument();
  });
});
