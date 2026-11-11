import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { ADMIN, DUTY_OFFICER, mockApi, renderApp } from "../test/render";
import { SCREENS } from "./screens";
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
      "Health Intelligence", // pilot module 9 (D-30, D-39), before Natural Hazards (§48 Q9)
      "Natural Hazards & Climate", // pilot module 8 (D-30, D-38), last under MONITOR as the design
      "Response Playbooks",
      "Evacuation Management", // pilot module 10 (D-30, D-40), after Response Playbooks
      "Fleet & Assets", // pilot module 11 (D-30, D-41), after Evacuation Management
      "Mass Notification", // pilot module 1 (D-30)
      "Assistance Partners", // pilot module 5 (D-30, D-36)
      "Site Twin", // pilot module 13 (D-30, D-43), after Assistance Partners
      "Safety Check-in",
      "AI Risk Copilot", // pilot module 19 (D-50), after Safety Check-in
      "Document Expiry", // pilot module 7 (D-30, D-37), under PLAN & INSIGHT (plan-pilot-dx G-9)
      "Supply Chain Risk", // pilot module 14 (D-30, D-44), after Document Expiry
      "Predictive Risk", // pilot module 16 (D-30, D-46), before Executive Overview
      "Exercise & Training", // pilot module 18 (D-48), before After-Action Review
      "After-Action Review", // pilot module 17 (D-30, D-47), after Predictive Risk
      "Executive Overview", // pilot module 15 (D-30, D-45), last under PLAN & INSIGHT
    ]); // Audit only for administrators (UIP-07)
    // The Copilot is in scope since D-50.
    for (const outOfScope of ["Integrations", "OSINT"]) {
      expect(within(nav).queryByText(new RegExp(outOfScope, "i"))).toBeNull();
    }
  });

  it("shows Audit in the sidebar to administrators only (UIP-07)", async () => {
    const { unmount } = renderApp("/");
    await screen.findByTestId("user-name"); // the Duty Officer is known, and still no Audit
    expect(within(screen.getByRole("navigation", { name: "Main" })).queryByRole("link", { name: "Audit" })).toBeNull();
    unmount();
    mockApi({ "/api/me": { body: ADMIN } });
    renderApp("/");
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(await within(nav).findByRole("link", { name: "Audit" })).toHaveAttribute("href", "/audit");
  });

  it("gives every screen its own icon (UIP-06)", () => {
    const icons = SCREENS.map((s) => s.icon);
    expect(new Set(icons).size).toBe(icons.length);
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
