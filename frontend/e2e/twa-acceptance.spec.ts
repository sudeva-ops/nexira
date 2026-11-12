import { expect, type Page, test } from "@playwright/test";

import { as, cspViolations, PASSWORD, signedIn, until } from "./support";

// Site Twin live activity acceptance (Prompt 138; requirements-pilot.md §119, D-53;
// plan-pilot-twa §6) on the real stack. `make acceptance` runs it last, after the graphics
// spec's reset, which leaves the normal day off (G-2). The Duty Officer switches it on
// from the presenter bar; a move then reaches the plan and "Recent movements" for the Duty
// Officer and the Viewer, by kind and zone, with no name; it is audited and the chain verifies.
// NBO-SITE mid-scenario pauses the day; after its last scene it resumes. The camera wall's
// counts are the plan's. The day is switched off again at the end.

interface Movement {
  at: string;
  kind: string;
  from_zone: string | null;
  to_zone: string | null;
}
interface Movements {
  movements: Movement[];
  arrivals_today: number;
  departures_today: number;
  visitors_waiting: number;
}
interface Twin {
  site: { id: string; name: string };
  zones: { code: string; name: string; count: number }[];
  occupants: { kind: string; name: string | null; zone_code: string }[];
  sensors: { code: string; kind: string; zone_code: string | null; status: string }[];
}
interface Scenario {
  status: string;
  current_scene: number;
  scene_complete: boolean;
}

const QUIET_S = 150; // longer than the day's slowest step (75 s), twice over

