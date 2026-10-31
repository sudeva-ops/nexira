import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { DUTY_OFFICER, mockApi, renderApp } from "../test/render";
import { formatTime } from "./time";

beforeEach(() => {
  mockApi({ "/api/me": { body: DUTY_OFFICER } });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("app shell", () => {
  it("lists exactly the Phase 1 screens and the approved pilot modules (D-25, D-30)", () => {
    renderApp("/");
    const nav = screen.getByRole("navigation", { name: "Main" });
    const labels = within(nav)
      .getAllByRole("link")
      .map((a) => a.textContent);
    expect(labels).toEqual([
      "Decision Queue",
      "AI Agents",
      "Global Operations",
      "Incidents",
      "People & Sites",
      "Journey Management", // pilot module 2 (D-30)
      "Air Travel Tracking", // pilot module 3 (D-30)
      "Response Playbooks",
      "Mass Notification", // pilot module 1 (D-30)
      "Assistance Partners", // pilot module 5 (D-30, D-36)
      "Safety Check-in",
      "Document Expiry", // pilot module 7 (D-30, D-37), under PLAN & INSIGHT (plan-pilot-dx G-9)
      "Audit",
    ]);
    for (const outOfScope of ["Evacuation", "Copilot", "Executive", "Integrations", "OSINT"]) {
      expect(within(nav).queryByText(new RegExp(outOfScope, "i"))).toBeNull();
    }
  });

  it("uses the Decision Queue as the home screen", () => {
    renderApp("/");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Decision Queue");
  });

  it("shows GST and UTC clocks in the header", () => {
    renderApp("/incidents");
    expect(screen.getByTestId("clock-home")).toBeInTheDocument();
    expect(screen.getByTestId("clock-utc")).toBeInTheDocument();
  });
});

describe("user menu", () => {
  it("shows the name and roles from GET /api/me with a bearer token", async () => {
    const fetchMock = mockApi({ "/api/me": { body: DUTY_OFFICER } });
    renderApp("/");
    expect(await screen.findByTestId("user-name")).toHaveTextContent("Daniel Mercer");
    expect(screen.getByTestId("user-roles")).toHaveTextContent("DUTY_OFFICER");
    const init = fetchMock.mock.calls[0]?.[1];
    expect(init?.headers).toMatchObject({ Authorization: "Bearer test-token" });
  });

  it("shows mission-scoped roles with their mission", async () => {
    mockApi({
      "/api/me": {
        body: {
          ...DUTY_OFFICER,
          display_name: "Layla Haddad",
          roles: [{ code: "HEAD_OF_MISSION", mission_id: "m1", mission_code: "NBO" }],
        },
      },
    });
    renderApp("/");
    expect(await screen.findByTestId("user-roles")).toHaveTextContent("HEAD_OF_MISSION · NBO");
  });

  it("signs out", async () => {
    const onLogout = vi.fn();
    renderApp("/", onLogout);
    await userEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(onLogout).toHaveBeenCalledOnce();
  });
});

describe("formatTime", () => {
  it("shows GST as UTC+4", () => {
    const t = new Date("2026-10-24T22:30:05Z");
    expect(formatTime(t, "UTC")).toBe("22:30:05");
    expect(formatTime(t, "Asia/Dubai")).toBe("02:30:05");
  });
});
