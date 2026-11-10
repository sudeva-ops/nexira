import { expect, test } from "@playwright/test";

import {
  API,
  as,
  cspViolations,
  KEYCLOAK,
  PASSWORD,
  signedIn,
} from "./support";

// AI Risk Copilot acceptance (Prompt 121; requirements-pilot.md §97, D-50; plan-pilot-cop §7) on
// the real stack. `make acceptance` runs it on its own after the pilot specs and before the
// After-Action Review spec: it reads INC-<year>-1042 as the Phase 1 run and the pilot specs left
// it, and changes nothing but audit rows. The Duty Officer asks in the browser; the Viewer asks
// through the API. Every figure is checked against the Incidents and Safety Check-in APIs.

interface Source {
  kind: string;
  reference: string;
  href: string;
}
interface Sentence {
  text: string;
  sources: Source[];
}
interface Answer {
  kind: string;
  sentences: Sentence[];
  sources: Source[];
  incident_id: string | null;
  label: string;
}
interface Report {
  reference: string;
  sections: { heading: string; sentences: Sentence[]; note: string | null }[];
  sources: Source[];
}
interface Tally {
  recipients: number;
  safe: number;
  need_help: number;
  pending: number;
}

const year = new Date().getUTCFullYear();
const INCIDENT = `INC-${year}-1042`;
const LABEL = "Simulated copilot · rule-based wording · simulated data";
const HEADINGS = [
  "Summary",
  "Our people",
  "Actions taken",
  "Related risks",
  "Recommendations",
];

