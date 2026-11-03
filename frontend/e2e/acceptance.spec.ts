import fs from "node:fs";

import { expect, type Page, test } from "@playwright/test";

import { as, cspViolations, fixture, PASSWORD, signedIn, until } from "./support";

// Phase 1 acceptance (decisions.md §7, Prompt 15): scenes 0-6 of NBO-CIVIL-UNREST
// on the real stack, from `make reset-demo` (run it with `make acceptance`). The
// Duty Officer drives the scenario with the presenter bar; every decision is made
// in the browser by a logged-in user with the right role. The performance numbers
// (requirements §5) are written to test-results/performance.json.

interface Incident {
  id: string;
  reference: string;
  category: string;
  status: string;
  severity: string;
  signal_severity: string;
  confidence: number;
  mission_id: string | null;
}
interface Proposal {
  id: string;
  agent_code: string;
  action_type: string;
  status: string;
  incident_id: string | null;
  effective_level: number;
  action_payload: Record<string, unknown>;
}
interface Run {
  id: string;
  status: string;
  steps: { seq: number; id: string; status: string; result: Record<string, unknown> }[];
}
interface FleetAsset {
  code: string;
  status: string;
  simulated: boolean;
  tags: { code: string; reference: string | null }[];
}
interface MissionFleet {
  vehicles: number;
  available: number;
  capacity: { seats_available: number; seats_needed: number };
}
interface Executive {
  posture: { level: string; critical_missions: number; elevated_missions: number };
  active_incidents: number;
  detection: { current_s: number | null; current_reference: string | null };
  accounted: { pct: number | null };
  regions: { region: string; exposure: number }[];
  attention: { mission_code: string; drivers: { kind: string; reference: string | null }[] }[];
}

interface Tally {
  safe: number;
  need_help: number;
  pending: number;
}

const year = new Date().getUTCFullYear();
const card = (page: Page, id: string) => page.locator(`[data-proposal-id="${id}"]`);

