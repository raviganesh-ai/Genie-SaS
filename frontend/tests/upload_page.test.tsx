import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { UploadPage } from "@/features/upload/UploadPage";
import { mockFetchSequence, renderWithProviders } from "./testUtils";
import { FIXTURE_SESSION_ID } from "./fixtures";

describe("UploadPage", () => {
  it("offers Ask Work IQ as a visible alternative to uploading files", async () => {
    mockFetchSequence([
      { match: `/sessions/${FIXTURE_SESSION_ID}/uploads`, response: [] },
    ]);

    renderWithProviders(<UploadPage />, { sessionId: FIXTURE_SESSION_ID });

    const askLink = await screen.findByRole("button", { name: "Ask Work IQ" });
    expect(askLink).toBeInTheDocument();
    expect(
      screen.getByText(/Rather pull context from meetings and communications/),
    ).toBeInTheDocument();
  });
});
