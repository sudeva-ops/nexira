import { expect, test } from "@playwright/test";

import { as, cspViolations, PASSWORD, signedIn, until } from "./support";

// VIP & Delegation Protection acceptance (Prompt 82; requirements-pilot.md §62, D-42) on the real
// stack. `make acceptance` runs it after the Travel & Air spec (Playwright orders files by name).
// It needs the seeded VV-<year>-031 still PLANNED, so a fresh `make reset-demo` (a live visit
// stays live). The presenter plays ADD-VISIT; people propose, refuse and approve the change
// (G-1: the HQ Crisis Director decides); the Viewer, Travel Desk and the Cairo Head of Mission
// never learn the visit exists, through the API, the screen, the audit or realtime.

interface Reason {
  level: string;
  text: string;
  incident_reference: string | null;
}
interface Segment {
  id: string;
  seq: number;
  kind: string;
  starts_at: string;
  ends_at: string | null;
  status: string;
  risk: string;
  reasons: Reason[];
  recommendation: string | null;
  pending_change: { id: string; status: string } | null;
}
interface Visit {
  id: string;
  reference: string;
  status: string;
  risk: string;
  source: string;
  simulated: boolean;
  segments: Segment[];
  changes: { id: string; status: string; decided_by_name: string | null }[];
  detail: { vehicles: { code: string; state: string }[] };
  checklist: { id: string; label: string; done: boolean }[];
  kpis: { venues: number; venues_surveyed: number };
}
interface Scenario {
  status: string;
  current_scene: number;
  scene_complete: boolean;
}

const SCENARIO = "ADD-VISIT";
const year = new Date().getUTCFullYear();
const REFERENCE = `VV-${year}-031`;
const OUTSIDERS = ["viewer", "travel.desk", "hom.cairo"] as const;

