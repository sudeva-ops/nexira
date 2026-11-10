import { expect, type Page, test } from "@playwright/test";

import { as, cspViolations, PASSWORD, signedIn, until } from "./support";

// Exercise & Training acceptance (Prompt 117; requirements-pilot.md §92, D-48; plan-pilot-exr §9)
// on the real stack, run on its own after a demo reset: `make acceptance` resets again before it
// (§93 Q12). The Duty Officer launches the Nairobi civil-unrest exercise from the screen and plays
// scenes 1-4 with Next inject; people respond as in the Phase 1 run (PB-07 by the Duty Officer,
// step 7 by the Nairobi Head of Mission, the advisory); the Duty Officer ends it. The scores agree
// with the After-Action Review metrics of the same record; readiness moves to the new score.

interface Score {
  dimension: string;
  score: number | null;
  measured: Record<string, unknown>;
}
interface Exercise {
  id: string;
  name: string;
  status: string;
  source: string;
  mission_code: string;
  incident_id: string | null;
  incident_reference: string | null;
  overall_score: number | null;
  participants: number | null;
  ended_at: string | null;
  scores: Score[];
  run: { status: string; current_scene: number } | null;
  can_act: boolean;
}
interface Exercises {
  kpis: { templates: number; this_year: number };
  exercises: Exercise[];
}
interface Template {
  code: string;
  mission_code: string;
  can_launch: boolean;
}
interface Incident {
  id: string;
  reference: string;
  confidence: number;
  exercise: boolean;
}
interface Proposal {
  id: string;
  action_type: string;
  status: string;
  incident_id: string | null;
  exercise: boolean;
}
interface Run {
  id: string;
  status: string;
  steps: { id: string; status: string }[];
}
interface Site {
  id: string;
  name: string;
  site_type: string;
  mission_code: string;
  readiness_score: number | null;
  last_drill_on: string | null;
  readiness_source: string | null;
}
interface Executive {
  posture: { level: string };
  active_incidents: number;
  accounted: { pct: number | null };
  readiness: { mean: number | null; sites: number; from_exercises: number; illustrative: number };
}
interface Metric {
  key: string;
  value: number | null;
  met: boolean | null;
}
interface Tally {
  safe: number;
  need_help: number;
  pending: number;
}

const year = new Date().getUTCFullYear();
const INCIDENT = `INC-${year}-1042`;
const TEMPLATE = "NBO-CIVIL-UNREST";
const card = (page: Page, id: string) => page.locator(`[data-proposal-id="${id}"]`);
const halfUp = (v: number) => Math.floor(v + 0.5);

