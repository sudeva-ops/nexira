import { expect, type Page, test } from "@playwright/test";

import { as, cspViolations, PASSWORD, signedIn } from "./support";

// After-Action Review acceptance (Prompt 111; requirements-pilot.md §87 as amended by
// plan-pilot-aar G-2; D-47) on the real stack. Later pilot specs set INC-<year>-1042 back to
// ACTIVE, so `make acceptance` runs this one last, on its own (plan-pilot-aar G-4). Here: a
// review is refused while the incident is ACTIVE; the Duty Officer sets it to MONITORING and
// starts AAR-<year>-1042 from Incidents; the timeline, metrics and drafts come from the record
// with no name; people decide; finalising waits for the last draft and freezes the metrics; the
// export is audited; the Viewer reads only; the chain verifies.

interface Metric {
  key: string;
  value: number | null;
  met: boolean | null;
}
interface Item {
  id: string;
  rule_code: string | null;
  status: string;
  owner_team: string;
}
interface Review {
  id: string;
  reference: string;
  status: string;
  metrics: Metric[];
  timeline: { source: string; text: string }[];
  items: Item[];
  can_act: boolean;
  can_finalise: boolean;
}

const year = new Date().getUTCFullYear();
const INCIDENT = `INC-${year}-1042`;
const REVIEW = `AAR-${year}-1042`;
// Seeded people and demo users (simulated); none may appear in a review or its export.
const NAMES = [
  "Peter Mwangi",
  "Hana Takeda",
  "Grace Wanjiru",
  "Omar Siddiqui",
  "Elena Costa",
  "Layla Haddad",
  "Daniel Mercer",
];
const DUE = new Date(Date.now() + 30 * 86_400_000).toISOString().slice(0, 10);

const row = (page: Page, rule: string) =>
  page
    .getByRole("table", { name: "Lessons and actions" })
    .locator(`tr[data-item="${rule}"]`);

