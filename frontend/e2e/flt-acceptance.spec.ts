import { expect, test } from "@playwright/test";

import { as, cspViolations, PASSWORD, signedIn, until } from "./support";

// Fleet & Assets acceptance (Prompt 76; requirements-pilot.md §57, D-41) on the real stack.
// `make acceptance` runs it after the Evacuation spec (Playwright orders files by name). The
// Phase 1 spec checks Nairobi's fleet before the unrest (4 of 5), after scene 4 (VH-02 blocked
// and in the zone, 3 of 5, 20 seats for 16) and after scene 5 (assigned to EVN-1001). By now
// INC-<year>-1042 is ACTIVE again (the Document Expiry spec) and EVN-1001 is complete, so
// nothing is assigned. This spec plays NBO-FLEET from the presenter bar: VH-04 into the
// impact zone and back, then VH-05 back from the workshop; then a Security Officer's status
// change, the Viewer, the Cairo Head of Mission and the audit. It needs that run first.

interface Asset {
  id: string;
  code: string;
  status: string;
  status_reason: string | null;
  location_label: string;
  available: boolean;
  driver_assigned: boolean;
  driver_name: string | null;
  tags: { code: string; reference: string | null }[];
}
interface MaintenanceItem {
  asset_code: string;
  task: string;
  alert: boolean;
  done_by_type: string | null;
}
interface Incident {
  id: string;
  reference: string;
  status: string;
}
interface Scenario {
  status: string;
  current_scene: number;
  scene_complete: boolean;
}

const SCENARIO = "NBO-FLEET";
const year = new Date().getUTCFullYear();
const INCIDENT = `INC-${year}-1042`;

