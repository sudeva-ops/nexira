import { screen } from "@testing-library/react";
import { vi } from "vitest";

import type { AuditEntry } from "../../api/audit";
import { ADMIN, DUTY_OFFICER, mockApi, renderApp } from "../../test/render";

const ENTRY: AuditEntry = {
  chain_seq: 7,
  occurred_at: "2026-10-24T10:00:00+00:00",
  actor_type: "SYSTEM",
  actor_id: "seed",
  action: "ROLE.GRANT",
  entity_type: "user_role",
  entity_id: "g-1",
  details: {},
  prev_hash: "a".repeat(64),
  row_hash: "b".repeat(64),
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("audit screen", () => {
  it("shows the log and an intact chain to administrators", async () => {
    mockApi({
      "/api/me": { body: ADMIN },
      "/api/audit": { body: [ENTRY] },
      "/api/audit/verify": { body: { intact: true, first_broken_seq: null, rows: 7 } },
    });
    renderApp("/audit");
    expect(await screen.findByText("ROLE.GRANT")).toBeInTheDocument();
    expect(await screen.findByText("Hash chain intact")).toBeInTheDocument();
    // DC-01: the figures in a tile row
    const tiles = screen.getByRole("group", { name: "Audit figures" });
    expect(tiles).toHaveTextContent("Entries7");
    expect(tiles).toHaveTextContent("ChainIntact7 entries verified by the database");
  });

  it("reports a broken chain", async () => {
    mockApi({
      "/api/me": { body: ADMIN },
      "/api/audit": { body: [ENTRY] },
      "/api/audit/verify": { body: { intact: false, first_broken_seq: 3, rows: 7 } },
    });
    renderApp("/audit");
    expect(await screen.findByText("Hash chain broken")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Hash chain broken. First broken entry: #3.");
  });

  it("does not show the log to other roles", async () => {
    const fetchMock = mockApi({
      "/api/me": { body: DUTY_OFFICER },
      "/api/audit": { status: 403, body: { detail: "Forbidden" } },
    });
    renderApp("/audit");
    expect(await screen.findByText("Administrators only")).toBeInTheDocument();
    const paths = fetchMock.mock.calls.map(([url]) => String(url).split("?")[0]);
    expect(paths).not.toContain("/api/audit/verify");
  });
});