test("After-Action Review acceptance: refused while ACTIVE, the record, decisions, final, export", async ({
  browser,
  request,
}) => {
  test.skip(
    !PASSWORD,
    "DEMO_USER_PASSWORD is not set (run through `make acceptance`)",
  );
  test.setTimeout(240_000);
  const duty = await as(request, "duty.officer");
  const security = await as(request, "security.officer");
  const viewer = await as(request, "viewer");
  const admin = await as(request, "admin");
  const incident = (
    await duty.get<{ id: string; reference: string; status: string }[]>(
      "/api/incidents",
    )
  ).find((i) => i.reference === INCIDENT);
  expect(incident?.status, "run after every other acceptance spec").toBe(
    "ACTIVE",
  );
  if (!incident) return;

  // --- 0. Refused while ACTIVE (§88 Q2); Executive's timing for the same incident -----------
  const refused = await duty.post("/api/aar", { incident_id: incident.id });
  expect(refused.status()).toBe(409);
  const executive = await duty.get<{
    detection: { current_s: number | null; current_reference: string | null };
  }>("/api/executive/overview");

  // --- 1. The Duty Officer sets MONITORING and starts the review from Incidents (AAR-01, AAR-08)
  const page = await signedIn(
    browser,
    "duty.officer",
    `/incidents?id=${incident.id}`,
  );
  await page.getByLabel("Incident status").selectOption("MONITORING");
  await page.getByRole("button", { name: "Set status" }).click();
  await page.getByRole("button", { name: "Start after-action review" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "After-Action Review",
  );
  await expect(page.getByRole("note")).toContainText(
    `After-action review ${REVIEW} · ${INCIDENT}`,
  );
  const reviewId = new URL(page.url()).searchParams.get("review") ?? "";
  const review = () => duty.get<Review>(`/api/aar/${reviewId}`);
  const started = await review();
  expect([started.reference, started.status]).toEqual([REVIEW, "DRAFT"]);

  // --- 2. The record: timeline, metrics, drafts; no name (AAR-02..04, plan G-1, G-2) ---------
  const texts = started.timeline.map((t) => t.text);
  for (const expected of [
    /^Fused /,
    /^Exposure: /,
    /^Step 5 · Send safety check-in/,
    /^Step 7 · Approve evacuation route B: approved by the Head of Mission\.$/,
    /^Check-in NTF-\d+: a staff member did not answer and was escalated\.$/,
    /: approved by the Duty Officer\.$/,
    /^Status ACTIVE → MONITORING\.$/,
  ]) {
    expect(
      texts.some((t) => expected.test(t)),
      String(expected),
    ).toBe(true);
  }
  const metric = (key: string) => started.metrics.find((m) => m.key === key);
  expect(metric("detection_to_incident")?.met).toBe(true); // ≤ 5 s (requirements §5)
  expect(metric("incident_to_exposure")?.met).toBe(true);
  expect(metric("personnel_accounted")?.value).toBe(94); // 15 + 1 of 17 (decisions.md §7)
  if (
    executive.detection.current_reference === INCIDENT &&
    executive.detection.current_s !== null
  ) {
    expect(
      Math.abs(
        (metric("detection_to_notification")?.value ?? -99) -
          executive.detection.current_s,
      ),
    ).toBeLessThan(1);
  }
  const codes = started.items.map((i) => i.rule_code);
  for (const code of [
    "CHECKIN_SILENT",
    "LOW_CONFIDENCE",
    "FLEET_ZONE",
    "SITE_FAULT",
    "SUPPLY_IMPACT",
    "DOCS_EXPIRING",
  ]) {
    expect(codes, code).toContain(code);
  }
  expect(codes).not.toContain("GATE_WAIT"); // step 7 was approved within seconds (G-2)
  expect(new Set(started.items.map((i) => i.status))).toEqual(
    new Set(["DRAFT"]),
  );
  const body = JSON.stringify(started);
  for (const name of NAMES) expect(body, name).not.toContain(name);
  const main = (await page.locator(".nx-aar-main").textContent()) ?? "";
  for (const name of NAMES) expect(main, name).not.toContain(name);

  // --- 3. People decide (AAR-05): two accepted, one rejected, one added ---------------------
  await row(page, "CHECKIN_SILENT")
    .getByRole("button", { name: "Accept" })
    .click();
  const accept = page.getByLabel("Accept CHECKIN_SILENT");
  await accept.getByLabel("Owner team").selectOption("HR");
  await accept.getByLabel("Due date").fill(DUE);
  await accept.getByRole("button", { name: "Confirm" }).click();
  await expect(row(page, "CHECKIN_SILENT")).toHaveAttribute(
    "data-status",
    "ACCEPTED",
  );
  await row(page, "LOW_CONFIDENCE")
    .getByRole("button", { name: "Accept" })
    .click();
  await page
    .getByLabel("Accept LOW_CONFIDENCE")
    .getByRole("button", { name: "Confirm" })
    .click();
  await expect(row(page, "LOW_CONFIDENCE")).toHaveAttribute(
    "data-status",
    "ACCEPTED",
  );
  await row(page, "FLEET_ZONE").getByRole("button", { name: "Reject" }).click();
  await page
    .getByLabel("Reject reason")
    .getByRole("button", { name: "Handled offline" })
    .click();
  await expect(row(page, "FLEET_ZONE")).toHaveAttribute(
    "data-status",
    "REJECTED",
  );
  await page.getByRole("button", { name: "Add lesson" }).click();
  const add = page.getByLabel("Add a lesson");
  await add
    .getByLabel("Finding")
    .fill("The consular hotline was busy before the portal opened.");
  await add
    .getByLabel("New action")
    .fill("Open the crisis portal at CRITICAL severity.");
  await add.getByLabel("Team").selectOption("CONSULAR");
  await add.getByRole("button", { name: "Add" }).click();
  await expect(row(page, "OWN")).toHaveAttribute("data-status", "ACCEPTED");
  const decided = await review();
  expect(
    decided.items.find((i) => i.rule_code === "CHECKIN_SILENT")?.owner_team,
  ).toBe("HR");

  // --- 4. Finalise waits for the last draft, then freezes (AAR-06) ---------------------------
  expect(decided.can_finalise).toBe(false); // the Duty Officer does not finalise
  expect((await duty.post(`/api/aar/${reviewId}/finalise`)).status()).toBe(403);
  const pending = await security.post(`/api/aar/${reviewId}/finalise`);
  expect(pending.status()).toBe(409);
  for (const item of decided.items.filter((i) => i.status === "DRAFT")) {
    expect(
      (
        await duty.post(`/api/aar/items/${item.id}/reject`, {
          reason: "Not needed",
        })
      ).ok(),
    ).toBe(true);
  }
  const before = (await review()).metrics;
  const officer = await signedIn(
    browser,
    "security.officer",
    `/aar?review=${reviewId}`,
  );
  await officer.getByRole("button", { name: "Finalise" }).click();
  await expect(officer.getByRole("note")).toContainText(
    "the metrics are frozen",
  );
  await officer.context().close();
  const final = await review();
  expect(final.status).toBe("FINAL");
  expect(final.metrics.map((m) => [m.key, m.value])).toEqual(
    before.map((m) => [m.key, m.value]),
  );
  const accepted = final.items.find((i) => i.rule_code === "CHECKIN_SILENT");
  expect((await duty.post(`/api/aar/items/${accepted?.id}/done`)).ok()).toBe(
    true,
  );
  const fleet = final.items.find((i) => i.rule_code === "FLEET_ZONE");
  expect(
    (
      await duty.post(`/api/aar/items/${fleet?.id}/accept`, {
        owner_team: "FLEET",
        due_on: DUE,
      })
    ).status(),
  ).toBe(409);
  const late = await duty.post(`/api/aar/${reviewId}/items`, {
    finding: "F",
    action: "A",
    owner_team: "IT",
    priority: "LOW",
    due_on: DUE,
  });
  expect(late.status()).toBe(409);

  // --- 5. The Viewer reads and exports; nothing else (AAR-07, AAR-08) ------------------------
  const asViewer = await viewer.get<Review>(`/api/aar/${reviewId}`);
  expect([asViewer.can_act, asViewer.can_finalise]).toEqual([false, false]);
  expect(
    (await viewer.post(`/api/aar/items/${accepted?.id}/done`)).status(),
  ).toBe(403);
  const exportsBefore = (
    await admin.get<{ action: string }[]>(
      "/api/audit?entity_type=after_action_review&limit=500",
    )
  ).filter((e) => e.action === "AAR.EXPORT").length;
  const reader = await signedIn(browser, "viewer", `/aar?review=${reviewId}`);
  await expect(
    reader.getByRole("table", { name: "Lessons and actions" }),
  ).toBeVisible();
  for (const name of ["Accept", "Reject", "Add lesson", "Finalise", "Done"]) {
    await expect(reader.getByRole("button", { name, exact: true })).toHaveCount(
      0,
    );
  }
  await reader.getByRole("button", { name: "Export review" }).click();
  const printed = reader.getByTestId("aar-print");
  await expect(printed.getByRole("heading", { level: 1 })).toHaveText(
    `After-action review ${REVIEW}`,
  );
  await expect(printed).toContainText("Simulated data");
  await expect(reader.getByRole("navigation")).toHaveCount(0);
  const text = (await printed.textContent()) ?? "";
  for (const name of NAMES) expect(text, name).not.toContain(name);
  await reader.context().close();

  // --- 6. Audited, and the chain verifies (D-20) ---------------------------------------------
  const audit = await admin.get<{ action: string }[]>("/api/audit?limit=500");
  const actions = audit.map((e) => e.action);
  for (const action of [
    "AAR.START",
    "AAR.ITEM_ACCEPT",
    "AAR.ITEM_REJECT",
    "AAR.ITEM_ADD",
    "AAR.FINALISE",
    "AAR.ITEM_DONE",
  ]) {
    expect(actions, action).toContain(action);
  }
  const exportsAfter = (
    await admin.get<{ action: string }[]>(
      "/api/audit?entity_type=after_action_review&limit=500",
    )
  ).filter((e) => e.action === "AAR.EXPORT").length;
  expect(exportsAfter).toBe(exportsBefore + 1);
  expect(
    await admin.get<{ intact: boolean }>("/api/audit/verify"),
  ).toMatchObject({ intact: true });

  expect(cspViolations).toEqual([]);
});
