import { expect, test } from "@playwright/test";

import { as, cspViolations, PASSWORD, signedIn, until } from "./support";

// Pilot module 1 acceptance (Prompt 22; requirements-pilot.md §6, D-31) on the real
// stack, after the Phase 1 acceptance (`make acceptance` runs both from reset-demo).
// The second person is the Consular Officer: the demo has one Duty Officer, and D-31
// allows DUTY_OFFICER or CONSULAR_OFFICER to approve.

interface Campaign {
  id: string;
  reference: string;
  status: string;
  recipients: number;
  message: string;
  translations: Record<string, string>;
  approved_by_name: string | null;
  funnel: Record<string, Record<string, number>>;
}
interface Proposal {
  id: string;
  action_type: string;
  status: string;
  incident_id: string | null;
  action_payload: Record<string, unknown>;
}
interface Incident {
  id: string;
  category: string;
  status: string;
  mission_id: string | null;
}

const NAIROBI_WORDS = ["Nairobi", "CBD", "Upper Hill"];

test("Mass Notification acceptance: compose, second person, live funnel, France", async ({
  browser,
  request,
}) => {
  test.skip(!PASSWORD, "DEMO_USER_PASSWORD is not set (run through `make acceptance`)");
  test.setTimeout(300_000);
  const duty = await as(request, "duty.officer");
  const admin = await as(request, "admin");
  const missions = await duty.get<{ id: string; code: string; city: string }[]>("/api/missions");
  const paris = missions.find((m) => m.code === "PAR");
  expect(paris).toBeDefined();

  // --- 1. The Duty Officer composes a Paris citizen advisory from a template ----------
  const author = await signedIn(browser, "duty.officer", "/notifications");
  await author.getByRole("option", { name: "PAR · Paris" }).waitFor({ state: "attached" });
  await author.getByLabel("Kind", { exact: true }).selectOption("ADVISORY");
  await author.getByLabel("Add mission", { exact: true }).selectOption({ label: "PAR · Paris" });
  await author.getByRole("group", { name: "Person types" }).getByRole("button", { name: "Citizens" }).click();
  await author.getByLabel("Template", { exact: true }).selectOption("CIVIL_UNREST_SHELTER");
  await expect(author.getByLabel("Message (English)", { exact: true })).toHaveValue(/central Paris/);
  await author.getByRole("button", { name: "Save draft" }).click();
  const recipients = author.getByLabel("Recipients", { exact: true });
  await expect(recipients).toContainText("a second person must approve");
  const count = Number((await recipients.innerText()).match(/(\d+) recipients/)?.[1]);
  expect(count).toBeGreaterThan(0);

  // Send test to me: a preview, and nothing queued (MN-08).
  await author.getByRole("button", { name: "Send test to me" }).click();
  await expect(author.getByLabel("Test preview")).toContainText("central Paris");

  await author.getByRole("button", { name: "Submit for approval" }).click();
  await author.waitForURL(/campaign=/);
  const campaignId = new URL(author.url()).searchParams.get("campaign") ?? "";
  const pending = await duty.get<Campaign>(`/api/campaigns/${campaignId}`);
  expect([pending.status, pending.recipients]).toEqual(["PENDING_APPROVAL", 0]); // nothing sent

  // --- 2. Self-approval is refused, in the UI and by the API (D-31, plan G-2) ------------
  await expect(author.getByText(`${pending.reference} · Awaiting approval`)).toBeVisible();
  await expect(author.getByRole("button", { name: "Approve and send" })).toHaveCount(0);
  expect((await duty.post(`/api/campaigns/${campaignId}/approve`)).status()).toBe(403);
  const viewer = await as(request, "viewer");
  expect((await viewer.post(`/api/campaigns/${campaignId}/approve`)).status()).toBe(403);

  // --- 3. The Consular Officer approves; the funnel reaches read for everyone, live --------
  const approver = await signedIn(browser, "consular.officer", `/notifications?campaign=${campaignId}`);
  await approver.getByRole("button", { name: "Approve and send" }).click();
  for (const channel of ["App push", "SMS"]) {
    await expect(approver.getByLabel(`${channel} funnel`)).toContainText(`${count}/${count} read`, {
      timeout: 30_000,
    });
  }
  const sent = await duty.get<Campaign>(`/api/campaigns/${campaignId}`);
  expect([sent.status, sent.recipients, sent.approved_by_name]).toEqual([
    "SENT",
    count,
    expect.stringMatching(/\S/),
  ]);
  expect(sent.message).toContain("Paris");
  expect(Object.keys(sent.translations).sort()).toEqual(["ar", "fr", "sw"]);

  // Every step is audited, and the chain verifies (MN-12, D-20).
  const audit = await admin.get<{ action: string; actor_type: string; entity_id: string }[]>(
    "/api/audit?limit=500",
  );
  const steps = audit.filter((e) => e.entity_id === sent.reference).map((e) => e.action);
  for (const step of ["CAMPAIGN.DRAFT", "CAMPAIGN.TEST_SEND", "CAMPAIGN.SUBMIT", "CAMPAIGN.APPROVE", "CAMPAIGN.SEND"]) {
    expect(steps, step).toContain(step);
  }
  expect(await admin.get<{ intact: boolean }>("/api/audit/verify")).toMatchObject({ intact: true });

  // --- 4. France: PB-07's advisory for Paris names Paris (MN-04, Prompt 19) ----------------
  const parisIncident = async () =>
    (await duty.get<Incident[]>("/api/incidents?status=ACTIVE")).find(
      (i) => i.category === "CIVIL_UNREST" && i.mission_id === paris?.id,
    );
  if (!(await parisIncident())) {
    await duty.post("/api/scenarios/FRA-NATIONAL-PROTESTS/reset");
    await duty.post("/api/scenarios/FRA-NATIONAL-PROTESTS/next");
  }
  const incident = await until(parisIncident, "the Paris incident", 120);
  const proposals = () => duty.get<Proposal[]>("/api/proposals?limit=200");
  const advisoryFor = async () =>
    (await proposals()).find((p) => p.action_type === "SEND_EXTERNAL_MESSAGE" && p.incident_id === incident.id);
  if (!(await advisoryFor())) {
    const planner = await until(
      async () =>
        (await proposals()).find(
          (p) => p.action_type === "START_PLAYBOOK" && p.incident_id === incident.id && p.status === "PENDING",
        ),
      "PB-07 proposed for Paris",
    );
    expect((await duty.post(`/api/proposals/${planner.id}/approve`)).status()).toBe(200);
  }
  const advisory = await until(advisoryFor, "the Paris advisory");
  const texts = [
    String(advisory.action_payload.message),
    ...Object.values(advisory.action_payload.translations as Record<string, string>),
  ];
  expect(texts[0]).toContain("Paris");
  for (const word of NAIROBI_WORDS) expect(texts.join(" ")).not.toContain(word);

  expect(cspViolations).toEqual([]);
});
