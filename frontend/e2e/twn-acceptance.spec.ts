import { expect, test } from "@playwright/test";

import { as, cspViolations, PASSWORD, signedIn, until } from "./support";

// Site Twin acceptance (Prompt 88; requirements-pilot.md §67, D-43) on the real stack.
// `make acceptance` runs it after the Travel & Air spec (Playwright orders files by name). By
// now INC-<year>-1042 is ACTIVE again (the Document Expiry spec) and the Phase 1 run has sent
// PB-07's shelter alert (step 4), so Nairobi shelters; EVN-1001 is complete, so no route shows
// (the Phase 1 spec checks Route B while it was ACTIVE, plan G-3). This spec plays NBO-SITE from
// the presenter bar: the faults, the shelter and the recovery; then the readiness tick, names by
// scope and the audit.

interface Twin {
  site: { id: string; name: string };
  zones: { code: string; count: number }[];
  occupants: { kind: string; name: string | null; label: string | null }[];
  sensors: { code: string; status: string; detail: string | null }[];
  systems: { code: string; state: string; fuel_pct: number | null }[];
  counts: {
    on_site: number;
    staff: number;
    guards: number;
    visitors: number;
    safe_room: number;
    safe_room_capacity: number | null;
    sensors_online: number;
    sensors: number;
    faults: number;
  };
  shelter: { incident_reference: string } | null;
  route: unknown;
  readiness: { score: number | null; items: { id: string | null; label: string; done: boolean }[] };
  simulated: boolean;
}
interface Scenario {
  status: string;
  current_scene: number;
  scene_complete: boolean;
}

const SCENARIO = "NBO-SITE";
const year = new Date().getUTCFullYear();
const INCIDENT = `INC-${year}-1042`;
const STAFF = ["Omar Siddiqui", "Martin Keller", "James Otieno"];