test("Site Twin live activity: a normal day, moves for every role, paused by NBO-SITE", async ({
  browser,
  request,
}) => {
  test.skip(!PASSWORD, "DEMO_USER_PASSWORD is not set (run through `make acceptance`)");
  test.setTimeout(15 * 60_000);
  const duty = await as(request, "duty.officer");
  const viewer = await as(request, "viewer");
  const admin = await as(request, "admin");
  const embassy = (await duty.get<{ id: string; name: string }[]>("/api/sites/twin")).find(
    (s) => s.name === "Embassy Nairobi",
  );
  expect(embassy, "run from `make reset-demo`").toBeTruthy();
  if (!embassy) return;
  const movements = (client = duty) => client.get<Movements>(`/api/sites/${embassy.id}/twin/movements`);
  const twin = (client = duty) => client.get<Twin>(`/api/sites/${embassy.id}/twin`);
  const latest = async () => (await movements()).movements[0]?.at ?? "";
  const moveAfter = (since: string, what: string) =>
    until(async () => {
      const at = await latest();
      return at > since ? at : undefined;
    }, what, QUIET_S);
  const staffNames = (await twin()).occupants.flatMap((o) => (o.name ? [o.name] : []));
  expect(staffNames.length, "the Duty Officer sees staff names").toBeGreaterThan(0);
  expect((await duty.get<{ on: boolean }>("/api/scenarios/normal-day")).on, "reset-demo sets it off").toBe(false);

  // --- 1. The presenter switches the normal day on (TWN-13, G-2) ------------------------------
  const page = await signedIn(browser, "duty.officer", "/twin");
  const reader = await signedIn(browser, "viewer", "/twin");
  const day = page.getByRole("toolbar", { name: "Presenter" }).getByRole("checkbox", { name: "Normal day" });
  await expect(day).not.toBeChecked();
  const before = await latest();
  await page.getByRole("toolbar", { name: "Presenter" }).getByText("Normal day").click();
  await expect(day).toBeChecked();
  expect((await duty.get<{ on: boolean }>("/api/scenarios/normal-day")).on).toBe(true);
  const switched = await admin.get<{ action: string; actor_type: string; details: { on?: boolean } }[]>(
    "/api/audit?limit=50",
  );
  expect(switched.find((e) => e.action === "SITE.NORMAL_DAY")).toMatchObject({ actor_type: "USER", details: { on: true } });

  // --- 2. A move, for the Duty Officer and the Viewer, never who (TWN-12, TWN-14) -------------
  const moved = await moveAfter(before, "a move of the normal day");
  const [first] = (await movements()).movements;
  expect(first?.at).toBe(moved);
  const line = (m: Movement) =>
    m.from_zone === null ? `Arrived · ${m.to_zone}` : m.to_zone === null ? `Left · ${m.from_zone}` : `${m.from_zone} → ${m.to_zone}`;
  for (const [who, screen] of [
    ["duty.officer", page],
    ["viewer", reader],
  ] as const) {
    const strip = screen.getByLabel("Recent movements");
    await expect(strip, who).toContainText(line(first as Movement), { timeout: 20_000 });
    const text = (await strip.textContent()) ?? "";
    for (const name of staffNames) expect(text, `${who}: ${name}`).not.toContain(name);
    expect(text, who).not.toMatch(/Visitor \d|Guard \d/); // labels stay off the strip
  }
  expect(JSON.stringify(await movements(viewer))).not.toMatch(new RegExp(staffNames.join("|")));
  // The plan draws each person in their zone: the people per zone are the API's counts.
  const now = await twin();
  for (const z of now.zones) {
    await expect(
      page.getByRole("img", { name: "Embassy Nairobi floor plan" }).locator(`g.nx-twn-person[data-zone="${z.code}"]`),
      z.code,
    ).toHaveCount(z.count, { timeout: 20_000 });
  }

  // The record: SITE.PRESENCE by the access-control feed, and the chain verifies (TWN-13).
  const trail = await admin.get<{ action: string; actor_type: string; details: Record<string, unknown> }[]>(
    `/api/audit?entity_type=site&entity_id=${embassy.id}&limit=20`,
  );
  const presence = trail.find((e) => e.action === "SITE.PRESENCE");
  expect(presence?.actor_type).toBe("SYSTEM");
  expect(Object.keys(presence?.details ?? {}).sort()).toEqual(expect.arrayContaining(["from", "kind", "to"]));
  expect(await admin.get<{ intact: boolean }>("/api/audit/verify")).toMatchObject({ intact: true });

  // --- 3. The camera wall's counts are the plan's (TWN-15) ------------------------------------
  const counts = Object.fromEntries((await twin()).zones.map((z) => [z.code, z.count]));
  const cameras = (await twin()).sensors.filter((s) => s.kind === "CCTV" && s.status !== "OFFLINE");
  const tiles = page.locator(".nx-cctv-tile [data-camera]");
  await expect(tiles.first()).toBeVisible();
  for (const tile of await tiles.all()) {
    const code = await tile.getAttribute("data-camera");
    const zone = cameras.find((c) => c.code === code)?.zone_code;
    if (!zone) continue;
    await expect(tile, code ?? "").toContainText(`${counts[zone]} in zone · access control (simulated)`, {
      timeout: 20_000,
    });
  }

  // --- 4. NBO-SITE mid-scenario pauses the day; after its last scene it resumes (G-3) ---------
  const sceneDone = (scene: number) =>
    until(async () => {
      const s = await duty.get<Scenario>("/api/scenarios/NBO-SITE");
      return s.current_scene === scene && (s.scene_complete || s.status !== "PLAYING") ? true : undefined;
    }, `NBO-SITE scene ${scene}`);
  expect((await duty.post("/api/scenarios/NBO-SITE/next")).ok()).toBe(true);
  await sceneDone(1); // faults, and presence back as seeded
  const paused = await latest();
  await page.waitForTimeout(QUIET_S * 1000);
  expect(await latest(), "no move while NBO-SITE is mid-scenario").toBe(paused);
  for (const scene of [2, 3]) {
    expect((await duty.post("/api/scenarios/NBO-SITE/next")).ok()).toBe(true);
    await sceneDone(scene);
  }
  await moveAfter(await latest(), "the day resumed after the scenario");

  // --- 5. Off again, as reset-demo leaves it ---------------------------------------------------
  await page.getByRole("toolbar", { name: "Presenter" }).getByText("Normal day").click();
  await expect(day).not.toBeChecked();
  expect((await duty.get<{ on: boolean }>("/api/scenarios/normal-day")).on).toBe(false);
  await closeAll([page, reader]);
  expect(cspViolations).toEqual([]);
});

async function closeAll(pages: Page[]): Promise<void> {
  for (const p of pages) await p.context().close();
}
