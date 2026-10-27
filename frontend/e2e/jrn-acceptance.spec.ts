import { expect, test } from "@playwright/test";

import { as, cspViolations, PASSWORD, signedIn, until } from "./support";

// Pilot module 2 acceptance (Prompt 27; requirements-pilot.md §12, D-32) on the real
// stack, after the Phase 1 and Mass Notification acceptances (`make acceptance` runs all
// three from reset-demo). TRP-8812 "impacted" is checked in the Phase 1 run's scene 2,
// while the Nairobi incident is still ACTIVE.

interface Trip {
  id: string;
  reference: string;
  approval_status: string;
  risk_level: string;
  live_risk: string;
  mission_id: string | null;
  requested_by_name: string | null;
  approved_by_name: string | null;
  approved_risk_level: string | null;
}
interface Incident {
  id: string;
  category: string;
  severity: string;
  mission_id: string | null;
}
interface Person {
  id: string;
  full_name: string;
  person_type: string;
  mission_code: string | null;
}

const LEVELS = ["LOW", "MODERATE", "HIGH", "CRITICAL"];

/** YYYY-MM-DD, n days from today in the home zone (GST). */
function day(n: number): string {
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Dubai" }).format(new Date());
  const d = new Date(`${today}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

test("Journey Management acceptance: a HIGH Paris trip, refusals, checklist, approval", async ({
  browser,
  request,
}) => {
  test.skip(!PASSWORD, "DEMO_USER_PASSWORD is not set (run through `make acceptance`)");
  test.setTimeout(240_000);
  const desk = await as(request, "travel.desk");
  const duty = await as(request, "duty.officer");
  const security = await as(request, "security.officer");
  const viewer = await as(request, "viewer");
  const admin = await as(request, "admin");
  const missions = await duty.get<{ id: string; code: string }[]>("/api/missions");
  const paris = missions.find((m) => m.code === "PAR");
  expect(paris).toBeDefined();

  // --- 0. The France scenario: an ACTIVE civil-unrest incident at the Paris mission -------
  const parisIncident = async () =>
    (await duty.get<Incident[]>("/api/incidents?status=ACTIVE")).find(
      (i) => i.category === "CIVIL_UNREST" && i.mission_id === paris?.id,
    );
  if (!(await parisIncident())) {
    await duty.post("/api/scenarios/FRA-NATIONAL-PROTESTS/reset");
    await duty.post("/api/scenarios/FRA-NATIONAL-PROTESTS/next");
  }
  await until(parisIncident, "the Paris incident", 120);

  // --- 1. The Travel Desk plans a Paris trip for two staff --------------------------------
  const diplomats = (await desk.get<{ items: Person[] }>("/api/people?mission=PAR&person_type=DIPLOMAT&limit=50"))
    .items;
  // Two with names no one else in Paris has, so the planner search finds exactly them.
  const staff = diplomats.filter((p) => diplomats.filter((o) => o.full_name === p.full_name).length === 1).slice(0, 2);
  expect(staff).toHaveLength(2);
  const planner = await signedIn(browser, "travel.desk", "/journeys");
  await planner.getByRole("button", { name: "Plan a trip" }).click();
  await planner.getByLabel("Purpose").fill("Embassy consultations");
  await planner.getByLabel("To (city)").fill("Paris");
  await planner.getByLabel("Country (ISO, e.g. FR)").fill("FR");
  await planner.locator("#trip-starts").fill(day(3));
  await planner.locator("#trip-ends").fill(day(5));
  for (const person of staff) {
    await planner.locator("#trip-people").fill(person.full_name);
    await planner.getByRole("button", { name: `+ ${person.full_name} · PAR` }).first().click();
  }
  await expect(planner.getByLabel("Chosen travellers").getByRole("button")).toHaveCount(2);
  await planner.getByRole("button", { name: "Add segment" }).click();
  await planner.getByRole("group", { name: "Segment 1" }).getByLabel("Title").fill("AF 655");
  await planner.getByRole("button", { name: "Save draft" }).click();
  await planner.waitForURL(/trip=/);
  const tripId = new URL(planner.url()).searchParams.get("trip") ?? "";
  const drafted = await desk.get<Trip>(`/api/trips/${tripId}`);
  await expect(planner.getByText(`${drafted.reference} · Draft`)).toBeVisible();
  expect(drafted.requested_by_name).toBe("Tomas Reyes");

  // --- 2. Submitting rates it HIGH or above (D-32, plan G-1) ------------------------------
  await expect(planner.getByLabel("Destination risk")).toContainText("raised to");
  await planner.getByRole("button", { name: "Submit for approval" }).click();
  await expect(planner.getByText(`${drafted.reference} · Awaiting approval`)).toBeVisible();
  const pending = await desk.get<Trip>(`/api/trips/${tripId}`);
  expect(pending.approval_status).toBe("PENDING");
  expect(LEVELS.indexOf(pending.risk_level)).toBeGreaterThanOrEqual(LEVELS.indexOf("HIGH"));
  expect(pending.mission_id).toBe(paris?.id); // plan G-2: the single mission in France

  // --- 3. Refusals: the requester (the Travel Desk) and anyone without the role ------------
  await expect(planner.getByRole("button", { name: "Approve trip" })).toHaveCount(0);
  await expect(planner.getByRole("button", { name: "Reject" })).toHaveCount(0);
  for (const [who, client] of [
    ["the requester (Travel Desk)", desk],
    ["a Duty Officer", duty],
    ["a Viewer", viewer],
  ] as const) {
    expect((await client.post(`/api/trips/${tripId}/approve`)).status(), who).toBe(403);
  }

  // --- 4. The checklist blocks the Security Officer until all four are ticked (JR-05) -----
  const approver = await signedIn(browser, "security.officer", `/journeys?trip=${tripId}`);
  await expect(approver.getByText(/need all four ticked before approval/)).toBeVisible();
  await expect(approver.getByRole("button", { name: "Approve trip" })).toHaveCount(0);
  const blocked = await security.post(`/api/trips/${tripId}/approve`);
  expect(blocked.status()).toBe(409);
  expect(await blocked.text()).toContain("security_briefing");
  const checklist = approver.getByRole("group", { name: "Pre-travel checklist" });
  for (const item of [
    "Security briefing completed",
    "Travel insurance & medical cover",
    "Emergency contacts verified",
    "Check-in schedule agreed",
  ]) {
    const box = checklist.getByRole("checkbox", { name: item });
    await expect(box).toBeEnabled();
    await checklist.getByText(item, { exact: true }).click(); // the label, as a user does
    await expect(box).toBeChecked();
  }

  // --- 5. The Security Officer approves ------------------------------------------------------
  await approver.getByRole("button", { name: "Approve trip" }).click();
  await expect(approver.getByText(`${drafted.reference} · Approved`)).toBeVisible();
  await expect(checklist.getByRole("checkbox", { name: "Security approval" })).toBeChecked();
  const approved = await security.get<Trip>(`/api/trips/${tripId}`);
  expect([approved.approval_status, approved.approved_by_name]).toEqual(["APPROVED", "Leila Nasser"]);
  expect(LEVELS.indexOf(approved.approved_risk_level ?? "")).toBeGreaterThanOrEqual(
    LEVELS.indexOf(pending.risk_level),
  );
  // The Travel Desk sees it approved, live (TRIP_UPDATED).
  await expect(planner.getByText(`${drafted.reference} · Approved`)).toBeVisible({ timeout: 15_000 });

  // --- 6. Every step is audited and the chain verifies (JR-09, D-20) -------------------------
  const audit = await admin.get<{ action: string; entity_id: string }[]>("/api/audit?limit=500");
  const steps = audit.filter((e) => e.entity_id === drafted.reference).map((e) => e.action).sort();
  expect(steps).toEqual(
    ["TRIP.APPROVE", "TRIP.CHECK", "TRIP.CHECK", "TRIP.CHECK", "TRIP.CHECK", "TRIP.DRAFT", "TRIP.SUBMIT"],
  );
  expect(await admin.get<{ intact: boolean }>("/api/audit/verify")).toMatchObject({ intact: true });

  expect(cspViolations).toEqual([]);
});
