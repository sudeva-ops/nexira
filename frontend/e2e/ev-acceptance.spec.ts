import { expect, test } from "@playwright/test";

import { as, cspViolations, PASSWORD, signedIn, until } from "./support";

// Evacuation Management acceptance (Prompt 70; requirements-pilot.md §52, D-40) on the real stack.
// `make acceptance` runs it after the Phase 1 spec (Playwright orders files by name), which checks
// EVP-NBO ready after scenes 1-4 and that the Nairobi Head of Mission's approval of the scene 5
// proposal activates nothing; the HQ Crisis Director's then activates it. This spec takes the
// evacuation on from there: the manifest, the partners, the movement message's second person,
// NBO-EVACUATION from the presenter bar, the Viewer, the Cairo Head of Mission and the audit.
// It needs that run first (from `make reset-demo`).

interface Evacuation {
  id: string;
  reference: string;
  plan_reference: string;
  status: string;
  step: number | null;
  steps: { step: number; name: string; at: string | null }[];
  requested_by_name: string | null;
  activated_by_name: string | null;
  counts: Record<string, number>;
  checked_in: number;
  seats: number | null;
  documents_flagged: number;
  partner_requests: { reference: string; partner_name: string; service: string; status: string }[];
  message_reference: string | null;
  message_status: string | null;
  simulated: boolean;
}
interface Detail extends Evacuation {
  names_shown: boolean;
  manifest: {
    id: string;
    category: string | null;
    seat: string | null;
    status: string;
    name: string | null;
    document_flag: boolean | null;
  }[];
}
interface PartnerRequest {
  reference: string;
  person_id: string | null;
  person_name: string | null;
  note: string | null;
  status: string;
}
interface Campaign {
  id: string;
  reference: string;
  status: string;
  campaign_type: string;
  recipients: number;
  deliveries: Record<string, number>;
}
interface Scenario {
  status: string;
  current_scene: number;
  scene_complete: boolean;
}

const SCENARIO = "NBO-EVACUATION";
const MISSION_COUNT = 16; // diplomats, delegates and dependants (§53 Q3)
const CITIZENS = 44; // 212 exposed, 168 safe in the scene 4 check-in

