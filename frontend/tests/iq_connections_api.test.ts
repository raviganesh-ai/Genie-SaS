import { describe, expect, it } from "vitest";
import { iqConnectionsApi } from "@/services/iqConnectionsApi";

describe("iqConnectionsApi.buildStartUrl", () => {
  it("builds a backend URL carrying the session id and provider, never a token", () => {
    const url = iqConnectionsApi.buildStartUrl("session-1", "work_iq");

    const parsed = new URL(url);
    expect(parsed.pathname).toBe("/iq/connections/work_iq/start");
    expect(parsed.searchParams.get("session_id")).toBe("session-1");
    expect(url).not.toMatch(/token/i);
  });

  it("builds a distinct URL per provider", () => {
    const workIqUrl = iqConnectionsApi.buildStartUrl("session-1", "work_iq");
    const fabricIqUrl = iqConnectionsApi.buildStartUrl("session-1", "fabric_iq");

    expect(workIqUrl).not.toBe(fabricIqUrl);
    expect(new URL(fabricIqUrl).pathname).toBe("/iq/connections/fabric_iq/start");
  });
});