test("Fleet & Assets acceptance: NBO-FLEET, the geofence, the workshop, status, the Viewer", async ({
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
  const missions = await duty.get<{ id: string; code: string }[]>("/api/missions");
  const nbo = missions.find((m) => m.code === "NBO")?.id ?? "";
  const assets = async (client = duty) =>
    Object.fromEntries(
      (await client.get<Asset[]>(`/api/fleet/assets?mission_id=${nbo}`)).map((a) => [a.code, a]),
    );
  const tags = async (code: string) => (await assets())[code]?.tags.map((t) => t.code) ?? [];
  const sceneDone = (scene: number) =>
    until(async () => {
      const s = await duty.get<Scenario>(`/api/scenarios/${SCENARIO}`);
      return s.current_scene === scene && (s.scene_complete || s.status !== "PLAYING") ? true : undefined;
    }, `scene ${scene} played`);

  // --- 0. INC-1042 ACTIVE, after the Phase 1 run: VH-02 blocked and in the zone ---------------
  const incident = (await duty.get<Incident[]>("/api/incidents")).find((i) => i.reference === INCIDENT);
  expect(incident, "run after the Phase 1 spec, from reset-demo").toBeTruthy();
  if (!incident) return;
  if (incident.status !== "ACTIVE") {
    expect((await duty.patch(`/api/incidents/${incident.id}/status`, { status: "ACTIVE" })).ok()).toBeTruthy();
  }
  expect(await tags("VH-02")).toEqual(["BLOCKED", "IN_ZONE"]);
  expect(await tags("VH-04")).toEqual([]); // at the residence: at site (plan-pilot-flt G-1)
  expect((await assets())["VH-05"]?.status).toBe("MAINTENANCE");
  const page = await signedIn(browser, "duty.officer", `/fleet?mission=${nbo}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Fleet & Assets");
  await expect(page.getByText("GPS + telematics (simulated)")).toBeVisible();
  const alert = page.getByTestId("fleet-alert");
  await expect(alert).toContainText(`VH-02 · Haile Selassie Ave · driver needs help (${INCIDENT})`);
  await expect(alert).not.toContainText("VH-04");
  const table = page.getByRole("table", { name: "Vehicles and critical assets" });
  await expect(table.locator('tr[data-asset="VH-02"]')).toContainText("BLOCKED · DRIVER SOS");
  await expect(page.getByRole("table", { name: "Maintenance alerts" })).toContainText("VH-05");

  // --- 1. NBO-FLEET scene 1: VH-04 into the zone; the alert and a FLEET entry (FLT-05) --------
  const bar = page.getByRole("toolbar", { name: "Presenter" });
  await bar.getByLabel("Scenario").selectOption(SCENARIO);
  await expect(bar).toContainText("Ready");
  await bar.getByRole("button", { name: "Next scene" }).click();
  await sceneDone(1);
  await until(async () => ((await tags("VH-04")).includes("IN_ZONE") ? true : undefined), "VH-04 in the zone");
  // The presenter bar opened /fleet with the default mission; Nairobi has the ACTIVE incident.
  await page.getByRole("combobox", { name: "Mission" }).selectOption(nbo);
  await expect(alert).toContainText(`VH-04 · Uhuru Highway · in the impact zone of ${INCIDENT}`, { timeout: 20_000 });
  await expect(alert).toContainText("Latest zone crossing: VH-04");

  // --- 2. Scene 2: back to the residence and out of the zone --------------------------------
  await bar.getByRole("button", { name: "Next scene" }).click();
  await sceneDone(2);
  await until(async () => ((await tags("VH-04")).length === 0 ? true : undefined), "VH-04 back at site");
  const timeline = await duty.get<{ timeline: { event_type: string; summary: string; actor_type: string }[] }>(
    `/api/incidents/${incident.id}`,
  );
  const fleetEntries = timeline.timeline.filter((e) => e.event_type === "FLEET");
  expect(fleetEntries.map((e) => e.summary)).toEqual(
    expect.arrayContaining([
      `VH-04 entered the impact zone of ${INCIDENT} · Waiyaki Way.`,
      `VH-04 left the impact zone of ${INCIDENT} · Residence.`,
    ]),
  );
  expect(fleetEntries).toHaveLength(2);
  expect(new Set(fleetEntries.map((e) => e.actor_type))).toEqual(new Set(["SYSTEM"]));

  // --- 3. Scene 3: the simulated workshop returns VH-05 (FLT-04, G-7) ------------------------
  await bar.getByRole("button", { name: "Next scene" }).click();
  await sceneDone(3);
  const vh05 = await until(async () => {
    const a = (await assets())["VH-05"];
    return a?.status === "AVAILABLE" ? a : undefined;
  }, "VH-05 back from the workshop");
  expect([vh05.available, vh05.status_reason]).toEqual([true, null]);
  const brakes = (await duty.get<MaintenanceItem[]>(`/api/fleet/maintenance?mission_id=${nbo}`)).find(
    (m) => m.asset_code === "VH-05" && m.task === "Brake service",
  );
  expect([brakes?.alert, brakes?.done_by_type]).toEqual([false, "WORKSHOP"]);
  await page.getByRole("combobox", { name: "Mission" }).selectOption(nbo);
  await expect(table.locator('tr[data-asset="VH-05"]')).toContainText("AVAILABLE", { timeout: 20_000 });
  await expect(page.getByRole("table", { name: "Maintenance alerts" })).toHaveCount(0);
  const capacity = page.getByLabel("Evacuation capacity");
  await expect(capacity).toContainText("Seats available23"); // VH-01 4 + VH-03 13 + VH-04 3 + VH-05 3
  await expect(capacity).toContainText("Capacity sufficient.");

  // --- 4. A Security Officer sets VH-03 to maintenance with a reason; a Viewer cannot ---------
  const vh03 = (await assets())["VH-03"]?.id ?? "";
  expect((await viewer.patch(`/api/fleet/assets/${vh03}/status`, { status: "MAINTENANCE", reason: "x" })).status()).toBe(403);
  expect((await homCairo.patch(`/api/fleet/assets/${vh03}/status`, { status: "MAINTENANCE", reason: "x" })).status()).toBe(403);
  const officer = await signedIn(browser, "security.officer", `/fleet?mission=${nbo}`);
  await officer.getByRole("table", { name: "Vehicles and critical assets" }).locator('tr[data-asset="VH-03"]').click();
  await officer.getByRole("combobox", { name: "New status" }).selectOption("MAINTENANCE");
  await officer.getByLabel("Reason").fill("Tyre puncture");
  await officer.getByRole("button", { name: "Set status" }).click();
  await until(async () => ((await assets())["VH-03"]?.status === "MAINTENANCE" ? true : undefined), "VH-03 in maintenance");
  expect((await assets())["VH-03"]?.status_reason).toBe("Tyre puncture");
  await expect(table.locator('tr[data-asset="VH-03"]')).toContainText("MAINTENANCE", { timeout: 20_000 }); // live
  expect((await security.patch(`/api/fleet/assets/${vh03}/status`, { status: "AVAILABLE" })).ok()).toBeTruthy();
  await officer.context().close();

  // --- 5. Driver names only within the scope (FLT-07, G-8) ----------------------------------
  expect((await assets())["VH-02"]?.driver_name).toBe("Peter Mwangi");
  for (const [who, client] of [
    ["viewer", viewer],
    ["hom.cairo", homCairo],
  ] as const) {
    const seen = await assets(client);
    expect([seen["VH-02"]?.driver_assigned, seen["VH-02"]?.driver_name], who).toEqual([true, null]);
    expect(seen["VH-02"]?.tags.map((t) => t.code), who).toEqual(["BLOCKED", "IN_ZONE"]);
    expect(JSON.stringify(seen), who).not.toContain("Peter Mwangi");
  }
  const viewerPage = await signedIn(browser, "viewer", `/fleet?mission=${nbo}`);
  const viewed = viewerPage.getByRole("table", { name: "Vehicles and critical assets" });
  await expect(viewed.locator('tr[data-asset="VH-02"]')).toContainText("BLOCKED · DRIVER SOS");
  await viewed.locator('tr[data-asset="VH-02"]').click();
  await expect(viewerPage.getByRole("table", { name: "Asset details" })).toContainText("Driver assigned");
  await expect(viewerPage.getByText("Peter Mwangi")).toHaveCount(0);
  await expect(viewerPage.getByRole("button", { name: /Set status|Mark done/ })).toHaveCount(0);
  await viewerPage.context().close();

  // --- 6. Every change audited, and the chain verifies (D-20) -------------------------------
  const trail = async (code: string) =>
    (await admin.get<{ action: string; actor_type: string }[]>(
      `/api/audit?entity_type=fleet_asset&entity_id=${code}&limit=500`,
    )).map((e) => [e.action, e.actor_type]);
  expect((await trail("VH-04")).filter(([a]) => a === "FLEET.POSITION")).toEqual(
    Array(10).fill(["FLEET.POSITION", "SYSTEM"]), // the residence and five out (scene 1), four back (G-5)
  );
  expect(await trail("VH-05")).toEqual(
    expect.arrayContaining([
      ["FLEET.MAINTENANCE_DONE", "SYSTEM"],
      ["FLEET.STATUS", "SYSTEM"],
    ]),
  );
  expect((await trail("VH-03")).filter(([a]) => a === "FLEET.STATUS")).toEqual([
    ["FLEET.STATUS", "USER"],
    ["FLEET.STATUS", "USER"],
  ]);
  expect(await admin.get<{ intact: boolean }>("/api/audit/verify")).toMatchObject({ intact: true });

  expect(cspViolations).toEqual([]);
});