test("AI Risk Copilot acceptance: situation, names by role, unknown, report, audit, no external call", async ({
  browser,
  request,
}) => {
  test.skip(
    !PASSWORD,
    "DEMO_USER_PASSWORD is not set (run through `make acceptance`)",
  );
  test.setTimeout(180_000);
  const duty = await as(request, "duty.officer");
  const viewer = await as(request, "viewer");
  const admin = await as(request, "admin");
  const incident = (
    await duty.get<{ id: string; reference: string }[]>("/api/incidents")
  ).find((i) => i.reference === INCIDENT);
  expect(incident, "run after the Phase 1 acceptance").toBeDefined();
  if (!incident) return;
  const detail = await duty.get<{ exposure_summary: { people: number } }>(
    `/api/incidents/${incident.id}`,
  );
  const checkin = (
    await duty.get<{ id: string; reference: string; campaign_type: string }[]>(
      `/api/campaigns?incident_id=${incident.id}`,
    )
  ).find((c) => c.campaign_type === "CHECKIN");
  const tally = (
    await duty.get<{ personnel: Tally }>(`/api/checkin/${checkin?.id}/summary`)
  ).personnel;
  const named = async (status: string) =>
    (
      await duty.get<{ full_name: string }[]>(
        `/api/checkin/${checkin?.id}/people?group=personnel&status=${status}`,
      )
    ).map((p) => p.full_name);
  const pending = await named("PENDING");
  const needHelp = await named("NEED_HELP");
  expect(pending.length + needHelp.length, "someone to name").toBeGreaterThan(
    0,
  );
  const asksBefore = (
    await admin.get<{ action: string }[]>("/api/audit?limit=500")
  ).filter((e) => e.action === "COPILOT.ASK").length;

  // Every request the browser makes stays on the stack: no external AI service (COP-05).
  const page = await signedIn(browser, "duty.officer", "/copilot");
  const hosts = new Set<string>();
  page.on("request", (r) => hosts.add(new URL(r.url()).host));
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "AI Risk Copilot",
  );

  // --- 1. The situation, cited, matching the record (COP-01, COP-02) ----------------------------
  await page
    .getByRole("button", { name: "Summarise the Nairobi situation" })
    .click();
  const answers = page.getByLabel("Answer");
  const first = answers.nth(0);
  await expect(first).toContainText(LABEL);
  await expect(first).toContainText(INCIDENT);
  await expect(first).toContainText(
    `${detail.exposure_summary.people} people are in the impact zone`,
  );
  await expect(first).toContainText(
    `Check-in ${checkin?.reference}: of ${tally.recipients} personnel, ${tally.safe} safe, ` +
      `${tally.need_help} need help and ${tally.pending} not yet answered`,
  );
  await expect(
    first.getByRole("link", { name: INCIDENT }).first(),
  ).toHaveAttribute("href", `/incidents?id=${incident.id}`);

  // --- 2. Names for the Duty Officer, counts for the Viewer (COP-03; plan G-1: A) --------------
  // Named by reference: after the pilot specs the latest check-in is another incident's, which
  // is what the bare suggestion answers (and the answer says which incident it is about).
  const people = `Who has not responded to the check-in for ${INCIDENT}?`;
  await page.getByLabel("Question").fill(people);
  await page.keyboard.press("Enter");
  const second = answers.nth(1);
  await expect(second).toContainText(`About ${INCIDENT}`);
  for (const name of [...pending, ...needHelp])
    await expect(second).toContainText(name);
  const asViewer = (await (
    await viewer.post("/api/copilot/ask", {
      question: people,
    })
  ).json()) as Answer;
  const viewerText = asViewer.sentences.map((s) => s.text).join(" ");
  expect(viewerText).toContain(
    `of ${tally.recipients} personnel, ${tally.safe} safe`,
  );
  for (const name of [...pending, ...needHelp])
    expect(viewerText, name).not.toContain(name);
  expect(asViewer.sentences.every((s) => s.sources.length > 0)).toBe(true);

  // --- 3. An unknown question is declined, with no source (COP-01) -------------------------------
  const unknown = (await (
    await duty.post("/api/copilot/ask", {
      question: "What will the exchange rate be tomorrow?",
    })
  ).json()) as Answer;
  expect([unknown.kind, unknown.sources.length, unknown.label]).toEqual([
    "UNKNOWN",
    0,
    LABEL,
  ]);
  expect(unknown.sentences[0]?.text).toMatch(/^I can't answer that yet\./);

  // --- 4. The situation report, every sentence cited, exported once (COP-04) ---------------------
  await page
    .getByLabel("Question")
    .fill("Draft a situation report for Nairobi");
  await page.keyboard.press("Enter");
  const drafted = page.getByLabel("Situation report");
  await expect(drafted).toContainText(`Situation report · ${INCIDENT}`);
  for (const heading of HEADINGS) await expect(drafted).toContainText(heading);
  await expect(drafted).toContainText(
    "Rule-based recommendations from the record",
  );
  await expect(page.getByRole("button", { name: /^send/i })).toHaveCount(0);
  const report = (await (
    await duty.post("/api/copilot/report", { incident_id: incident.id })
  ).json()) as Report;
  expect(report.sections.map((s) => s.heading)).toEqual(HEADINGS);
  for (const s of report.sections) {
    for (const sentence of s.sentences)
      expect(sentence.sources.length, sentence.text).toBeGreaterThan(0);
  }
  const exportsBefore = (
    await admin.get<{ action: string }[]>("/api/audit?limit=500")
  ).filter((e) => e.action === "COPILOT.REPORT_EXPORT").length;
  await drafted.getByRole("link", { name: "Export as PDF" }).click();
  const printed = page.getByTestId("copilot-print");
  await expect(printed.getByRole("heading", { level: 1 })).toContainText(
    `Situation report · ${INCIDENT}`,
  );
  await expect(page.getByRole("navigation")).toHaveCount(0);
  const exportsAfter = (
    await admin.get<{ action: string }[]>("/api/audit?limit=500")
  ).filter((e) => e.action === "COPILOT.REPORT_EXPORT").length;
  expect(exportsAfter).toBe(exportsBefore + 1);
  await page.context().close();

  // --- 5. Audited without the question's text; the chain verifies (COP-06, D-20) -------------------
  const audit = await admin.get<
    { action: string; actor_type: string; details: Record<string, unknown> }[]
  >("/api/audit?limit=500");
  const asks = audit.filter((e) => e.action === "COPILOT.ASK");
  expect(asks.length - asksBefore).toBe(5); // three in the browser, the Viewer's and the unknown
  for (const e of asks) {
    expect(e.actor_type).toBe("USER");
    expect(Object.keys(e.details).sort()).toEqual(["kind", "references"]);
    const details = JSON.stringify(e.details);
    expect(details).not.toMatch(/responded|Summarise|exchange rate/);
    for (const name of [...pending, ...needHelp])
      expect(details, name).not.toContain(name);
  }
  expect(asks.map((e) => e.details.kind)).toEqual(
    expect.arrayContaining(["SITUATION", "PEOPLE", "REPORT", "UNKNOWN"]),
  );
  expect(
    await admin.get<{ intact: boolean }>("/api/audit/verify"),
  ).toMatchObject({ intact: true });

  const stack = new Set([new URL(API).host, new URL(KEYCLOAK).host]);
  const outside = [...hosts].filter(
    (h) => !stack.has(h) && !/^(localhost|127\.0\.0\.1)(:\d+)?$/.test(h),
  );
  expect(outside, "requests outside the stack").toEqual([]);
  expect(cspViolations).toEqual([]);
});
