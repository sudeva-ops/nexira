import { expect, type Page, test } from "@playwright/test";

import { as, cspViolations, PASSWORD, signedIn, until } from "./support";

// Predictive Risk acceptance (Prompt 105; requirements-pilot.md §82 as amended by
// plan-pilot-prd §11 and G-1 option B; D-46) on the real stack. `make acceptance` runs it after
// the Notification spec (Playwright orders files by name). The calm forecast and Nairobi's are
// checked in the Phase 1 spec, the only place they exist. Here: ADD-FORECAST from the presenter
// bar takes Addis Ababa over 70; the screen shows it; the Forecast agent's advice names no visit;
// the Viewer reads it and cannot dismiss it; a Duty Officer dismisses it; all of it is audited.

interface Rising {
  mission_id: string;
  mission_code: string;
  now: number;
  peak: number;
  peak_day: string;
  crosses: boolean;
}
interface Overview {
  threshold: number;
  rising: Rising[];
  actions: { mission_code: string; text: string }[];
}
interface MissionRisk {
  now: number;
  history: { day: string; source: string }[];
  forecast: { day: string; value: number }[];
  events: { title: string; starts_on: string }[];
}
interface Proposal {
  id: string;
  action_type: string;
  status: string;
  effective_level: number;
  title: string;
  can_dismiss: boolean;
  can_decide: boolean;
}
interface Scenario {
  current_scene: number;
  scene_complete: boolean;
  status: string;
}

const SCENARIO = "ADD-FORECAST";
const RALLY = "Rally near the industrial park";
const ADVICE = "ADVISE_READINESS_CHECK";
const card = (page: Page, id: string) => page.locator(`[data-proposal-id="${id}"]`);
const plusDays = (day: string, n: number) =>
  new Date(Date.parse(`${day}T00:00:00Z`) + n * 86_400_000).toISOString().slice(0, 10);

