import { expect, test } from "@playwright/test";

import { as, cspViolations, PASSWORD, signedIn, until } from "./support";

// Document Expiry acceptance (Prompt 52; requirements-pilot.md §37, D-37) on the real stack.
// `make acceptance` runs it last. The Phase 1 spec leaves INC-<year>-1042 at MONITORING, and
// a document only "could block evacuation" while its mission has an active incident (DX-03),
// so a Duty Officer sets the incident back to ACTIVE first, as a person would when unrest
// flares again. Run alone from reset-demo, it plays NBO-CIVIL-UNREST up to scene 2 itself.
// The Compliance agent only proposes; a Consular Officer decides in the Decision Queue.

interface Doc {
  id: string;
  holder_name: string;
  mission_code: string | null;
  doc_type: string;
  days_left: number;
  urgency: string;
  could_block_evacuation: boolean;
  renewal_status: string;
  simulated: boolean;
}
interface Summary {
  tracked: number;
  expiring_30: number;
  could_block: number;
  ready_pct: number | null;
  simulated: boolean;
}
interface Incident {
  id: string;
  reference: string;
  status: string;
}
interface Proposal {
  id: string;
  agent_code: string;
  action_type: string;
  status: string;
  incident_id: string | null;
  action_payload: { document_ids?: string[] };
}
interface Campaign {
  id: string;
  reference: string;
  campaign_type: string;
  created_by_type: string;
  message: string;
  status: string;
  recipients: number;
  simulated: boolean;
  funnel: Record<string, Record<string, number>>;
}

const year = new Date().getUTCFullYear();
const REMINDER = "Your travel document expires soon. Please start the renewal with the consular section.";

