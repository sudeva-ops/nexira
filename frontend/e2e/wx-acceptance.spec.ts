import { expect, test } from "@playwright/test";

import { as, cspViolations, PASSWORD, signedIn, until } from "./support";

// Weather acceptance (Prompt 42; requirements-pilot.md §27, D-35) on the real stack. `make
// acceptance` runs it last; run alone, it needs `make reset-demo` first (the storm's
// conditions hold for 6 hours, plan G-1). The Duty Officer plays MNL-TROPICAL-STORM from the
// presenter bar; PB-06 is approved in the Decision Queue by a logged-in person.

interface Incident {
  id: string;
  reference: string;
  category: string;
  severity: string;
  confidence: number;
  impact_radius_m: number;
  mission_id: string | null;
}
interface IncidentDetail extends Incident {
  mission_code: string | null;
  exposure_summary: { staff: number; mission_sites: number; trips: number };
}
interface Proposal {
  id: string;
  action_type: string;
  title: string;
  status: string;
  incident_id: string | null;
  action_payload: Record<string, unknown>;
}
interface Run {
  id: string;
  status: string;
  steps: { seq: number; status: string; result: Record<string, unknown> }[];
}
interface Weather {
  mission_code: string;
  condition: string;
  wind_kph: number;
  gust_kph: number;
  source: string;
  stale: boolean;
}
interface Scenario {
  status: string;
  current_scene: number;
  scene_complete: boolean;
}

const SCENARIO = "MNL-TROPICAL-STORM";

