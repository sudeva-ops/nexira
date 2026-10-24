import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { drillAge } from "../../ui/format";
import { PEOPLE, SITES, SUMMARY } from "../../test/fixtures";
import { DUTY_OFFICER, mockApi, renderApp } from "../../test/render";

let fetchMock: ReturnType<typeof mockApi>;

beforeEach(() => {
  fetchMock = mockApi({
    "/api/me": { body: DUTY_OFFICER },
    "/api/operations/summary": { body: SUMMARY },
    "/api/people": { body: PEOPLE },
    "/api/sites": { body: SITES },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("People & Sites", () => {
  it("lists people with location confidence, source and zone status", async () => {
    renderApp("/people");
    const table = await screen.findByRole("table", { name: "People" });
    const peter = within(table).getByText("Peter Mwangi").closest("tr");
    expect(peter).not.toBeNull();
    expect(peter).toHaveTextContent("GPS");
    expect(peter).toHaveTextContent("91%");
    expect(peter).toHaveTextContent("IN ZONE");
    expect(screen.getByText("2 of 2")).toBeInTheDocument();
  });

  it("shows mission property only in the Sites figure (D-23)", async () => {
    renderApp("/people");
    const label = await screen.findByText("Sites", { selector: ".l" });
    await vi.waitFor(() => expect(label.parentElement).toHaveTextContent("74"));
  });

  it("searches on the server", async () => {
    renderApp("/people");
    await screen.findByRole("table", { name: "People" });
    await userEvent.type(screen.getByLabelText("Filter"), "zamalek");
    await vi.waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("q=zamalek"))).toBe(true),
    );
  });

  it("shows sites with readiness and last drill", async () => {
    renderApp("/people");
    await userEvent.click(await screen.findByRole("tab", { name: "Sites" }));
    const table = await screen.findByRole("table", { name: "Sites" });
    const embassy = within(table).getByText("Embassy Nairobi").closest("tr");
    expect(embassy).toHaveTextContent("88");
    expect(embassy).toHaveTextContent("3 weeks ago");
  });

  it("formats drill age", () => {
    const now = new Date("2026-10-24T00:00:00Z");
    expect(drillAge(null, now)).toBe("—");
    expect(drillAge("2026-10-22", now)).toBe("this week");
    expect(drillAge("2026-10-17", now)).toBe("1 week ago");
  });
});