test("Document Expiry acceptance: register, Compliance proposal approved, scopes, audit", async ({
  browser,
  request,
}) => {
  test.skip(!PASSWORD, "DEMO_USER_PASSWORD is not set (run through `make acceptance`)");
  test.setTimeout(300_000);
  const duty = await as(request, "duty.officer");
  const consular = await as(request, "consular.officer");
  const viewer = await as(request, "viewer");
  const cairo = await as(request, "hom.cairo");
  const admin = await as(request, "admin");
  const documents = () => duty.get<Doc[]>("/api/documents?limit=1000");

  // --- 0. NBO-CIVIL-UNREST active ------------------------------------------------------------
  const nairobi = async () =>
    (await duty.get<Incident[]>("/api/incidents")).find((i) => i.reference === `INC-${year}-1042`);
  if (!(await nairobi())) {
    for (let scene = 0; scene < 2; scene += 1) await duty.post("/api/scenarios/NBO-CIVIL-UNREST/next");
  }
  const incident = await until(nairobi, "INC-1042", 90);
  if (incident.status !== "ACTIVE") {
    const set = await duty.patch(`/api/incidents/${incident.id}/status`, { status: "ACTIVE" });
    expect(set.ok()).toBeTruthy();
  }

  // --- 1. The register and KPIs, labelled simulated (DX-01..03, DX-08) -----------------------
  const all = await documents();
  expect(all.length).toBeGreaterThan(0);
  expect(all.every((d) => d.simulated)).toBe(true);
  const hana = all.find((d) => d.holder_name === "Hana Takeda" && d.doc_type === "DIPLOMATIC_PASSPORT");
  expect([hana?.days_left, hana?.urgency]).toEqual([21, "CRITICAL"]);
  const flagged = await until(async () => {
    const rows = (await documents()).filter((d) => d.mission_code === "NBO" && d.could_block_evacuation);
    return rows.length === 2 ? rows : undefined;
  }, "the two Nairobi documents flagged");
  expect(flagged.map((d) => [d.holder_name, d.doc_type]).sort()).toEqual([
    ["Aiko Takeda", "PASSPORT"],
    ["Hana Takeda", "DIPLOMATIC_PASSPORT"],
  ]);
  const summary = await viewer.get<Summary>("/api/documents/summary");
  expect(summary.simulated).toBe(true);
  expect(summary.tracked).toBeGreaterThanOrEqual(all.length); // the list stops at 1,000 (LIST_MAX)
  expect(summary.could_block).toBe(2);

  const page = await signedIn(browser, "consular.officer", "/documents");
  await expect(page.getByText("Sorted by urgency", { exact: false })).toContainText("simulated");
  await expect(page.getByText(`${summary.ready_pct}%`)).toBeVisible();
  for (const d of flagged) {
    const row = page.locator(`tr[data-document="${d.id}"]`);
    await expect(row).toContainText(d.holder_name);
    await expect(row).toContainText("Could block evacuation");
  }
  await expect(page.locator(`tr[data-document="${hana?.id}"]`)).toContainText("CRITICAL");

  // --- 2. The Compliance agent proposes; a Consular Officer approves (DX-07) ----------------
  const proposal = await until(async () => {
    const found = (await duty.get<Proposal[]>("/api/proposals?limit=200")).find(
      (p) => p.agent_code === "COMPLIANCE" && p.incident_id === incident.id && p.status === "PENDING",
    );
    return found;
  }, "the Compliance proposal");
  expect(proposal.action_type).toBe("START_DOCUMENT_RENEWAL");
  expect([...(proposal.action_payload.document_ids ?? [])].sort()).toEqual(flagged.map((d) => d.id).sort());
  expect((await viewer.post(`/api/proposals/${proposal.id}/approve`)).status()).toBe(403);

  await page.goto("/");
  const card = page.locator(`[data-proposal-id="${proposal.id}"]`);
  await expect(card).toContainText("travel documents could block an evacuation");
  await card.getByRole("button", { name: /^Approve as .*Consular Officer/ }).click();
  await until(async () => {
    const all = await consular.get<Proposal[]>("/api/proposals?limit=200");
    return all.find((p) => p.id === proposal.id)?.status === "APPROVED" ? true : undefined;
  }, "the proposal approved and executed");

  // --- 3. Two renewals in progress, live; the reminders delivered (DX-04, DX-05) ------------
  // The executor takes the step REQUESTED, which plan-pilot-dx §3-4 counts as "in progress";
  // the consular section then starts the work (IN_PROGRESS) as a person.
  await page.goto("/documents");
  for (const d of flagged) {
    await expect(page.locator(`tr[data-document="${d.id}"]`)).toContainText("Renewal requested by you");
  }
  const requested = (await documents()).filter((d) => flagged.some((f) => f.id === d.id));
  expect(requested.map((d) => d.renewal_status)).toEqual(["REQUESTED", "REQUESTED"]);
  const reminders = await until(async () => {
    const campaigns = await duty.get<Campaign[]>("/api/campaigns");
    return campaigns.find(
      (c) =>
        c.created_by_type === "AGENT" &&
        c.message === REMINDER &&
        c.status === "SENT" &&
        Object.values(c.funnel).every((f) => (f.DELIVERED ?? 0) + (f.READ ?? 0) === c.recipients) &&
        Object.keys(c.funnel).length > 0,
    );
  }, "the reminders delivered (simulated)");
  expect([reminders.campaign_type, reminders.recipients, reminders.simulated]).toEqual(["ADVISORY", 2, true]);
  expect(Object.keys(reminders.funnel).sort()).toEqual(["APP", "EMAIL"]);
  await page.context().close();

  // --- 4. A Viewer: KPIs, no names; another mission's Head of Mission: none of Nairobi (DX-09)
  expect((await viewer.post("/api/documents/reminders", { document_ids: [hana?.id] })).status()).toBe(403);
  const viewerPage = await signedIn(browser, "viewer", "/documents");
  await expect(viewerPage.getByText("Totals only")).toBeVisible();
  await expect(viewerPage.getByText(`${summary.ready_pct}%`)).toBeVisible();
  await expect(viewerPage.getByRole("table")).toHaveCount(0);
  await expect(viewerPage.getByText("Hana Takeda")).toHaveCount(0);
  await viewerPage.context().close();

  const cairoRows = await cairo.get<Doc[]>("/api/documents?limit=1000");
  expect(cairoRows.length).toBeGreaterThan(0);
  expect(cairoRows.filter((d) => d.mission_code !== "CAI")).toEqual([]);
  const cairoPage = await signedIn(browser, "hom.cairo", "/documents");
  await expect(cairoPage.getByRole("heading", { name: "Expiring documents" })).toBeVisible();
  await expect(cairoPage.getByText("Totals only")).toHaveCount(0);
  await expect(cairoPage.getByText("Hana Takeda")).toHaveCount(0);
  await expect(cairoPage.getByText("Aiko Takeda")).toHaveCount(0);
  await cairoPage.context().close();

  // --- 5. Audited, and the chain verifies (D-20) --------------------------------------------
  const audit = await admin.get<{ action: string }[]>("/api/audit?limit=500");
  const actions = audit.map((e) => e.action);
  expect(actions.filter((a) => a === "DOCUMENT.RENEWAL_REQUESTED").length).toBeGreaterThanOrEqual(2);
  expect(actions).toContain("DOCUMENT.REMINDERS");
  expect(actions).toContain("PROPOSAL.EXECUTE");
  expect(await admin.get<{ intact: boolean }>("/api/audit/verify")).toMatchObject({ intact: true });

  expect(cspViolations).toEqual([]);
});