test("Weather acceptance: conditions, a Manila storm, PB-06 approved, the trip impacted", async ({
  browser,
  request,
}) => {
  test.skip(!PASSWORD, "DEMO_USER_PASSWORD is not set (run through `make acceptance`)");
  test.setTimeout(300_000);
  const duty = await as(request, "duty.officer");
  const viewer = await as(request, "viewer");
  const admin = await as(request, "admin");
  const missions = await duty.get<{ id: string; code: string }[]>("/api/missions");
  const manila = missions.find((m) => m.code === "MNL")?.id;
  expect(manila).toBeTruthy();
  // The list carries mission_id; only the detail names the mission's code.
  const storm = async () =>
    (await duty.get<Incident[]>("/api/incidents?status=ACTIVE")).find(
      (i) => i.category === "STORM" && i.mission_id === manila,
    );
  const sceneDone = (scene: number) =>
    until(async () => {
      const s = await duty.get<Scenario>(`/api/scenarios/${SCENARIO}`);
      return s.current_scene === scene && (s.scene_complete || s.status !== "PLAYING") ? true : undefined;
    }, `scene ${scene} played`);

  // --- 0. Every mission has current conditions, labelled simulated (WX-01, WX-02) ----------
  const weather = await until(async () => {
    const rows = await viewer.get<Weather[]>("/api/weather");
    return rows.length === 36 ? rows : undefined;
  }, "conditions for all 36 missions");
  expect(weather.filter((w) => w.stale)).toEqual([]);
  expect(weather.find((w) => w.mission_code === "MNL")?.condition, "run from `make reset-demo`").not.toBe("STORM");
  expect(await storm()).toBeUndefined();

  const page = await signedIn(browser, "duty.officer", "/operations");
  const panel = page.getByRole("table", { name: "Weather at missions" });
  await expect(panel.getByRole("row")).toHaveCount(36);
  // The panel's own label; hazard incidents (hz-acceptance, run earlier) carry the same source chip.
  await expect(page.locator(".nx-card-sub", { hasText: "xWeather (simulated)" })).toBeVisible();
  await expect(page.getByTestId("weather-marker-MNL")).toBeAttached();

  // --- 1. Building: Manila worsens, played from the presenter bar (WX-07) ------------------
  const bar = page.getByRole("toolbar", { name: "Presenter" });
  await bar.getByLabel("Scenario").selectOption(SCENARIO);
  await expect(bar).toContainText("Calm");
  await bar.getByRole("button", { name: "Next scene" }).click();
  await sceneDone(1);
  const manilaRow = panel.getByRole("row", { name: /Manila/ });
  await expect(manilaRow).toContainText("Cloudy", { timeout: 20_000 });
  await expect(manilaRow).toContainText("45/65");

  // --- 2. Warning: stormy conditions and one STORM incident exposing the mission (WX-03/04) --
  await bar.getByRole("button", { name: "Next scene" }).click();
  await sceneDone(2);
  await expect(panel.getByRole("row").first()).toContainText("Manila", { timeout: 20_000 }); // worst first
  await expect(manilaRow).toContainText("Storm");
  await expect(manilaRow).toContainText("110/150");
  await expect(page.getByTestId("weather-marker-MNL")).toHaveAttribute("aria-label", /Manila · Storm/);
  const incident = await until(async () => {
    const i = await storm();
    return i?.confidence === 80 ? i : undefined;
  }, "one fused STORM incident (xWeather and Dataminr)");
  expect([incident.severity, incident.impact_radius_m]).toEqual(["CRITICAL", 60_000]);
  const storms = (await duty.get<Incident[]>("/api/incidents?status=ACTIVE")).filter((i) => i.category === "STORM");
  expect(storms).toHaveLength(1);
  const detail = await until(async () => {
    const d = await duty.get<IncidentDetail>(`/api/incidents/${incident.id}`);
    return d.exposure_summary.mission_sites > 0 ? d : undefined;
  }, "the storm's exposure");
  // The mission is 40 km from the storm's centre: inside 60 km, far outside unrest's 5 km.
  expect(detail.mission_code).toBe("MNL");
  expect(detail.exposure_summary.mission_sites).toBe(2); // embassy and residence
  expect(detail.exposure_summary.staff).toBeGreaterThanOrEqual(18);
  expect(detail.exposure_summary.trips).toBe(1); // TRP-8810
  await page.getByTestId(`incident-marker-${incident.reference}`).click();
  await expect(page.getByLabel("Exposure summary")).toBeVisible();
  await expect(page.getByText(`${incident.reference} · Storm`).first()).toBeVisible();

  // --- 3. The Response Planner proposes PB-06; the Duty Officer approves it (WX-05) ---------
  const pb06 = await until(async () => {
    const all = await duty.get<Proposal[]>("/api/proposals?limit=200");
    return all.find(
      (p) => p.action_type === "START_PLAYBOOK" && p.incident_id === incident.id && p.action_payload.playbook_code === "PB-06",
    );
  }, "the PB-06 proposal");
  expect([pb06.status, pb06.title]).toEqual(["PENDING", "Run PB-06 · Severe weather near mission"]);
  const pb07 = (await duty.get<Proposal[]>("/api/proposals?limit=200")).filter(
    (p) => p.incident_id === incident.id && p.action_payload.playbook_code === "PB-07",
  );
  expect(pb07).toEqual([]);
  await page.goto("/");
  await page
    .locator(`[data-proposal-id="${pb06.id}"]`)
    .getByRole("button", { name: "Approve as Duty Officer or Security Officer" })
    .click();
  const run = await until(async () => {
    const runs = await duty.get<Run[]>(`/api/playbook-runs?incident_id=${incident.id}`);
    return runs[0]?.status === "COMPLETED" ? runs[0] : undefined;
  }, "PB-06 completed");
  expect(run.steps.map((s) => s.status)).toEqual(["DONE", "DONE", "DONE", "DONE"]);
  expect(Number(run.steps[2]?.result.recipients)).toBeGreaterThan(0); // the staff alert
  const advisory = await until(async () => {
    const all = await duty.get<Proposal[]>("/api/proposals?limit=200");
    return all.find((p) => p.action_type === "SEND_EXTERNAL_MESSAGE" && p.incident_id === incident.id);
  }, "the Manila citizen advisory proposal (D-31)");
  expect(String(advisory.action_payload.message)).toContain("Tropical storm warning for Manila");

  // --- 4. The seeded trip to Manila is impacted (WX-06) -------------------------------------
  const journeys = await signedIn(browser, "travel.desk", "/journeys");
  const trip = journeys.getByRole("table", { name: "Trips" }).getByRole("row", { name: /TRP-8810/ });
  await expect(trip).toContainText(`Impacted · ${incident.reference}`);
  await journeys.context().close();

  // --- 5. Audited, and the chain verifies (D-20) --------------------------------------------
  const audit = await admin.get<{ action: string; entity_id: string | null }[]>("/api/audit?limit=500");
  expect(audit.some((e) => e.action === "WEATHER.OVERRIDE" && e.entity_id === "MNL")).toBe(true);
  expect(audit.some((e) => e.action === "INCIDENT.CREATE" && e.entity_id === incident.reference)).toBe(true);
  expect(await admin.get<{ intact: boolean }>("/api/audit/verify")).toMatchObject({ intact: true });

  expect(cspViolations).toEqual([]);
});