test("Site Twin acceptance: the embassy, NBO-SITE faults, shelter and recovery, readiness, names", async ({
  browser,
  request,
}) => {
  test.skip(!PASSWORD, "DEMO_USER_PASSWORD is not set (run through `make acceptance`)");
  test.setTimeout(300_000);
  const duty = await as(request, "duty.officer");
  const security = await as(request, "security.officer");
  const viewer = await as(request, "viewer");
  const homCairo = await as(request, "hom.cairo");
  const admin = await as(request, "admin");

  const embassy = (await duty.get<{ id: string; name: string }[]>("/api/sites/twin")).find(
    (s) => s.name === "Embassy Nairobi",
  );
  expect(embassy, "run from `make reset-demo`").toBeTruthy();
  if (!embassy) return;
  const twin = (client = duty) => client.get<Twin>(`/api/sites/${embassy.id}/twin`);
  const sceneDone = (scene: number) =>
    until(async () => {
      const s = await duty.get<Scenario>(`/api/scenarios/${SCENARIO}`);
      return s.current_scene === scene && (s.scene_complete || s.status !== "PLAYING") ? true : undefined;
    }, `scene ${scene} played`);
  const incident = (await duty.get<{ id: string; reference: string; status: string }[]>("/api/incidents")).find(
    (i) => i.reference === INCIDENT,
  );
  expect(incident?.status, "run after the Phase 1 and Document Expiry specs").toBe("ACTIVE");
  const siteEntries = async () =>
    (
      await duty.get<{ timeline: { event_type: string; summary: string; actor_type: string }[] }>(
        `/api/incidents/${incident?.id}`,
      )
    ).timeline.filter((e) => e.event_type === "SITE");

  // --- 0. The seeded embassy (TWN-01..05) -----------------------------------------------------
  const seeded = await twin();
  expect(seeded.counts).toEqual({
    on_site: 25,
    staff: 11,
    guards: 3,
    visitors: 11,
    safe_room: 0,
    safe_room_capacity: 20,
    sensors_online: 43,
    sensors: 43,
    faults: 0,
  });
  expect(seeded.readiness.score).toBe(79); // site.readiness_score, as People & Sites (G-1)
  expect(seeded.systems.map((s) => s.code)).toEqual(["GEN-NBO", "SAT-NBO"]); // from Fleet
  expect(seeded.systems[0]?.fuel_pct).toBe(72);
  expect(seeded.shelter?.incident_reference).toBe(INCIDENT); // PB-07 step 4, INC-1042 ACTIVE
  expect(seeded.route).toBeNull(); // EVN-1001 is complete
  expect(seeded.simulated).toBe(true);
  const page = await signedIn(browser, "duty.officer", "/twin");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Site Twin");
  await expect(page.getByText("11 staff · 3 guards · 11 visitors")).toBeVisible();
  await expect(page.getByText("43 / 43", { exact: true })).toBeVisible();
  await expect(page.getByTestId("twin-shelter")).toContainText(`Shelter-in-place active (${INCIDENT})`);
  await expect(page.getByRole("img", { name: "Embassy Nairobi floor plan" }).locator("circle")).toHaveCount(25);
  const before = (await siteEntries()).length;

  // --- 1. NBO-SITE scene 1: Gate 2 reader FAULT, camera 7 OFFLINE (TWN-03) --------------------
  const bar = page.getByRole("toolbar", { name: "Presenter" });
  await bar.getByLabel("Scenario").selectOption(SCENARIO);
  await expect(bar).toContainText("Ready");
  await bar.getByRole("button", { name: "Next scene" }).click();
  await sceneDone(1);
  const faulty = await until(async () => {
    const t = await twin();
    return t.counts.faults === 2 ? t : undefined;
  }, "two faults");
  expect(faulty.counts.sensors_online).toBe(41);
  expect(faulty.sensors.find((s) => s.code === "G2-READER")).toMatchObject({
    status: "FAULT",
    detail: "Fault · manual guard",
  });
  expect(faulty.readiness.items.find((i) => i.label === "All access points monitored")?.done).toBe(false);
  await expect(page.getByText("41 / 43", { exact: true })).toBeVisible({ timeout: 20_000 }); // live
  const entries = (await siteEntries()).slice(before);
  expect(entries.map((e) => e.summary)).toEqual([
    "Embassy Nairobi · Gate 2 · badge reader: FAULT (Fault · manual guard).",
    "Embassy Nairobi · Camera 7: OFFLINE (Offline).",
  ]);
  expect(new Set(entries.map((e) => e.actor_type))).toEqual(new Set(["SYSTEM"]));

  // --- 2. Scene 2: shelter, 9 / 20 in the safe room (TWN-02, TWN-04) -------------------------
  await bar.getByRole("button", { name: "Next scene" }).click();
  await sceneDone(2);
  const sheltered = await until(async () => {
    const t = await twin();
    return t.counts.safe_room === 9 ? t : undefined;
  }, "nine in the safe room");
  const zones = Object.fromEntries(sheltered.zones.map((z) => [z.code, z.count]));
  expect([zones.safe, zones.comms, zones.conf, sheltered.counts.on_site]).toEqual([9, 2, 11, 25]);
  expect(sheltered.sensors.find((s) => s.code === "G1-MAIN")?.detail).toBe("Locked down");
  await expect(page.getByTestId("twin-shelter")).toContainText(
    "9 staff in the safe room, 2 staff in the IT room, 11 visitors held in the conference room.",
    { timeout: 20_000 },
  );
  await expect(page.getByText("9 / 20", { exact: true })).toBeVisible();

  // --- 3. Scene 3: recovery, 43 / 43 -----------------------------------------------------------
  await bar.getByRole("button", { name: "Next scene" }).click();
  await sceneDone(3);
  await until(async () => ((await twin()).counts.faults === 0 ? true : undefined), "the systems recovered");
  await expect(page.getByText("43 / 43", { exact: true })).toBeVisible({ timeout: 20_000 });
  expect((await siteEntries()).length - before).toBe(4); // two faults, two recoveries

  // --- 4. Readiness: a Security Officer ticks; the Viewer cannot (TWN-05) ----------------------
  const open = seeded.readiness.items.find((i) => i.label === "Generator load test witnessed");
  expect(open?.done).toBe(false);
  expect((await viewer.post(`/api/sites/readiness/${open?.id}/done`)).status()).toBe(403);
  expect((await homCairo.post(`/api/sites/readiness/${open?.id}/done`)).status()).toBe(403);
  const officer = await signedIn(browser, "security.officer", "/twin");
  await officer.getByRole("button", { name: "Mark done: Generator load test witnessed" }).click();
  await until(
    async () =>
      (await twin()).readiness.items.find((i) => i.label === "Generator load test witnessed")?.done ? true : undefined,
    "the item done",
  );
  expect((await security.post(`/api/sites/readiness/${open?.id}/done`)).status()).toBe(409); // once
  await officer.context().close();

  // --- 5. Names only within the people scope (§68 Q3) ------------------------------------------
  const names = (await twin()).occupants.filter((o) => o.kind === "STAFF").map((o) => o.name);
  expect(names).toEqual(expect.arrayContaining(STAFF));
  for (const [who, client] of [
    ["viewer", viewer],
    ["hom.cairo", homCairo],
  ] as const) {
    const seen = await twin(client);
    expect(seen.counts.on_site, who).toBe(25);
    expect(seen.occupants.every((o) => o.name === null), who).toBe(true);
    for (const name of STAFF) expect(JSON.stringify(seen), `${who} ${name}`).not.toContain(name);
  }
  const viewerPage = await signedIn(browser, "viewer", "/twin");
  await expect(viewerPage.getByText("11 staff · 3 guards · 11 visitors")).toBeVisible();
  await expect(viewerPage.getByRole("button", { name: /Mark done/ })).toHaveCount(0);
  expect(await viewerPage.content()).not.toContain("Omar Siddiqui");
  await viewerPage.context().close();

  // --- 6. Every change audited, and the chain verifies (D-20) ---------------------------------
  const trail = (
    await admin.get<{ action: string; actor_type: string; details: Record<string, unknown> }[]>(
      `/api/audit?entity_type=site&entity_id=${embassy.id}&limit=500`,
    )
  ).map((e) => [e.action, e.actor_type, JSON.stringify(e.details)] as const);
  const actions = trail.map(([a]) => a);
  for (const action of ["SITE.SEED", "SITE.SENSOR", "SITE.PRESENCE", "SITE.READINESS_DONE"]) {
    expect(actions, action).toContain(action);
  }
  expect(trail.filter(([a]) => a === "SITE.PRESENCE")).toHaveLength(20); // 9 staff and 11 visitors
  expect(trail.filter(([a]) => a === "SITE.READINESS_DONE").map(([, t]) => t)).toEqual(["USER"]);
  for (const name of STAFF) expect(JSON.stringify(trail), name).not.toContain(name);
  expect(await admin.get<{ intact: boolean }>("/api/audit/verify")).toMatchObject({ intact: true });

  expect(cspViolations).toEqual([]);
});