test("Exercise & Training acceptance: launch, respond, end, scores, readiness, the Viewer", async ({
  browser,
  request,
}) => {
  test.skip(!PASSWORD, "DEMO_USER_PASSWORD is not set (run through `make acceptance`)");
  test.setTimeout(420_000);
  const duty = await as(request, "duty.officer");
  const admin = await as(request, "admin");
  const viewer = await as(request, "viewer");
  const hom = await as(request, "hom.nairobi");
  const proposals = () => duty.get<Proposal[]>("/api/proposals?limit=200");

  // --- 0. Templates, the illustrative history and Nairobi's seeded readiness (EXR-01, 06, 07)
  expect(await duty.get<Incident[]>("/api/incidents?status=ACTIVE"), "after a demo reset").toEqual([]);
  const templates = await duty.get<Template[]>("/api/exercises/templates");
  expect(templates.map((t) => [t.code, t.mission_code])).toEqual([
    ["DAC-CYCLONE", "DAC"],
    ["FRA-NATIONAL-PROTESTS", "PAR"],
    ["MNL-TROPICAL-STORM", "MNL"],
    [TEMPLATE, "NBO"],
  ]);
  const history = await duty.get<Exercises>("/api/exercises");
  expect(history.kpis.templates).toBe(4);
  expect(history.exercises.every((e) => e.source === "ILLUSTRATIVE" && e.status === "COMPLETED")).toBe(true);
  expect(new Set(history.exercises.map((e) => e.mission_code)).size).toBe(history.exercises.length); // one each
  const seeded = history.exercises.find((e) => e.mission_code === "NBO");
  const embassy = async () =>
    (await duty.get<{ items: Site[] }>("/api/sites?mission=NBO")).items.find(
      (s) => s.mission_code === "NBO" && s.site_type === "EMBASSY",
    );
  const before = await embassy();
  expect([before?.readiness_score, before?.readiness_source, before?.last_drill_on]).toEqual([
    seeded?.overall_score,
    "ILLUSTRATIVE",
    seeded?.ended_at?.slice(0, 10),
  ]);
  const twin = () =>
    duty.get<{ readiness: { score: number | null; source: string | null } }>(`/api/sites/${before?.id}/twin`);
  expect((await twin()).readiness).toMatchObject({ score: seeded?.overall_score, source: "ILLUSTRATIVE" });
  const executive = () => duty.get<Executive>("/api/executive/overview");
  const calm = await executive();

  // --- 1. Launch from the screen; the banner; a second launch refused (EXR-02, EXR-08) ----------
  const page = await signedIn(browser, "duty.officer", "/exercises");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Exercise & Training");
  const launch = page.getByLabel("Launch an exercise");
  await launch.getByLabel("Template").selectOption(TEMPLATE);
  await launch.getByLabel("Kind").selectOption("FUNCTIONAL");
  await launch.getByRole("button", { name: "Launch" }).click();
  const controls = page.getByLabel("Running exercise");
  await expect(controls).toContainText("RUNNING");
  await expect(page.getByLabel("Exercise running")).toContainText("SIMULATED EXERCISE");
  const exerciseId = await until(
    async () => new URL(page.url()).searchParams.get("exercise") ?? undefined,
    "the launched exercise selected",
  );
  const exercise = () => duty.get<Exercise>(`/api/exercises/${exerciseId}`);
  expect((await exercise()).status).toBe("RUNNING");
  const again = await duty.post("/api/exercises", { template: TEMPLATE, kind: "TABLETOP" });
  expect(again.status()).toBe(409);
  expect((await duty.post(`/api/scenarios/${TEMPLATE}/reset`)).status()).toBe(409);
  expect((await duty.get<Exercise[]>("/api/exercises/running")).map((e) => e.id)).toEqual([exerciseId]);

  // --- 2. Scene 1: the signals open the exercise's incident, labelled (EXR-03) -----------------
  const next = controls.getByRole("button", { name: "Next inject" });
  await next.click();
  const nairobi = await until(async () => {
    const found = (await duty.get<Incident[]>("/api/incidents")).find((i) => i.reference === INCIDENT);
    return found && found.confidence === 92 ? found : undefined;
  }, "three signals fused (confidence 92)", 180);
  expect(nairobi.exercise).toBe(true);
  await page.goto(`/incidents?id=${nairobi.id}`);
  await expect(
    page.getByRole("table", { name: "Incident register" }).getByLabel("Exercise").first(),
  ).toBeVisible();

  // --- 3. Scene 2: impact; PB-07 proposed for the exercise incident, labelled ------------------
  await page.goto(`/exercises?exercise=${exerciseId}`);
  await next.click();
  const pb07 = await until(
    async () =>
      (await proposals()).find((p) => p.action_type === "START_PLAYBOOK" && p.incident_id === nairobi.id),
    "PB-07 proposed",
  );
  expect(pb07.exercise).toBe(true);
  // Left out of leadership figures (§93 Q4).
  const during = await executive();
  expect([during.active_incidents, during.posture.level, during.accounted.pct]).toEqual([
    calm.active_incidents,
    calm.posture.level,
    calm.accounted.pct,
  ]);

  // --- 4. Scene 3: the Duty Officer approves PB-07; step 7 by the Nairobi HoM; the advisory -----
  await next.click();
  await page.goto("/");
  await expect(card(page, pb07.id).getByLabel("Exercise")).toBeVisible();
  await card(page, pb07.id).getByRole("button", { name: "Approve as Duty Officer or Security Officer" }).click();
  const run = await until(async () => {
    const runs = await duty.get<Run[]>(`/api/playbook-runs?incident_id=${nairobi.id}`);
    return runs[0]?.status === "AWAITING_APPROVAL" ? runs[0] : undefined;
  }, "PB-07 at step 7");
  const step7 = run.steps[6]?.id ?? "";
  expect((await hom.post(`/api/playbook-runs/${run.id}/steps/${step7}/approve`)).ok()).toBe(true);
  const finished = await until(async () => {
    const r = await duty.get<Run>(`/api/playbook-runs/${run.id}`);
    return r.status === "COMPLETED" ? r : undefined;
  }, "PB-07 completed");
  const advisory = await until(
    async () =>
      (await proposals()).find((p) => p.action_type === "SEND_EXTERNAL_MESSAGE" && p.incident_id === nairobi.id),
    "the citizen advisory",
  );
  expect((await duty.post(`/api/proposals/${advisory.id}/approve`)).ok()).toBe(true);

  // --- 5. Scene 4: the check-in answers; Hana Takeda escalated on the exercise's 20 s (G-3: A) --
  await page.goto(`/exercises?exercise=${exerciseId}`);
  await next.click();
  const checkin = (
    await duty.get<{ id: string; campaign_type: string; exercise: boolean }[]>(
      `/api/campaigns?incident_id=${nairobi.id}`,
    )
  ).find((c) => c.campaign_type === "CHECKIN");
  expect(checkin?.exercise).toBe(true);
  const summary = await until(async () => {
    const s = await duty.get<{ personnel: Tally; citizens: Tally }>(`/api/checkin/${checkin?.id}/summary`);
    return s.personnel.safe === 15 && s.citizens.safe === 168 ? s : undefined;
  }, "all check-in answers", 120);
  expect([summary.personnel.safe, summary.personnel.need_help, summary.personnel.pending]).toEqual([15, 1, 1]);
  await until(async () => {
    const pending = await duty.get<{ full_name: string; escalated: boolean }[]>(
      `/api/checkin/${checkin?.id}/people?group=personnel&status=PENDING`,
    );
    return pending.find((p) => p.full_name === "Hana Takeda" && p.escalated);
  }, "Hana Takeda escalated");

  // --- 6. End from the screen: scored and frozen (EXR-04, EXR-05) ------------------------------
  await controls.getByRole("button", { name: "End exercise" }).click();
  const breakdown = page.getByLabel("Scoring breakdown");
  await expect(breakdown).toBeVisible({ timeout: 15_000 });
  await expect(page.getByLabel("Exercise running")).toHaveCount(0);
  const ended = await exercise();
  expect([ended.status, ended.incident_reference, ended.participants]).toEqual(["COMPLETED", INCIDENT, 16]);
  await expect(breakdown).toContainText("simulated delivery");
  await expect(breakdown.locator('[data-dimension="OVERALL"]')).toContainText(String(ended.overall_score));

  // The same record through After-Action Review (§93 Q4: an exercise's incident can be reviewed).
  expect((await duty.patch(`/api/incidents/${nairobi.id}/status`, { status: "MONITORING" })).ok()).toBe(true);
  const started = await duty.post("/api/aar", { incident_id: nairobi.id });
  expect(started.status()).toBe(201);
  const review = (await started.json()) as { metrics: Metric[]; exercise: boolean };
  expect(review.exercise).toBe(true);
  const metric = (key: string) => review.metrics.find((m) => m.key === key);
  const score = (d: string) => ended.scores.find((s) => s.dimension === d);
  const notified = metric("detection_to_notification")?.value ?? null;
  expect(notified).not.toBeNull();
  expect(Math.abs(Number(score("DETECTION")?.measured.seconds) - (notified ?? 0))).toBeLessThan(0.01);
  expect(score("DETECTION")?.measured.target_s).toBe(120);
  expect(score("DETECTION")?.score).toBe(Math.min(100, halfUp((100 * 120) / Math.max(notified ?? 1, 1))));
  expect(score("ACCOUNTABILITY")?.score).toBe(metric("personnel_accounted")?.value); // 94
  expect(score("ACCOUNTABILITY")?.measured).toMatchObject({ answered: 16, asked: 17 });
  const speed = score("DECISION_SPEED");
  expect(speed?.measured.target_s).toBe(300);
  if (metric("decision_slowest")?.met === true) expect(speed?.score).toBe(100);
  const reach = score("COMMUNICATION")?.measured ?? {};
  expect([reach.exposed, reach.simulated_delivery]).toEqual([229, true]);
  expect(score("COMMUNICATION")?.score).toBe(halfUp((100 * Number(reach.reached)) / 229));
  expect(finished.steps.every((s) => s.status === "DONE")).toBe(true);
  expect([score("PLAN_ADHERENCE")?.score, score("PLAN_ADHERENCE")?.measured]).toEqual([100, { done: 8, steps: 8 }]);
  const figures = ended.scores.map((s) => s.score).filter((s): s is number => s !== null);
  expect(figures).toHaveLength(5);
  expect(ended.overall_score).toBe(halfUp(figures.reduce((a, b) => a + b, 0) / figures.length));

  // Frozen: nothing ends it twice or changes the scores.
  expect((await duty.post(`/api/exercises/${exerciseId}/end`)).status()).toBe(409);
  expect((await duty.post(`/api/exercises/${exerciseId}/abandon`, { reason: "x" })).status()).toBe(409);
  const later = await exercise();
  expect([later.scores, later.overall_score]).toEqual([ended.scores, ended.overall_score]);

  // --- 7. Readiness from this exercise on People & Sites, Site Twin and the Executive (EXR-07) ---
  const today = new Date().toISOString().slice(0, 10);
  const after = await embassy();
  expect([after?.readiness_score, after?.readiness_source, after?.last_drill_on]).toEqual([
    ended.overall_score,
    "EXERCISE",
    today,
  ]);
  expect((await twin()).readiness).toMatchObject({ score: ended.overall_score, source: "EXERCISE" });
  const drilled = await executive();
  expect(drilled.readiness.illustrative).toBe(calm.readiness.illustrative - 1);
  expect(drilled.readiness.from_exercises).toBe(calm.readiness.from_exercises);
  expect(drilled.active_incidents).toBe(calm.active_incidents);

  // --- 8. The Viewer reads and cannot launch or end (EXR-08) -----------------------------------
  expect((await viewer.get<Template[]>("/api/exercises/templates")).some((t) => t.can_launch)).toBe(false);
  expect((await viewer.post("/api/exercises", { template: TEMPLATE, kind: "TABLETOP" })).status()).toBe(403);
  expect((await viewer.post(`/api/exercises/${exerciseId}/end`)).status()).toBe(403);
  const reader = await signedIn(browser, "viewer", `/exercises?exercise=${exerciseId}`);
  await expect(reader.getByRole("table", { name: "Recent exercises" })).toBeVisible();
  await expect(reader.getByLabel("Scoring breakdown")).toBeVisible();
  for (const name of ["Launch", "Next inject", "End exercise", "Abandon"]) {
    await expect(reader.getByRole("button", { name, exact: true })).toHaveCount(0);
  }
  await reader.context().close();

  // --- 9. Audited, and the chain verifies (D-20) ---------------------------------------------
  const audit = await admin.get<{ action: string }[]>(
    `/api/audit?entity_type=exercise&entity_id=${exerciseId}&limit=500`,
  );
  const own = audit.map((e) => e.action);
  expect(own.sort()).toEqual(["EXERCISE.END", "EXERCISE.START"]);
  expect(await admin.get<{ intact: boolean }>("/api/audit/verify")).toMatchObject({ intact: true });

  expect(cspViolations).toEqual([]);
});