test("Phase 1 acceptance: NBO-CIVIL-UNREST scenes 0-6", async ({ browser, request }) => {
  test.skip(!PASSWORD, "DEMO_USER_PASSWORD is not set (run through `make acceptance`)");
  test.setTimeout(300_000);
  const duty = await as(request, "duty.officer");
  const admin = await as(request, "admin");
  const proposals = () => duty.get<Proposal[]>("/api/proposals?limit=200");
  const perf: Record<string, number | null> = {};

  // --- Scene 0 · Calm: the seeded state ------------------------------------------------
  const dutyPage = await signedIn(browser, "duty.officer");
  expect(await duty.get<Incident[]>("/api/incidents?status=ACTIVE")).toEqual([]);
  expect(await proposals()).toEqual([]);
  await expect(dutyPage.getByText("No decisions waiting")).toBeVisible();
  const missions = await duty.get<{ code: string; display_risk: string; id: string }[]>("/api/missions");
  const nbo = missions.find((m) => m.code === "NBO");
  expect(nbo?.display_risk).toBe("LOW");
  const presenter = dutyPage.getByRole("toolbar", { name: "Presenter" });
  await expect(presenter).toContainText("Calm");
  // FLT-02 (Prompt 76): Nairobi's fleet before the unrest: 4 of 5 vehicles, VH-05 in the workshop.
  const fleet = () => duty.get<MissionFleet>(`/api/fleet/missions/${nbo?.id}`);
  const vehicles = async () =>
    Object.fromEntries(
      (await duty.get<FleetAsset[]>(`/api/fleet/assets?mission_id=${nbo?.id}`))
        .filter((a) => a.code.startsWith("VH-"))
        .map((a) => [a.code, a]),
    );
  const tags = async () =>
    Object.fromEntries(Object.entries(await vehicles()).map(([c, a]) => [c, a.tags.map((t) => t.code)]));
  expect([(await fleet()).available, (await fleet()).vehicles]).toEqual([4, 5]);
  expect((await vehicles())["VH-05"]?.status).toBe("MAINTENANCE");
  expect(Object.values(await vehicles()).every((a) => a.simulated)).toBe(true);
  // TWN-01 (Prompt 88): the Nairobi embassy's twin before the unrest: 25 on site, no overlay.
  const embassy = (await duty.get<{ id: string; name: string }[]>("/api/sites/twin")).find(
    (s) => s.name === "Embassy Nairobi",
  );
  const twinOf = () =>
    duty.get<{ counts: { on_site: number }; shelter: unknown; route: { code: string; evacuation_reference: string } | null }>(
      `/api/sites/${embassy?.id}/twin`,
    );
  expect(await twinOf()).toMatchObject({ counts: { on_site: 25 }, shelter: null, route: null });
  // EXE-01, EXE-02 (Prompt 98; plan-pilot-exe G-1): the Executive Overview's calm state, which
  // only exists before this run.
  const executive = () => duty.get<Executive>("/api/executive/overview");
  const africa = (o: Executive) => o.regions.find((r) => r.region === "Africa")?.exposure;
  const calm = await executive();
  expect([calm.posture.level, calm.posture.critical_missions, calm.posture.elevated_missions]).toEqual([
    "GUARDED",
    0,
    4,
  ]);
  expect([calm.active_incidents, calm.accounted.pct, africa(calm)]).toEqual([0, null, 25]);

  // --- Scene 1 · Signals fused ---------------------------------------------------------
  await presenter.getByRole("button", { name: "Next scene" }).click();
  await expect(dutyPage.getByRole("heading", { level: 1 })).toHaveText("Global Operations");
  const marker = dutyPage.locator(`[data-testid="incident-marker-INC-${year}-1042"]`);
  await expect(marker).toBeVisible({ timeout: 10_000 });
  const markerSeenAt = Date.now();
  const nairobi = await until(async () => {
    const all = await duty.get<Incident[]>("/api/incidents");
    const inc = all.find((i) => i.reference === `INC-${year}-1042`);
    return inc && inc.confidence === 92 ? inc : undefined;
  }, "three signals fused (confidence 92)", 150);
  expect([nairobi.category, nairobi.signal_severity]).toEqual(["CIVIL_UNREST", "HIGH"]);
  const paris = (await duty.get<Incident[]>("/api/incidents")).find((i) => i.reference === `INC-${year}-1043`);
  expect(paris?.category).toBe("TRANSPORT_STRIKE");
  const watch = (await proposals()).filter((p) => p.agent_code === "WATCH_OFFICER");
  expect(watch.map((p) => [p.action_type, p.status])).toContainEqual(["LOG_INFO", "AUTO_EXECUTED"]);

  const timings = JSON.parse(fixture("timings")) as {
    incident_created_at: string;
    signal_to_incident_s: number;
    incident_to_exposure_s: number | null;
  };
  perf.signal_to_incident_s = timings.signal_to_incident_s;
  perf.incident_to_exposure_s = timings.incident_to_exposure_s;
  // The marker was checked once a second at most after the incident row appeared,
  // so this is an upper bound for "UI update".
  perf.incident_to_ui_s = Math.round((markerSeenAt - Date.parse(timings.incident_created_at)) / 10) / 100;

  // --- Scene 2 · Impact ------------------------------------------------------------------
  await presenter.getByRole("button", { name: "Next scene" }).click();
  const detail = await duty.get<{
    severity: string;
    mission_code: string;
    exposure_summary: { staff: number; delegates: number; citizens: number; people: number; sites: number; trips: number };
  }>(`/api/incidents/${nairobi.id}`);
  expect(detail.exposure_summary).toMatchObject({ staff: 14, delegates: 3, citizens: 212, people: 229, sites: 3, trips: 1 });
  expect([detail.severity, detail.mission_code]).toEqual(["CRITICAL", "NBO"]);
  const scene2 = await proposals();
  expect(scene2.some((p) => p.agent_code === "EXPOSURE" && p.incident_id === nairobi.id && p.status === "AUTO_EXECUTED")).toBe(true);
  const pb07 = scene2.find((p) => p.action_type === "START_PLAYBOOK" && p.incident_id === nairobi.id);
  expect([pb07?.status, pb07?.effective_level]).toEqual(["PENDING", 2]);
  // JR-06 (Prompt 27): while the incident is ACTIVE, TRP-8812 shows as impacted. Scene 6
  // sets it to MONITORING, so the Journey acceptance cannot check this later.
  const journeys = await signedIn(browser, "travel.desk", "/journeys");
  const trp8812 = journeys.getByRole("table", { name: "Trips" }).getByRole("row", { name: /TRP-8812/ });
  await expect(trp8812).toContainText(`Impacted · INC-${year}-1042`);
  await expect(journeys.getByRole("alert")).toContainText(`TRP-8812 impacted by INC-${year}-1042`);
  await journeys.context().close();

  // --- Scene 3 · Playbook: the Duty Officer approves; step 7 needs the Nairobi HoM -------
  await presenter.getByRole("button", { name: "Next scene" }).click();
  await expect(dutyPage.getByRole("heading", { level: 1 })).toHaveText("Decision Queue");
  await card(dutyPage, pb07?.id ?? "").getByRole("button", { name: "Approve as Duty Officer or Security Officer" }).click();
  const run = await until(async () => {
    const runs = await duty.get<Run[]>(`/api/playbook-runs?incident_id=${nairobi.id}`);
    return runs[0]?.status === "AWAITING_APPROVAL" ? runs[0] : undefined;
  }, "PB-07 at step 7");
  expect(run.steps.map((s) => s.status)).toEqual([...Array(6).fill("DONE"), "AWAITING_APPROVAL", "PENDING"]);
  expect(run.steps[4]?.result.recipients).toBe(229);
  const step7 = run.steps[6]?.id ?? "";
  expect((await duty.post(`/api/playbook-runs/${run.id}/steps/${step7}/approve`)).status()).toBe(403);
  const hom = await signedIn(browser, "hom.nairobi", `/playbooks?code=PB-07&run=${run.id}`);
  await hom.getByRole("button", { name: "Approve as Head of Mission" }).click();
  const finished = await until(async () => {
    const r = await duty.get<Run>(`/api/playbook-runs/${run.id}`);
    return r.status === "COMPLETED" ? r : undefined;
  }, "PB-07 completed");
  expect(finished.steps.map((s) => s.status)).toEqual(Array(8).fill("DONE"));

  // --- Scene 3b · Advisory: Communications proposes; the Duty Officer approves ------------
  const advisory = await until(
    async () =>
      (await proposals()).find((p) => p.action_type === "SEND_EXTERNAL_MESSAGE" && p.incident_id === nairobi.id),
    "the citizen advisory",
  );
  expect(Object.keys(advisory.action_payload.translations as object).sort()).toEqual(["ar", "fr", "sw"]);
  await card(dutyPage, advisory.id).getByRole("button", { name: "Approve as Duty Officer or Consular Officer" }).click();
  await until(async () => {
    const campaigns = await duty.get<{ campaign_type: string; status: string; simulated: boolean }[]>(
      `/api/campaigns?incident_id=${nairobi.id}`,
    );
    return campaigns.find((c) => c.campaign_type === "ADVISORY" && c.status === "SENT" && c.simulated);
  }, "the advisory sent through the simulated adapter");

  // --- Scene 4 · Check-in --------------------------------------------------------------------
  await presenter.getByRole("button", { name: "Next scene" }).click();
  await expect(dutyPage.getByRole("heading", { level: 1 })).toHaveText("Safety Check-in");
  const checkin = (await duty.get<{ id: string; campaign_type: string }[]>(`/api/campaigns?incident_id=${nairobi.id}`)).find(
    (c) => c.campaign_type === "CHECKIN",
  );
  const summary = await until(async () => {
    const s = await duty.get<{ personnel: Tally; citizens: Tally }>(`/api/checkin/${checkin?.id}/summary`);
    return s.personnel.safe === 15 && s.citizens.safe === 168 ? s : undefined;
  }, "all check-in answers");
  expect([summary.personnel.safe, summary.personnel.need_help, summary.personnel.pending]).toEqual([15, 1, 1]);
  expect([summary.citizens.safe, summary.citizens.need_help, summary.citizens.pending]).toEqual([168, 4, 40]);
  await expect(dutyPage.getByLabel("Personnel figures")).toContainText("16 of 17 responded");
  const hana = await until(async () => {
    const pending = await duty.get<{ full_name: string; escalated: boolean }[]>(
      `/api/checkin/${checkin?.id}/people?group=personnel&status=PENDING`,
    );
    return pending.find((p) => p.full_name === "Hana Takeda" && p.escalated);
  }, "Hana Takeda escalated");
  expect(hana.escalated).toBe(true);
  // FLT-02, FLT-03 (Prompt 76): Peter Mwangi needs help, so VH-02 is blocked as well as on the
  // road in the zone; the garage and residence vehicles are at site (plan-pilot-flt G-1).
  expect((await tags())["VH-02"]).toEqual(["BLOCKED", "IN_ZONE"]);
  expect((await tags())["VH-01"]).toEqual([]);
  const during = await fleet();
  expect([during.available, during.capacity.seats_available, during.capacity.seats_needed]).toEqual([3, 20, 16]);
  // EV-02 (Prompt 70): after scenes 1-4, EVP-NBO is ready, not activated, labelled simulated.
  // Only here in `make acceptance` is that so; ev-acceptance.spec.ts takes it on from scene 5.
  const nboEvacuations = () => duty.get<{ status: string }[]>(`/api/evacuations?mission_id=${nbo?.id}`);
  expect(await nboEvacuations()).toEqual([]);
  await dutyPage.getByRole("link", { name: /Evacuation Management/ }).click();
  await dutyPage.getByRole("combobox", { name: "Mission" }).selectOption(nbo?.id ?? "");
  await expect(dutyPage.getByTestId("evacuation-banner")).toContainText(
    "Evacuation plan EVP-NBO is ready but not activated.",
  );
  await expect(dutyPage.getByText("Illustrative evacuation plan (simulated)")).toBeVisible();

  // EXE-01, EXE-02 (Prompt 98): after the check-in, the overview's incident figures.
  const unrest = await executive();
  expect([unrest.posture.level, unrest.accounted.pct, africa(unrest)]).toEqual(["SEVERE", 94, 38]);
  expect(unrest.detection.current_reference).toBe(nairobi.reference);
  expect(unrest.detection.current_s).not.toBeNull();
  expect(unrest.attention[0]?.mission_code).toBe("NBO");
  expect(unrest.attention[0]?.drivers.map((d) => d.kind)).toEqual(
    expect.arrayContaining(["INCIDENT", "FLEET", "SHELTER"]),
  );

  // --- Scene 5 · Decisions: the two-person rule (plan G-16 fixture) --------------------------
  await presenter.getByRole("button", { name: "Next scene" }).click();
  const evacuation = fixture("evacuation");
  await hom.goto("/");
  await card(hom, evacuation).getByRole("button", { name: "Approve as Head of Mission (1/2)" }).click();
  await expect(card(hom, evacuation).getByTestId("approver-1")).toContainText("✓ Head of Mission");
  expect((await proposals()).find((p) => p.id === evacuation)?.status).toBe("PENDING"); // not executed
  expect(await nboEvacuations()).toEqual([]); // EV-02: one approval activates nothing
  const homApi = await as(request, "hom.nairobi");
  expect((await homApi.post(`/api/proposals/${evacuation}/approve`)).status()).toBe(403); // step 2: rejected
  const hq = await signedIn(browser, "hq.director");
  await card(hq, evacuation).getByRole("button", { name: "Approve as HQ Crisis Director (2/2)" }).click();
  await until(
    async () => ((await proposals()).find((p) => p.id === evacuation)?.status === "APPROVED" ? true : undefined),
    "the evacuation executed",
  );
  expect((await nboEvacuations()).map((e) => e.status)).toEqual(["ACTIVE"]); // EV-02: the second activates
  // FLT-02 (Prompt 76): the available vehicles are assigned to the evacuation.
  const assigned = Object.entries(await tags()).filter(([, t]) => t.includes("ASSIGNED")).map(([c]) => c);
  expect(assigned).toEqual(["VH-01", "VH-03", "VH-04"]);
  // TWN-04 (Prompt 88; plan-pilot-twn G-3): while EVN-1001 is ACTIVE the embassy shows Route B,
  // and PB-07's shelter alert (step 4) has gone out for the ACTIVE incident.
  const evacuating = await twinOf();
  expect(evacuating.route).toMatchObject({ code: "B", evacuation_reference: "EVN-1001" });
  expect(evacuating.shelter).not.toBeNull();

  // --- Scene 6 · Review: a user sets MONITORING; the audit chain verifies ---------------------
  await presenter.getByRole("button", { name: "Next scene" }).click();
  await dutyPage.goto(`/incidents?id=${nairobi.id}`);
  await dutyPage.getByLabel("Incident status").selectOption("MONITORING");
  await dutyPage.getByRole("button", { name: "Set status" }).click();
  await until(async () => {
    const all = await duty.get<Incident[]>("/api/incidents");
    return all.find((i) => i.id === nairobi.id)?.status === "MONITORING" ? true : undefined;
  }, "MONITORING");
  const timeline = await duty.get<{ timeline: { event_type: string; actor_type: string }[] }>(`/api/incidents/${nairobi.id}`);
  const kinds = new Set(timeline.timeline.map((e) => e.event_type));
  for (const kind of ["SIGNAL", "FUSED", "EXPOSURE", "ESCALATED", "PLAYBOOK_STEP", "DECISION", "CHECKIN", "ESCALATION", "NOTE", "STATUS"]) {
    expect(kinds, kind).toContain(kind);
  }
  const audit = await admin.get<{ action: string; actor_type: string }[]>("/api/audit?limit=500");
  const decisions = audit.filter((e) =>
    ["PROPOSAL.APPROVE", "PROPOSAL.EDIT_APPROVE", "PROPOSAL.REJECT", "PLAYBOOK.STEP_APPROVE", "INCIDENT.STATUS_CHANGE"].includes(e.action),
  );
  expect(decisions.length).toBeGreaterThanOrEqual(6);
  expect(new Set(decisions.map((e) => e.actor_type))).toEqual(new Set(["USER"]));
  const verify = await admin.get<{ intact: boolean; first_broken_seq: number | null }>("/api/audit/verify");
  expect(verify).toMatchObject({ intact: true, first_broken_seq: null });
  expect(cspViolations).toEqual([]); // the security headers break nothing (Prompt 16)

  fs.mkdirSync("test-results", { recursive: true });
  fs.writeFileSync("test-results/performance.json", JSON.stringify(perf, null, 2));
  console.log("performance", JSON.stringify(perf));
  expect(perf.signal_to_incident_s).toBeLessThanOrEqual(5);
  expect(perf.incident_to_exposure_s).toBeLessThanOrEqual(5);
  expect(perf.incident_to_ui_s).toBeLessThanOrEqual(2);
});
