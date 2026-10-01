import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { ModernizationPage } from "@/features/modernization/ModernizationPage";
import { mockFetchSequence, renderWithProviders } from "./testUtils";
import { FIXTURE_SESSION_ID } from "./fixtures";

describe("ModernizationPage", () => {
  it("offers only configured capabilities instead of a free-text modernization goal", async () => {
    mockFetchSequence([
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/modernization/capabilities`,
        response: [
          {
            id: "runtime_upgrade",
            name: "Language or runtime upgrade",
            description: "Upgrade a supported runtime.",
            target_label: "Target language or runtime version",
            instruction_template: "Upgrade to {target}.",
          },
          {
            id: "standards_remediation",
            name: "Standards conformance remediation",
            description: "Remediate selected findings.",
            target_label: null,
            instruction_template: "Remediate findings.",
          },
        ],
      },
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/repository-bindings`,
        response: [],
      },
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/repository-assessments`,
        response: [],
      },
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/standards`,
        response: [],
      },
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/architecture-reference`,
        response: [],
      },
      {
        match: `/sessions/${FIXTURE_SESSION_ID}/modernization`,
        response: [],
      },
    ]);

    renderWithProviders(<ModernizationPage />, { sessionId: FIXTURE_SESSION_ID });

    expect(await screen.findByLabelText(/Modernization capability/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Target language or runtime version/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Modernization goal")).not.toBeInTheDocument();
    expect(screen.queryByText(/rehost/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/replatform/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/re-architect/i)).not.toBeInTheDocument();
  });
});
