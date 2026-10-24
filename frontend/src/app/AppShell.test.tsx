import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { App } from "./App";
import { formatTime } from "./time";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe("app shell", () => {
  it("lists exactly the Phase 1 screens in the navigation (D-25)", () => {
    renderAt("/");
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
      "Response Playbooks",
      "Safety Check-in",
      "Audit",
    ]);
    for (const outOfScope of ["Evacuation", "Copilot", "Executive", "Integrations", "OSINT"]) {
      expect(within(nav).queryByText(new RegExp(outOfScope, "i"))).toBeNull();
    }
  });

  it("uses the Decision Queue as the home screen", () => {
    renderAt("/");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Decision Queue");
  });

  it("shows GST and UTC clocks in the header", () => {
    renderAt("/incidents");
    expect(screen.getByTestId("clock-home")).toBeInTheDocument();
    expect(screen.getByTestId("clock-utc")).toBeInTheDocument();
  });
});

describe("formatTime", () => {
  it("shows GST as UTC+4", () => {
    const t = new Date("2026-10-24T22:30:05Z");
    expect(formatTime(t, "UTC")).toBe("22:30:05");
    expect(formatTime(t, "Asia/Dubai")).toBe("02:30:05");
  });
});