test("VIP Protection acceptance: the seeded visit, ADD-VISIT, two-person change, checklist, restriction", async ({
  browser,
  request,
}) => {
  test.skip(!PASSWORD, "DEMO_USER_PASSWORD is not set (run through `make acceptance`)");
  test.setTimeout(300_000);
  const security = await as(request, "security.officer");
  const hq = await as(request, "hq.director");
  const duty = await as(request, "duty.officer");
  const admin = await as(request, "admin");
  const outsiders = await Promise.all(OUTSIDERS.map(async (u) => [u, await as(request, u)] as const));

  const visitId = (await security.get<{ id: string; reference: string }[]>("/api/vip/visits")).find(
    (v) => v.reference === REFERENCE,
  )?.id;
  expect(visitId, "the seeded visit (run from `make reset-demo`)").toBeTruthy();
  if (!visitId) return;
  const visit = (client = security) => client.get<Visit>(`/api/vip/visits/${visitId}`);
  const site = async () => (await visit()).segments.find((s) => s.kind === "SITE_VISIT");
  const sceneDone = (scene: number) =>
    until(async () => {
      const s = await duty.get<Scenario>(`/api/scenarios/${SCENARIO}`);
      return s.current_scene === scene && (s.scene_complete || s.status !== "PLAYING") ? true : undefined;
    }, `scene ${scene} played`);

  // --- 0. The seeded visit (VIP-01..03) --------------------------------------------------------
  const seeded = await visit();
  expect(seeded.status, "run from `make reset-demo`: a live visit stays live").toBe("PLANNED");
  expect(seeded.segments.map((s) => [s.kind, s.risk])).toEqual([
    ["ARRIVAL", "LOW"],
    ["MOTORCADE", "MODERATE"],
    ["MEETING", "LOW"],
    ["EVENT", "MODERATE"],
    ["SITE_VISIT", "LOW"],
    ["DEPARTURE", "LOW"],
  ]);
  expect(seeded.risk).toBe("MODERATE");
  expect(seeded.checklist.filter((c) => c.done)).toHaveLength(3);
  expect(seeded.detail.vehicles.map((v) => v.code)).toEqual(["VH-11", "VH-12"]);
  expect(seeded.detail.vehicles.every((v) => v.state !== "UNKNOWN")).toBe(true); // from Fleet
  expect([seeded.simulated, seeded.source]).toEqual([true, "Illustrative visit (simulated)"]);
  for (const key of ['"lat"', '"lon"', '"location"', "POINT"]) {
    expect(JSON.stringify(seeded), key).not.toContain(key); // VIP-04: no position
  }

  // --- 1. Nobody else learns the visit exists (VIP-06) ----------------------------------------
  for (const [who, client] of outsiders) {
    expect(await client.get("/api/vip/access"), who).toEqual({ visible: false });
    expect(await client.get("/api/vip/visits"), who).toEqual([]);
    expect((await client.post(`/api/vip/visits/${visitId}/start`)).status(), who).toBe(404);
    expect(await client.get(`/api/audit?entity_type=vip_visit&entity_id=${REFERENCE}`), who).toEqual([]);
    const allowed = await client.get<Record<string, unknown>>(
      `/api/me/permissions?entity_type=vip_visit&entity_id=${visitId}`,
    );
    expect(allowed.start_visit || allowed.tick_vip_checklist, who).toBe(false);
  }
  // The Viewer watches realtime for the whole run: no visit ever reaches the browser (G-3).
  const viewer = await signedIn(browser, "viewer", "/vip");
  const frames: string[] = [];
  viewer.on("websocket", (ws) => ws.on("framereceived", (f) => frames.push(String(f.payload))));
  await viewer.reload();
  await expect(viewer.getByRole("status", { name: "Realtime live" })).toBeVisible();
  await expect(viewer.getByText("Restricted")).toBeVisible();
  await expect(viewer.getByRole("navigation", { name: "Main" }).getByText("VIP Protection")).toHaveCount(0);

  // --- 2. The screen as the design (VIP-07) ---------------------------------------------------
  const officer = await signedIn(browser, "security.officer", "/vip");
  await expect(officer.getByRole("heading", { level: 1 })).toHaveText("VIP Protection");
  await expect(officer.getByTestId("vip-banner")).toContainText(`Visit ${REFERENCE} · Minister's visit to Addis Ababa`);
  await expect(officer.getByTestId("vip-banner")).toContainText("TRP-8834");
  await expect(officer.getByText("4 / 5")).toBeVisible();
  await expect(officer.getByText("Industrial park pending")).toBeVisible();
  await expect(officer.getByRole("navigation", { name: "Main" }).getByText("VIP Protection")).toBeVisible();
  await expect(officer.getByText("Illustrative visit (simulated)", { exact: false })).toBeVisible();

  // --- 3. ADD-VISIT from the presenter bar: live, then the rally (VIP-04, VIP-08) --------------
  const presenter = await signedIn(browser, "duty.officer", "/vip");
  const bar = presenter.getByRole("toolbar", { name: "Presenter" });
  await bar.getByLabel("Scenario").selectOption(SCENARIO);
  await expect(bar).toContainText("Ready");
  await bar.getByRole("button", { name: "Next scene" }).click();
  await sceneDone(1);
  const live = await until(async () => {
    const v = await visit();
    return v.status === "LIVE" && v.segments[1]?.status === "IN_PROGRESS" ? v : undefined;
  }, "the visit live");
  expect(live.segments[0]?.status).toBe("COMPLETED");
  await expect(presenter.getByTestId("vip-banner")).toContainText("LIVE", { timeout: 20_000 });
  await expect(presenter.getByTestId("vip-banner")).toContainText("programme status only");

  await bar.getByRole("button", { name: "Next scene" }).click();
  await sceneDone(2);
  const high = await until(async () => {
    const s = await site();
    return s?.risk === "HIGH" ? s : undefined;
  }, "the site visit HIGH");
  const rally = high.reasons[0];
  expect(rally?.text).toMatch(/^civil unrest 1\.2 km away · INC-\d{4}-\d{4}$/);
  expect(high.recommendation).toBe("Move it out of the window, or replace it with a virtual alternative");
  await expect(officer.getByTestId("vip-recommendation")).toContainText("Site visit · Industrial park flagged High.", {
    timeout: 20_000, // the screen refetches every 10 s
  });

  // --- 4. The change: proposed, refused to the proposer, approved by HQ (VIP-05, G-1) ----------
  await officer.getByRole("button", { name: "Propose change" }).click();
  await officer.getByLabel("New start").fill("08:00");
  await officer.getByLabel("Reason").fill("Rally planned 1.2 km away");
  await officer.getByRole("button", { name: "Propose", exact: true }).click();
  const pending = await until(async () => (await site())?.pending_change ?? undefined, "the change pending");
  await expect(officer.getByTestId("vip-change")).toContainText("Waiting for the Head of Mission or the HQ Crisis Director");
  const refused = await security.post(`/api/vip/changes/${pending.id}/approve`);
  expect(refused.status()).toBe(403); // the proposer, and not a decider (D-16)
  const cairo = outsiders.find(([who]) => who === "hom.cairo")?.[1];
  expect((await cairo?.post(`/api/vip/changes/${pending.id}/approve`))?.status()).toBe(404);
  const decides = await hq.get<{ decide_vip_change: string[] }>(
    `/api/me/permissions?entity_type=vip_visit&entity_id=${visitId}`,
  );
  expect(decides.decide_vip_change).toEqual([pending.id]);
  const director = await signedIn(browser, "hq.director", "/vip");
  await director.getByTestId("vip-change").getByRole("button", { name: "Approve" }).click();
  const moved = await until(async () => {
    const s = await site();
    return s && !s.pending_change && s.starts_at !== high.starts_at ? s : undefined;
  }, "the site visit moved");
  expect(new Date(moved.starts_at).toISOString()).toBe(
    new Date(new Date(high.starts_at).toISOString().slice(0, 10) + "T05:00:00Z").toISOString(),
  ); // 08:00 in Addis Ababa
  expect(Date.parse(moved.ends_at ?? "") - Date.parse(moved.starts_at)).toBe(
    Date.parse(high.ends_at ?? "") - Date.parse(high.starts_at),
  ); // the duration kept
  expect(moved.risk).toBe("HIGH"); // recalculated: the place, not the time (G-5)
  expect((await visit()).changes[0]).toMatchObject({ status: "APPROVED", decided_by_name: expect.any(String) });
  await expect(officer.getByRole("table", { name: "Programme" }).locator('tr[data-seq="5"]')).toContainText("08:00", {
    timeout: 20_000,
  });

  // --- 5. The checklist: the venue survey ticked (VIP-03) -------------------------------------
  await officer.getByRole("button", { name: "Mark done: Industrial park venue survey" }).click();
  await until(async () => ((await visit()).kpis.venues_surveyed === 5 ? true : undefined), "the survey done");
  await expect(officer.getByText("5 / 5")).toBeVisible({ timeout: 20_000 });
  expect((await security.post(`/api/vip/checklist/${seeded.checklist.find((c) => !c.done)?.id}/done`)).status()).toBe(
    409,
  ); // once

  // --- 6. Scene 3: the forum completes ----------------------------------------------------------
  await bar.getByRole("button", { name: "Next scene" }).click();
  await sceneDone(3);
  await until(async () => {
    const v = await visit();
    return v.segments.slice(0, 4).every((s) => s.status === "COMPLETED") ? true : undefined;
  }, "segments 1-4 completed");

  // --- 7. Still nothing for anyone else; audited; the chain verifies (VIP-06, D-20) -----------
  for (const [who, client] of outsiders) {
    expect(await client.get("/api/vip/visits"), who).toEqual([]);
    expect(await client.get(`/api/audit?entity_type=vip_visit&entity_id=${REFERENCE}`), who).toEqual([]);
  }
  await expect(viewer.getByText("Restricted")).toBeVisible();
  const seen = frames.join("\n");
  expect(frames.length, "the Viewer's socket received events").toBeGreaterThan(0);
  for (const word of [REFERENCE, "VIP", "vip_visit", "Minister", "Industrial park venue"]) {
    expect(seen, word).not.toContain(word);
  }
  const trail = (
    await security.get<{ action: string; actor_type: string }[]>(
      `/api/audit?entity_type=vip_visit&entity_id=${REFERENCE}&limit=500`,
    )
  ).map((e) => e.action);
  for (const action of [
    "VIP.SEED",
    "VIP.START",
    "VIP.SEGMENT",
    "VIP.CHANGE_PROPOSE",
    "VIP.CHANGE_APPROVE",
    "VIP.CHECKLIST_DONE",
  ]) {
    expect(trail, action).toContain(action);
  }
  expect(trail.filter((a) => a === "VIP.SEGMENT")).toHaveLength(8); // scenes 1 and 3
  expect(await admin.get<{ intact: boolean }>("/api/audit/verify")).toMatchObject({ intact: true });
  expect(await duty.get<unknown[]>(`/api/audit?entity_type=vip_visit&entity_id=${REFERENCE}`)).not.toEqual([]);
  // The Decision Queue gained nothing from the rally (plan §9).
  const proposals = await duty.get<{ action_type: string; status: string; incident_reference: string | null }[]>(
    "/api/proposals?limit=200",
  );
  const rallyRef = rally?.text.split(" · ")[1];
  expect(proposals.filter((p) => p.incident_reference === rallyRef && p.status === "PENDING")).toEqual([]);

  expect(cspViolations).toEqual([]);
});