test("Evacuation Management acceptance: EVP-NBO, manifest, second person, NBO-EVACUATION, the Viewer", async ({
  browser,
  request,
}) => {
  test.skip(!PASSWORD, "DEMO_USER_PASSWORD is not set (run through `make acceptance`)");
  test.setTimeout(360_000);
  const duty = await as(request, "duty.officer");
  const consular = await as(request, "consular.officer");
  const viewer = await as(request, "viewer");
  const homNairobi = await as(request, "hom.nairobi");
  const hqDirector = await as(request, "hq.director");
  const homCairo = await as(request, "hom.cairo");
  const admin = await as(request, "admin");
  const missions = await duty.get<{ id: string; code: string }[]>("/api/missions");
  const nbo = missions.find((m) => m.code === "NBO")?.id ?? "";
  const latest = async () => (await duty.get<Evacuation[]>(`/api/evacuations?mission_id=${nbo}`))[0];
  const sceneDone = (scene: number) =>
    until(async () => {
      const s = await duty.get<Scenario>(`/api/scenarios/${SCENARIO}`);
      return s.current_scene === scene && (s.scene_complete || s.status !== "PLAYING") ? true : undefined;
    }, `scene ${scene} played`);

  // --- 0. EVP-NBO activated by two people at Phase 1 scene 5 (EV-02, EV-03) -------------------
  const evacuation = await latest();
  expect(evacuation, "run after the Phase 1 spec (NBO-CIVIL-UNREST scene 5), from reset-demo").toBeTruthy();
  if (!evacuation) return;
  expect([evacuation.reference, evacuation.plan_reference, evacuation.status, evacuation.step]).toEqual([
    "EVN-1001",
    "EVP-NBO",
    "ACTIVE",
    2,
  ]);
  expect(evacuation.requested_by_name).not.toBe(evacuation.activated_by_name);
  expect(evacuation.simulated).toBe(true);
  expect(evacuation.counts.CITIZEN).toBe(CITIZENS);
  expect(MISSION_COUNT).toBe(
    (evacuation.counts.STAFF ?? 0) + (evacuation.counts.DELEGATE ?? 0) + (evacuation.counts.DEPENDANT ?? 0),
  );
  expect([evacuation.checked_in, evacuation.seats, evacuation.documents_flagged]).toEqual([0, 72, 2]);
  const detail = await duty.get<Detail>(`/api/evacuations/${evacuation.id}`);
  expect([detail.names_shown, detail.manifest.length]).toEqual([true, MISSION_COUNT + CITIZENS]);
  const names = detail.manifest.map((e) => e.name ?? "");
  expect(detail.manifest.filter((e) => e.document_flag).map((e) => e.name).sort()).toEqual([
    "Aiko Takeda",
    "Hana Takeda",
  ]);

  // --- 1. The partners are asked with no names (EV-06, AS-08) ---------------------------------
  expect(evacuation.partner_requests).toHaveLength(2);
  const requests = await duty.get<PartnerRequest[]>("/api/partner-requests");
  for (const asked of evacuation.partner_requests) {
    const row = requests.find((r) => r.reference === asked.reference);
    expect([row?.person_id, row?.person_name], asked.reference).toEqual([null, null]);
    expect(row?.note).toContain(`${MISSION_COUNT + CITIZENS} people`);
    expect(names.filter((n) => row?.note?.includes(n))).toEqual([]);
  }

  // --- 2. The movement message waits for a second person, neither activator (EV-06, D-31) ----
  expect(evacuation.message_status).toBe("PENDING_APPROVAL");
  const message = (await duty.get<Campaign[]>("/api/campaigns")).find((c) => c.reference === evacuation.message_reference);
  expect(message?.campaign_type).toBe("ALERT");
  expect((await homNairobi.post(`/api/campaigns/${message?.id}/approve`)).status()).toBe(403);
  expect((await hqDirector.post(`/api/campaigns/${message?.id}/approve`)).status()).toBe(403);
  const sender = await signedIn(browser, "consular.officer", `/notifications?campaign=${message?.id}`);
  await sender.getByRole("button", { name: "Approve and send" }).click();
  const sent = await until(
    async () => {
      const c = await consular.get<Campaign>(`/api/campaigns/${message?.id}`);
      return c.status === "SENT" && (c.deliveries.READ ?? 0) + (c.deliveries.DELIVERED ?? 0) > 0 ? c : undefined;
    },
    "the movement message sent",
    90,
  );
  expect(sent.recipients).toBeGreaterThan(0);
  expect(sent.deliveries.FAILED ?? 0).toBe(0);
  await sender.context().close();

  // --- 3. The screen: in progress, 60 on the manifest, the Takedas flagged (EV-08) ------------
  const page = await signedIn(browser, "duty.officer", `/evacuation?mission=${nbo}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Evacuation Management");
  const banner = page.getByTestId("evacuation-banner");
  await expect(banner).toContainText("Evacuation EVP-NBO in progress. 0 of 60 evacuees checked in.");
  await expect(page.getByText(`${MISSION_COUNT} mission · ${CITIZENS} registered citizens`)).toBeVisible();
  const table = page.getByRole("table", { name: "Evacuation manifest" });
  await expect(table.locator("tbody tr")).toHaveCount(MISSION_COUNT + CITIZENS);
  await expect(table.getByRole("row", { name: /Hana Takeda/ })).toContainText("EXPIRING");
  await expect(table.getByRole("row", { name: /Aiko Takeda/ })).toContainText("EXPIRING");
  await expect(page.getByText(`Movement message ${evacuation.message_reference} · sent`)).toBeVisible();

  // Neither a Viewer nor the Cairo Head of Mission may check anyone in or stand it down (EV-04, EV-07).
  const entry = detail.manifest[0]?.id ?? "";
  for (const client of [viewer, homCairo]) {
    expect((await client.post(`/api/evacuations/${evacuation.id}/manifest/${entry}/check-in`)).status()).toBe(403);
    expect((await client.post(`/api/evacuations/${evacuation.id}/stand-down`, { reason: "test" })).status()).toBe(403);
  }

  // --- 4. NBO-EVACUATION scene 1: the simulated scanner checks all 60 in, with seats (EV-04) --
  const bar = page.getByRole("toolbar", { name: "Presenter" });
  await bar.getByLabel("Scenario").selectOption(SCENARIO);
  await expect(bar).toContainText("Ready");
  await bar.getByRole("button", { name: "Next scene" }).click();
  await sceneDone(1);
  const mustered = await until(async () => {
    const e = await latest();
    return e?.checked_in === MISSION_COUNT + CITIZENS ? e : undefined;
  }, "everyone checked in", 90);
  expect(mustered.step).toBe(3); // assembly: everyone is in
  await expect(banner).toContainText("60 of 60 evacuees checked in.", { timeout: 20_000 });
  const seated = await duty.get<Detail>(`/api/evacuations/${evacuation.id}`);
  expect(seated.manifest.every((e) => e.status === "CHECKED_IN" && e.seat)).toBe(true);
  expect(new Set(seated.manifest.map((e) => e.seat)).size).toBe(MISSION_COUNT + CITIZENS);
  await expect(table.locator("tbody tr", { hasText: "EXPECTED" })).toHaveCount(0);

  // --- 5. Scenes 2-4: convoy, flight, arrival, in order; COMPLETED (EV-05) --------------------
  for (const scene of [2, 3, 4]) {
    await bar.getByRole("button", { name: "Next scene" }).click();
    await sceneDone(scene);
    await until(async () => ((await latest())?.step === scene + 2 ? true : undefined), `step ${scene + 2}`);
  }
  const done = await latest();
  expect([done?.status, done?.step]).toEqual(["COMPLETED", 6]);
  const times = (done?.steps ?? []).map((s) => Date.parse(s.at ?? ""));
  expect(times.every((t) => !Number.isNaN(t))).toBe(true);
  expect(times).toEqual([...times].sort((a, b) => a - b));
  expect(done?.partner_requests.map((r) => r.status)).toEqual(["COMPLETED", "COMPLETED"]);
  await expect(banner).toContainText("EVN-1001 complete: the evacuees have arrived.", { timeout: 20_000 });
  await expect(page.getByRole("button", { name: /^Next step/ })).toHaveCount(0);

  // --- 6. A Viewer sees counts and no names; so does the Cairo Head of Mission (EV-09) --------
  for (const [who, client] of [
    ["viewer", viewer],
    ["hom.cairo", homCairo],
  ] as const) {
    const seen = await client.get<Detail>(`/api/evacuations/${evacuation.id}`);
    expect([seen.names_shown, seen.manifest.length, seen.checked_in], who).toEqual([false, 60, 60]);
    expect(seen.manifest.every((e) => e.name === null && e.category === null && e.seat === null), who).toBe(true);
    const everything = JSON.stringify([seen, await client.get("/api/evacuations"), await client.get("/api/evacuations/plans")]);
    expect(names.filter((n) => everything.includes(n)), who).toEqual([]);
  }
  const viewerPage = await signedIn(browser, "viewer", `/evacuation?mission=${nbo}`);
  await expect(viewerPage.getByTestId("evacuation-banner")).toContainText("EVN-1001 complete");
  await expect(viewerPage.getByRole("note")).toContainText("you see counts only");
  await expect(viewerPage.getByRole("table", { name: "Evacuation manifest" }).locator("tbody tr")).toHaveCount(60);
  await expect(viewerPage.getByText("Hana Takeda")).toHaveCount(0);
  await viewerPage.context().close();

  // --- 7. Every step audited, and the chain verifies (D-20) ---------------------------------
  const trail = async (type: string, id: string | null | undefined) =>
    (await admin.get<{ action: string }[]>(`/api/audit?entity_type=${type}&entity_id=${id}&limit=500`)).map(
      (e) => e.action,
    );
  const steps = await trail("evacuation", evacuation.reference);
  for (const action of ["EVACUATION.ACTIVATE", "EVACUATION.CHECK_IN"]) expect(steps, action).toContain(action);
  expect(steps.filter((a) => a === "EVACUATION.STEP")).toHaveLength(4); // steps 3-6
  for (const asked of evacuation.partner_requests) {
    expect(await trail("partner_request", asked.reference), asked.reference).toEqual(
      expect.arrayContaining(["PARTNER_REQUEST.CREATE", "PARTNER_REQUEST.COMPLETE"]),
    );
  }
  expect((await trail("notification_campaign", message?.reference)).length).toBeGreaterThanOrEqual(2);
  expect(await admin.get<{ intact: boolean }>("/api/audit/verify")).toMatchObject({ intact: true });

  expect(cspViolations).toEqual([]);
});