test("Predictive Risk acceptance: ADD-FORECAST, the screen, the advice, the Viewer, the audit", async ({
  browser,
  request,
}) => {
  test.skip(!PASSWORD, "DEMO_USER_PASSWORD is not set (run through `make acceptance`)");
  test.setTimeout(180_000);
  const duty = await as(request, "duty.officer");
  const viewer = await as(request, "viewer");
  const admin = await as(request, "admin");
  const overview = () => duty.get<Overview>("/api/predictive/overview");
  const advice = async () =>
    (await duty.get<Proposal[]>("/api/proposals?limit=200")).filter((p) => p.action_type === ADVICE);
  const add = (await duty.get<{ id: string; code: string }[]>("/api/missions")).find((m) => m.code === "ADD");
  expect(add, "the seeded Addis Ababa mission").toBeTruthy();
  const addRisk = () => duty.get<MissionRisk>(`/api/predictive/missions/${add?.id}`);
  const sceneDone = (scene: number) =>
    until(async () => {
      const s = await duty.get<Scenario>(`/api/scenarios/${SCENARIO}`);
      return s.current_scene === scene && (s.scene_complete || s.status !== "PLAYING") ? true : undefined;
    }, `scene ${scene} played`);

  // --- 0. Before: the rally is not in the calendar, Addis stays below 70, no advice -------------
  const before = await addRisk();
  const today = before.history.at(-1)?.day ?? "";
  expect(before.history.at(-1)?.source).toBe("LIVE");
  expect(before.events.map((e) => e.title)).not.toContain(RALLY);
  expect((await overview()).rising.find((r) => r.mission_code === "ADD")?.crosses).toBe(false);
  expect(await advice(), "run from `make reset-demo`").toEqual([]);

  // --- 1. ADD-FORECAST scene 1 from the presenter bar (PRD-05, PRD-08) -------------------------
  const page = await signedIn(browser, "duty.officer", "/predictive");
  const bar = page.getByRole("toolbar", { name: "Presenter" });
  await bar.getByLabel("Scenario").selectOption(SCENARIO);
  await expect(bar).toContainText("Ready");
  await bar.getByRole("button", { name: "Next scene" }).click();
  await sceneDone(1);
  const after = await until(async () => {
    const o = await overview();
    return o.rising[0]?.mission_code === "ADD" && o.rising[0].crosses ? o : undefined;
  }, "Addis Ababa first in rising risk, over 70");
  const addis = after.rising[0] as Rising;
  expect(addis.peak).toBeGreaterThanOrEqual(after.threshold);
  expect(addis.peak_day).toBe(plusDays(today, 5)); // the rally's day
  expect(
    after.actions.some((a) => a.mission_code === "ADD" && a.text.includes(`around ${RALLY}`)),
  ).toBe(true);
  const risk = await addRisk();
  expect(risk.events.filter((e) => e.starts_on === plusDays(today, 5)).map((e) => e.title)).toEqual(
    expect.arrayContaining([RALLY, "Counter-demonstration"]),
  );
  expect(Math.max(...risk.forecast.map((f) => f.value))).toBe(addis.peak);

  // --- 2. The screen: rising risk, the chart, the action, the calendar (PRD-07) ---------------
  // The presenter bar opens /predictive (SCENE_SCREEN); Addis is the first row of rising risk.
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Predictive Risk");
  const rising = page.getByRole("table", { name: "Rising risk" });
  await expect(rising.locator("tbody tr").first()).toHaveAttribute("data-mission", "ADD");
  await rising.locator('tr[data-mission="ADD"]').click();
  const chart = page.getByRole("img", {
    name: `Addis Ababa risk index: ${risk.now} today, a forecast peak of ${addis.peak} within 14 days, threshold 70`,
  });
  await expect(chart).toBeVisible();
  for (const part of ["prd-history", "prd-forecast", "prd-band", "prd-threshold"]) {
    await expect(chart.getByTestId(part), part).toBeAttached();
  }
  await expect(chart).toContainText("Elevated threshold · 70");
  await expect(page.getByLabel("Recommended actions")).toContainText(`Addis Ababa around ${RALLY}`);
  await expect(page.getByLabel("Events calendar")).toContainText(RALLY);
  await expect(page.getByRole("note")).toContainText("Model output is advisory.");

  // --- 3. The Forecast agent's advice: level 4, no visit, the Viewer reads it (PRD-06, G-1) -----
  const [proposal] = await until(async () => {
    const found = await advice();
    return found.length ? found : undefined;
  }, "the Forecast agent's advice");
  expect(await advice()).toHaveLength(1);
  expect([proposal?.status, proposal?.effective_level]).toEqual(["PENDING", 4]);
  expect(proposal?.title).toMatch(/^Addis Ababa risk forecast \d+ → \d+ by /);
  const asViewer = await viewer.get<Proposal>(`/api/proposals/${proposal?.id}`);
  expect([asViewer.can_dismiss, asViewer.can_decide]).toEqual([false, false]);
  expect(JSON.stringify(asViewer).toLowerCase()).not.toContain("visit"); // restricted (VIP-06)
  const viewerQueue = await signedIn(browser, "viewer", "/");
  const viewerCard = card(viewerQueue, proposal?.id ?? "");
  await expect(viewerCard).toContainText("Addis Ababa risk forecast");
  await expect(viewerCard.getByRole("button", { name: "Dismiss" })).toHaveCount(0);
  await expect(viewerCard.getByRole("button", { name: /^Approve/ })).toHaveCount(0);
  expect(
    (await viewer.post(`/api/proposals/${proposal?.id}/reject`, { reason: "Not needed" })).status(),
  ).toBe(403);

  // --- 4. The Viewer sees the screen (PRD-07) --------------------------------------------------
  await viewerQueue.goto("/predictive");
  await expect(viewerQueue.getByRole("heading", { level: 1 })).toHaveText("Predictive Risk");
  await expect(
    viewerQueue.getByRole("table", { name: "Rising risk" }).locator('tr[data-mission="ADD"]'),
  ).toBeVisible();
  await viewerQueue.context().close();

  // --- 5. A Duty Officer dismisses the advice; nothing else changes (PRD-06) -------------------
  await page.goto("/");
  const dutyCard = card(page, proposal?.id ?? "");
  await dutyCard.getByRole("button", { name: "Dismiss" }).click();
  await dutyCard.getByRole("button", { name: "Handled offline" }).click();
  await until(
    async () => ((await advice()).find((p) => p.id === proposal?.id)?.status === "REJECTED" ? true : undefined),
    "the advice dismissed",
  );
  expect(await advice()).toHaveLength(1); // a dismissal raises nothing new

  // --- 6. Audited, and the chain verifies (D-20) -----------------------------------------------
  const actions = async (query: string) =>
    (await admin.get<{ action: string }[]>(`/api/audit?${query}&limit=500`)).map((e) => e.action);
  expect(await actions("entity_type=risk_index")).toContain("PREDICTIVE.SNAPSHOT");
  expect((await actions("entity_type=mission_event")).filter((a) => a === "PREDICTIVE.EVENT").length).toBeGreaterThanOrEqual(2);
  expect(await actions(`entity_type=agent_proposal&entity_id=${proposal?.id}`)).toEqual(
    expect.arrayContaining(["PROPOSAL.CREATE", "PROPOSAL.REJECT"]),
  );
  expect(await admin.get<{ intact: boolean }>("/api/audit/verify")).toMatchObject({ intact: true });

  expect(cspViolations).toEqual([]);
});
