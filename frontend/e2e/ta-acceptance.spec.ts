import { expect, type Page, test } from "@playwright/test";

import { as, cspViolations, PASSWORD, signedIn, until } from "./support";

// Pilot module 4 acceptance (Prompt 37; requirements-pilot.md §22, D-34) on the real stack.
// `make acceptance` runs it last, after the air and France specs have played their
// scenarios; run alone, it plays them itself (from reset-demo). The Travel & Air agent only
// proposes: every action here is decided by a logged-in person in the Decision Queue.
// Refusing new proposals while paused (D-17) is covered by the backend tests; here the
// kill switch shows that people can still decide pending proposals while agents are paused.

interface Proposal {
  id: string;
  agent_code: string;
  action_type: string;
  title: string;
  status: string;
  effective_level: number;
  action_payload: Record<string, unknown>;
}
interface Trip {
  id: string;
  reference: string;
  approval_status: string;
  restricted: boolean;
}
interface Flight {
  flight_number: string;
  status: string;
}
interface Campaign {
  id: string;
  campaign_type: string;
  created_by_type: string;
  audience_filter: Record<string, unknown>;
  recipients: number;
  status: string;
}

const card = (page: Page, id: string) => page.locator(`[data-proposal-id="${id}"]`);

test("Travel & Air acceptance: notify, advise, cancel; people decide; restricted untouched", async ({
  browser,
  request,
}) => {
  test.skip(!PASSWORD, "DEMO_USER_PASSWORD is not set (run through `make acceptance`)");
  test.setTimeout(300_000);
  const duty = await as(request, "duty.officer");
  const desk = await as(request, "travel.desk");
  const admin = await as(request, "admin");
  const travel = async () =>
    (await duty.get<Proposal[]>("/api/proposals?limit=200")).filter((p) => p.agent_code === "TRAVEL_AIR");
  const trips = await duty.get<Trip[]>("/api/trips");
  const byRef = (ref: string) => trips.find((t) => t.reference === ref);
  const trp8818 = byRef("TRP-8818");
  const trp8811 = byRef("TRP-8811");
  const restricted = trips.filter((t) => t.restricted);
  expect([trp8818, trp8811].every(Boolean)).toBe(true);
  // TRP-8813, and TRP-8834 for the VIP visit (D-42), by start date.
  expect(restricted.map((t) => t.reference)).toEqual(["TRP-8813", "TRP-8834"]);

  // --- 0. The scenarios that give the agent something to see --------------------------------
  const xw451 = async () => (await duty.get<Flight[]>("/api/flights")).find((f) => f.flight_number === "XW 451");
  if ((await xw451())?.status === "SCHEDULED") {
    for (let scene = 0; scene < 3; scene += 1) {
      await duty.post("/api/scenarios/NBO-AIR-DIVERSION/next");
    }
    await until(async () => ((await xw451())?.status === "LANDED" ? true : undefined), "XW 451 landed", 120);
  }
  const cancelFor8811 = async () =>
    (await travel()).find((p) => p.action_type === "CANCEL_TRIP" && p.action_payload.trip_id === trp8811?.id);
  if (!(await cancelFor8811())) {
    await duty.post("/api/scenarios/FRA-NATIONAL-PROTESTS/reset");
    await duty.post("/api/scenarios/FRA-NATIONAL-PROTESTS/next");
  }

  // --- 1. XW 451 holding: a notification proposal, approved by the Travel Desk ---------------
  const holding = await until(
    async () => (await travel()).find((p) => p.title === "Notify XW 451 travellers · holding near Nairobi"),
    "the holding notification proposal",
  );
  expect([holding.action_type, holding.effective_level, holding.action_payload.trip_id]).toEqual([
    "NOTIFY_TRAVELLERS",
    2,
    trp8818?.id,
  ]);
  // Kill switch on: no new proposals (backend tests), but people still decide (D-17).
  expect((await admin.post("/api/agents/pause-all")).status()).toBe(200);
  const deskPage = await signedIn(browser, "travel.desk", "/");
  await card(deskPage, holding.id).getByRole("button", { name: "Approve as Travel Desk or Security Officer" }).click();
  await until(
    async () => ((await travel()).find((p) => p.id === holding.id)?.status === "APPROVED" ? true : undefined),
    "the notification approved while agents are paused",
  );
  expect((await admin.post("/api/agents/resume-all")).status()).toBe(200);
  const sent = await until(async () => {
    const campaigns = await duty.get<Campaign[]>("/api/campaigns");
    return campaigns.find((c) => c.audience_filter.trip_id === trp8818?.id && c.recipients === 3);
  }, "the alert to XW 451's three travellers");
  expect([sent.campaign_type, sent.created_by_type]).toEqual(["ALERT", "AGENT"]);
  await deskPage.goto("/notifications");
  await expect(deskPage.getByRole("table", { name: "Campaigns" })).toContainText("A trip's travellers (Travel & Air)");

  // --- 2. Diverted: onward-travel advice that nobody can execute ------------------------------
  const advice = await until(
    async () => (await travel()).find((p) => p.action_type === "ADVISE_REBOOKING" && p.title.includes("Mombasa")),
    "the onward travel advice",
  );
  expect(advice.effective_level).toBe(4);
  expect([403, 409]).toContain((await desk.post(`/api/proposals/${advice.id}/approve`)).status());
  await deskPage.goto("/");
  const adviceCard = card(deskPage, advice.id);
  await expect(adviceCard).toContainText("Advice only: never executed");
  await expect(adviceCard.getByRole("button", { name: /^Approve/ })).toHaveCount(0);
  await expect(adviceCard.getByRole("link", { name: "Open flight →" })).toBeVisible();

  // --- 3. France: cancel TRP-8811, decided by the Security Officer only ------------------------
  const cancel = await until(cancelFor8811, "the TRP-8811 cancel proposal", 120);
  expect(cancel.title).toMatch(/Cancel TRP-8811 Paris · risk now (HIGH|CRITICAL)/);
  expect((await desk.post(`/api/proposals/${cancel.id}/approve`)).status()).toBe(403);
  const securityPage = await signedIn(browser, "security.officer", "/");
  await card(securityPage, cancel.id).getByRole("button", { name: "Approve as Security Officer" }).click();
  await until(async () => {
    const trip = await duty.get<Trip>(`/api/trips/${trp8811?.id}`);
    return trip.approval_status === "CANCELLED" ? true : undefined;
  }, "TRP-8811 cancelled");
  await securityPage.goto(`/journeys?trip=${trp8811?.id}`);
  await expect(securityPage.getByText("TRP-8811 · Cancelled")).toBeVisible();

  // --- 4. Nothing about the restricted trip (TA-07, D-33) ---------------------------------------
  const restrictedIds = new Set(restricted.map((t) => t.id));
  expect((await travel()).filter((p) => restrictedIds.has(String(p.action_payload.trip_id)))).toEqual([]);

  // --- 5. Audited, and the chain verifies (D-20) ----------------------------------------------
  const audit = await admin.get<{ action: string; actor_type: string; entity_id: string }[]>("/api/audit?limit=500");
  expect(audit.some((e) => e.action === "TRIP.CANCEL" && e.entity_id === "TRP-8811" && e.actor_type === "AGENT")).toBe(
    true,
  );
  expect(audit.some((e) => e.action === "AGENTS.PAUSE")).toBe(true);
  expect(audit.some((e) => e.action === "AGENTS.RESUME")).toBe(true);
  expect(await admin.get<{ intact: boolean }>("/api/audit/verify")).toMatchObject({ intact: true });

  expect(cspViolations).toEqual([]);
});
