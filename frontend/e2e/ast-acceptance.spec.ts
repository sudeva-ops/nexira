import { expect, test } from "@playwright/test";

import { as, cspViolations, PASSWORD, signedIn, until } from "./support";

// Assistance Partners acceptance (Prompt 47; requirements-pilot.md §32, D-36) on the real
// stack. `make acceptance` runs it after the Phase 1 spec has played NBO-CIVIL-UNREST: PB-07
// has run (step 6 asked Kestrel to stand by) and Peter Mwangi answered HELP to the Nairobi
// check-in. Partners are simulated; every request here is made by a logged-in person.

interface Partner {
  code: string;
  simulated: boolean;
}
interface Coverage {
  code: string;
  missing: string[];
}
interface Incident {
  id: string;
  reference: string;
}
interface Campaign {
  id: string;
  campaign_type: string;
  incident_id: string | null;
}
interface PartnerRequest {
  id: string;
  reference: string;
  partner_name: string;
  service: string;
  incident_id: string | null;
  person_name: string | null;
  status: string;
  eta: string | null;
  created_by_type: string;
}

const year = new Date().getUTCFullYear();

test("Assistance Partners acceptance: directory, PB-07 standby, an SOS to completion", async ({ browser, request }) => {
  test.skip(!PASSWORD, "DEMO_USER_PASSWORD is not set (run through `make acceptance`)");
  test.setTimeout(300_000);
  const duty = await as(request, "duty.officer");
  const viewer = await as(request, "viewer");
  const admin = await as(request, "admin");
  const requests = () => duty.get<PartnerRequest[]>("/api/partner-requests");

  // --- 1. The directory and coverage, labelled simulated (AS-01, AS-07) ---------------------
  const partners = await viewer.get<Partner[]>("/api/partners");
  expect(partners.map((p) => p.code).sort()).toEqual(["ATL", "HAR", "KES", "MER", "SEN"]);
  expect(partners.every((p) => p.simulated)).toBe(true);
  const gaps = (await viewer.get<Coverage[]>("/api/partners/coverage")).filter((c) => c.missing.length);
  expect(gaps.map((g) => [g.code, g.missing])).toEqual([
    ["BUE", ["EVACUATION"]],
    ["CBR", ["EVACUATION"]],
  ]);
  const viewerPage = await signedIn(browser, "viewer", "/partners");
  await expect(viewerPage.getByLabel("Partner network")).toContainText("Sentinel Secure Transport");
  await expect(viewerPage.getByText("Fictional partners · simulated")).toBeVisible();
  await expect(viewerPage.getByText("34 / 36")).toBeVisible();
  await expect(viewerPage.getByLabel("Coverage gaps")).toContainText("Canberra (CBR) · no evacuation");
  await expect(viewerPage.getByRole("button", { name: "Request" })).toHaveCount(0);
  await viewerPage.context().close();

  // --- 2. PB-07 step 6 asked Kestrel to stand by, and the simulated partner took it (AS-05) --
  const nairobi = (await duty.get<Incident[]>("/api/incidents")).find((i) => i.reference === `INC-${year}-1042`);
  expect(nairobi, "run after the Phase 1 spec (NBO-CIVIL-UNREST played)").toBeTruthy();
  const standby = await until(async () => {
    const found = (await requests()).find(
      (r) => r.incident_id === nairobi?.id && r.created_by_type === "PLAYBOOK" && r.status !== "REQUESTED",
    );
    return found;
  }, "the Kestrel standby request, accepted");
  expect([standby.partner_name, standby.service]).toEqual(["Kestrel Medical Assistance", "MEDICAL"]);
  expect(["ACCEPTED", "EN_ROUTE"]).toContain(standby.status);
  expect(standby.eta).not.toBeNull();

  // --- 3. A Viewer cannot request; the SOS is suggested, a Duty Officer decides (AS-02, AS-06) -
  const sentinel = (await duty.get<{ id: string; code: string }[]>("/api/partners")).find((p) => p.code === "SEN");
  const refused = await viewer.post("/api/partner-requests", {
    partner_id: sentinel?.id,
    service: "SECURE_TRANSPORT",
    incident_id: nairobi?.id,
  });
  expect(refused.status()).toBe(403);

  const checkin = (await duty.get<Campaign[]>("/api/campaigns")).find(
    (c) => c.campaign_type === "CHECKIN" && c.incident_id === nairobi?.id,
  );
  expect(checkin).toBeTruthy();
  const page = await signedIn(browser, "duty.officer", `/checkin?campaign=${checkin?.id}`);
  const peter = page.getByLabel("Live responses").locator(".nx-pp", { hasText: "Peter Mwangi" });
  await expect(peter).toContainText("NEEDS HELP");
  await peter.getByRole("button", { name: "Request partner" }).click();
  const dialog = page.getByRole("dialog", { name: "Request help for Peter Mwangi" });
  await expect(dialog.getByText(/Suggested:/)).toContainText(
    "Suggested: Sentinel Secure Transport · SLA 30 min · NBO mission",
  );
  await expect(dialog).toContainText("Partners are simulated");
  await dialog.getByLabel(/Note for the partner/).fill("Vehicle blocked on Haile Selassie Ave");
  await dialog.getByRole("button", { name: "Request" }).click();
  await expect(dialog).toHaveCount(0);
  const sos = await until(
    async () => (await requests()).find((r) => r.person_name === "Peter Mwangi" && r.service === "SECURE_TRANSPORT"),
    "Peter's request",
  );
  expect([sos.partner_name, sos.incident_id, sos.created_by_type]).toEqual([
    "Sentinel Secure Transport",
    nairobi?.id,
    "USER",
  ]);

  // --- 4. Tracked live on the screen, then completed by a person (AS-03, AS-04) -------------
  await page.goto("/partners");
  const row = page.locator(`tr[data-request="${sos.reference}"]`);
  await expect(row).toContainText("Vehicle blocked on Haile Selassie Ave");
  await expect(row).toContainText("ACCEPTED", { timeout: 40_000 }); // live, no reload
  await expect(row).toContainText("EN ROUTE", { timeout: 40_000 });
  await row.getByRole("button", { name: "Complete" }).click();
  await expect(row).toContainText("COMPLETED");
  await expect(row.getByRole("button")).toHaveCount(0);

  // --- 5. Audited, and the chain verifies (D-20) --------------------------------------------
  const audit =
    await admin.get<{ action: string; entity_id: string | null; actor_type: string }[]>("/api/audit?limit=500");
  const trail = audit
    .filter((e) => e.entity_id === sos.reference)
    .map((e) => [e.action, e.actor_type])
    .reverse();
  expect(trail).toEqual([
    ["PARTNER_REQUEST.CREATE", "USER"],
    ["PARTNER_REQUEST.ACCEPT", "SYSTEM"],
    ["PARTNER_REQUEST.EN_ROUTE", "SYSTEM"],
    ["PARTNER_REQUEST.COMPLETE", "USER"],
  ]);
  expect(await admin.get<{ intact: boolean }>("/api/audit/verify")).toMatchObject({ intact: true });

  expect(cspViolations).toEqual([]);
});
