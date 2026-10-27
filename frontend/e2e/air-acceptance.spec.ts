import { expect, test } from "@playwright/test";

import { as, cspViolations, PASSWORD, signedIn, until } from "./support";

// Pilot module 3 acceptance (Prompt 32; requirements-pilot.md §17, D-33) on the real stack,
// from reset-demo (`make acceptance` runs it with the other three). The presenter plays
// NBO-AIR-DIVERSION in the browser: XW 451 (TRP-8818, three London staff) holds near
// Nairobi, diverts to Mombasa and lands. A LANDED flight is final, so this needs a fresh
// demo database (plan-pilot-air.md §10).

interface Flight {
  id: string;
  flight_number: string;
  status: string;
  diverted_to: string | null;
  travellers: string[];
  trip_reference: string;
}
interface Trip {
  id: string;
  reference: string;
  restricted: boolean;
}
interface TripDetail extends Trip {
  segments: { kind: string; title: string; flight_number: string | null; starts_at: string | null }[];
}
interface Person {
  full_name: string;
  place_label: string | null;
  location_source: string | null;
}

test("Air Travel acceptance: XW 451 holds, diverts to Mombasa and lands; restricted never shown", async ({
  browser,
  request,
}) => {
  test.skip(!PASSWORD, "DEMO_USER_PASSWORD is not set (run through `make acceptance`)");
  test.setTimeout(240_000);
  const duty = await as(request, "duty.officer");
  const viewer = await as(request, "viewer");
  const admin = await as(request, "admin");
  const xw451 = async () => (await duty.get<Flight[]>("/api/flights")).find((f) => f.flight_number === "XW 451");

  // --- 0. Seeded: XW 451 scheduled; the restricted trip has no flight (AT-01, AT-05) --------
  const scheduled = await until(xw451, "XW 451 tracked");
  expect(scheduled.status, "run from `make reset-demo`: a LANDED flight is final").toBe("SCHEDULED");
  expect([scheduled.trip_reference, scheduled.travellers.length]).toEqual(["TRP-8818", 3]);
  const restrictedTrip = (await viewer.get<Trip[]>("/api/trips")).find((t) => t.restricted);
  expect(restrictedTrip?.reference).toBe("TRP-8813");

  // --- 1. The presenter plays the scenario on the Air screen --------------------------------
  const page = await signedIn(browser, "duty.officer", "/air");
  const bar = page.getByRole("toolbar", { name: "Presenter" });
  await bar.getByLabel("Scenario").selectOption("NBO-AIR-DIVERSION");
  await expect(bar).toContainText("Scheduled");
  const row = page.getByRole("table", { name: "Tracked flights" }).getByRole("row", { name: /XW 451/ });

  await bar.getByRole("button", { name: "Next scene" }).click(); // scene 1: inbound
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Air Travel Tracking");
  await expect(row).toContainText("Airborne", { timeout: 20_000 });

  await bar.getByRole("button", { name: "Next scene" }).click(); // scene 2: holding
  await expect(page.getByRole("alert")).toContainText("XW 451 holding near Nairobi", { timeout: 20_000 });
  await expect(row).toContainText("Holding");

  await bar.getByRole("button", { name: "Next scene" }).click(); // scene 3: diverted, then landed
  await expect(page.getByRole("alert")).toContainText("XW 451 diverted to Mombasa", { timeout: 20_000 });
  await expect(row).toContainText("AUH → MBA");
  await expect(row).toContainText("Landed · Mombasa", { timeout: 120_000 }); // live, no reload
  await expect(page.getByRole("alert")).toHaveCount(0);

  // The detail and its events (AT-02, AT-03).
  await row.getByRole("button", { name: "XW 451" }).click();
  const events = page.getByLabel("Flight events");
  for (const step of ["Departed", "Holding · Arrivals restricted", "Diverted to MBA", "Landed · MBA"]) {
    await expect(events).toContainText(step);
  }
  await expect(page.getByRole("link", { name: "TRP-8818" })).toHaveAttribute("href", /\/journeys\?trip=/);

  // --- 2. Landing moved the travellers to Mombasa (AT-04) -------------------------------------
  const landed = await until(async () => {
    const f = await xw451();
    return f?.status === "LANDED" ? f : undefined;
  }, "XW 451 landed");
  expect(landed.diverted_to).toBe("MBA");
  for (const name of landed.travellers) {
    const found = await duty.get<{ items: Person[] }>(`/api/people?q=${encodeURIComponent(name)}&limit=5`);
    const person = found.items.find((p) => p.full_name === name);
    expect([person?.location_source, person?.place_label], name).toEqual([
      "FLIGHT",
      "Mombasa · Mombasa Moi (landed, XW 451)",
    ]);
  }

  // --- 3. The restricted trip's flight never appears (AT-05, plan G-7) -----------------------
  const flights = await duty.get<Flight[]>("/api/flights");
  expect(flights.map((f) => f.trip_reference)).not.toContain("TRP-8813");
  expect(flights.map((f) => f.flight_number)).not.toContain("XW 777");
  await expect(page.getByRole("table", { name: "Tracked flights" })).not.toContainText("TRP-8813");
  const masked = await viewer.get<TripDetail>(`/api/trips/${restrictedTrip?.id}`);
  expect(masked.segments.map((s) => [s.title, s.flight_number, s.starts_at])).toEqual([
    ["Flight (restricted)", null, null],
  ]);
  const viewerPage = await signedIn(browser, "viewer", `/journeys?trip=${restrictedTrip?.id}`);
  await expect(viewerPage.getByLabel("Itinerary")).toContainText("Flight (restricted)");
  await expect(viewerPage.getByLabel("Itinerary")).not.toContainText("XW 777");

  // --- 4. Audited, and the chain verifies (AT-08, D-20) ----------------------------------------
  // The newest 500 rows: this run's steps (FLIGHT.TRACK was written by the seed, long before).
  const audit = await admin.get<{ action: string; entity_id: string }[]>("/api/audit?limit=500");
  const steps = audit.filter((e) => e.entity_id === landed.id).map((e) => e.action);
  for (const step of ["FLIGHT.DEPARTED", "FLIGHT.HOLDING", "FLIGHT.DIVERTED", "FLIGHT.LANDED"]) {
    expect(steps, step).toContain(step);
  }
  expect(JSON.stringify(audit)).not.toContain("XW 777");
  expect(await admin.get<{ intact: boolean }>("/api/audit/verify")).toMatchObject({ intact: true });

  expect(cspViolations).toEqual([]);
});
