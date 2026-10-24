import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { Me } from "../../api/me";
import { at, DETAIL, HOM_CAIRO, HOM_NAIROBI, INCIDENT, VIEWER } from "../../test/fixtures";
import { DUTY_OFFICER, mockApi, renderApp } from "../../test/render";

function setup(me: Me) {
  return mockApi({
    "/api/me": { body: me },
    "/api/incidents": { body: [INCIDENT] },
    [`/api/incidents/${INCIDENT.id}`]: { body: DETAIL },
    [`/api/incidents/${INCIDENT.id}/status`]: { body: { ...DETAIL.timeline[0], event_type: "STATUS" } },
    [`/api/incidents/${INCIDENT.id}/notes`]: { status: 201, body: { ...DETAIL.timeline[0], event_type: "NOTE" } },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Incidents", () => {
  it("shows the register and the source-normalisation table (D-11)", async () => {
    setup(DUTY_OFFICER);
    renderApp("/incidents");
    const register = await screen.findByRole("table", { name: "Incident register" });
    expect(within(register).getByText(INCIDENT.reference)).toBeInTheDocument();

    const table = await screen.findByRole("table", { name: "Source normalisation" });
    expect(within(table).getByRole("columnheader", { name: "Normalised (signal)" })).toBeInTheDocument();
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getAllByRole("cell")[3]?.textContent)).toEqual([
      "HIGH",
      "HIGH",
      "MODERATE",
    ]);
    expect(within(at(rows, 0)).getByText("Dataminr (simulated)")).toBeInTheDocument();
    expect(screen.getByText(/Severity raised from HIGH to CRITICAL/)).toBeInTheDocument();
    expect(screen.getByText("Confidence 92%")).toBeInTheDocument();
    expect(screen.getByLabelText("Timeline")).toHaveTextContent("ESCALATED");
  });

  it("lets a Duty Officer change status and add a note (INC-07)", async () => {
    const fetchMock = setup(DUTY_OFFICER);
    renderApp(`/incidents?id=${INCIDENT.id}`);
    await userEvent.selectOptions(await screen.findByLabelText("Incident status"), "MONITORING");
    await userEvent.click(screen.getByRole("button", { name: "Set status" }));
    await userEvent.type(screen.getByLabelText("Note"), "Embassy staff sheltering.");
    await userEvent.click(screen.getByRole("button", { name: "Add note" }));

    const writes = fetchMock.mock.calls.filter(([, init]) => init?.method);
    expect(writes.map(([url, init]) => [String(url), init?.method, init?.body])).toEqual([
      [`/api/incidents/${INCIDENT.id}/status`, "PATCH", JSON.stringify({ status: "MONITORING" })],
      [`/api/incidents/${INCIDENT.id}/notes`, "POST", JSON.stringify({ text: "Embassy staff sheltering." })],
    ]);
  });

  it.each([
    ["a Viewer", VIEWER, false],
    ["the Cairo Head of Mission", HOM_CAIRO, false],
    ["the Nairobi Head of Mission", HOM_NAIROBI, true],
  ])("shows actions to %s only when allowed (D-05)", async (_who, me, allowed) => {
    setup(me);
    renderApp(`/incidents?id=${INCIDENT.id}`);
    await screen.findByRole("table", { name: "Source normalisation" });
    expect(screen.queryByLabelText("Incident status") !== null).toBe(allowed);
    expect(screen.queryByLabelText("Note") !== null).toBe(allowed);
  });
});
