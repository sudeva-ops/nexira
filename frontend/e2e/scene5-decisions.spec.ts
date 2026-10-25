import { execFileSync } from "node:child_process";
import path from "node:path";

import { type APIRequestContext, type Browser, expect, type Page, test } from "@playwright/test";

// Prompt 14: approve the PB-07 proposal; reject a proposal with a reason; the
// two-person rule with the Nairobi HoM and then the HQ Crisis Director, in two
// browser contexts.

const KEYCLOAK = process.env.E2E_KEYCLOAK_URL ?? "http://localhost:8080";
const API = process.env.E2E_API_URL ?? "http://localhost:8000";
const PASSWORD = process.env.DEMO_USER_PASSWORD ?? "";
const SCENARIO = "NBO-CIVIL-UNREST";

interface ProposalRow {
  id: string;
  action_type: string;
  status: string;
  incident_id: string | null;
  rejection_reason: string | null;
  approvals: { decided_by_name: string | null }[];
}

async function token(request: APIRequestContext, username: string): Promise<string> {
  const response = await request.post(
    `${KEYCLOAK}/realms/nexira-demo/protocol/openid-connect/token`,
    { form: { grant_type: "password", client_id: "nexira-dev-cli", username, password: PASSWORD } },
  );
  expect(response.ok()).toBeTruthy();
  return ((await response.json()) as { access_token: string }).access_token;
}

async function signedIn(browser: Browser, username: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await page.goto("/");
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(PASSWORD);
  await page.locator("#kc-login").click();
  await expect(page.getByRole("status", { name: "Realtime live" })).toBeVisible();
  return page;
}

async function until<T>(read: () => Promise<T | undefined>, what: string): Promise<T> {
  for (let i = 0; i < 80; i += 1) {
    const value = await read();
    if (value !== undefined) return value;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`timed out waiting for ${what}`);
}

test("decisions in the queue: approve, reject with a reason, and the two-person rule", async ({
  browser,
  request,
}) => {
  test.skip(!PASSWORD, "DEMO_USER_PASSWORD is not set (run through `make e2e`)");
  test.setTimeout(120_000);
  const headers = { Authorization: `Bearer ${await token(request, "duty.officer")}` };
  const get = async <T>(p: string): Promise<T> =>
    (await (await request.get(`${API}${p}`, { headers })).json()) as T;
  const proposals = () => get<ProposalRow[]>("/api/proposals?limit=200");

  // A fresh Nairobi incident from scene 1; the Response Planner proposes PB-07.
  for (const incident of await get<{ id: string }[]>("/api/incidents?status=ACTIVE")) {
    await request.patch(`${API}/api/incidents/${incident.id}/status`, {
      headers,
      data: { status: "MONITORING" },
    });
  }
  await request.post(`${API}/api/scenarios/${SCENARIO}/reset`, { headers });
  await request.post(`${API}/api/scenarios/${SCENARIO}/next`, { headers });
  const incidentId = await until(async () => {
    const active = await get<{ id: string; category: string }[]>("/api/incidents?status=ACTIVE");
    return active.find((i) => i.category === "CIVIL_UNREST")?.id;
  }, "the Nairobi incident");
  const planned = await until(
    async () =>
      (await proposals()).find(
        (p) => p.action_type === "START_PLAYBOOK" && p.incident_id === incidentId && p.status === "PENDING",
      ),
    "the PB-07 proposal",
  );

  // 1. The Duty Officer approves PB-07 in the queue.
  const duty = await signedIn(browser, "duty.officer");
  const card = (page: Page, id: string) => page.locator(`[data-proposal-id="${id}"]`);
  const pb07 = card(duty, planned.id);
  await pb07.getByRole("button", { name: "Approve as Duty Officer or Security Officer" }).click();
  await expect(pb07).toHaveCount(0); // it leaves the pending tab
  await until(
    async () => ((await proposals()).find((p) => p.id === planned.id)?.status === "APPROVED" ? true : undefined),
    "PB-07 approved",
  );

  // 2. PB-07 step 4 makes Communications propose the advisory; the Duty Officer
  //    rejects it with a reason, in the page that is still open.
  const advisoryRow = await until(
    async () =>
      (await proposals()).find(
        (p) => p.action_type === "SEND_EXTERNAL_MESSAGE" && p.incident_id === incidentId && p.status === "PENDING",
      ),
    "the advisory proposal",
  );
  const advisory = card(duty, advisoryRow.id);
  await expect(advisory).toBeVisible({ timeout: 15_000 });
  await advisory.getByRole("button", { name: "Reject" }).click();
  await advisory.getByRole("button", { name: "Handled offline" }).click();
  const rejected = await until(
    async () => (await proposals()).find((p) => p.id === advisoryRow.id && p.status === "REJECTED"),
    "the advisory rejected",
  );
  expect(rejected.rejection_reason).toBe("Handled offline");

  // 3. Two-person rule: the scene 5 evacuation proposal (plan G-16 fixture).
  const evacuationId = execFileSync("uv", ["run", "python", "-m", "nexira_sim.fixtures.evacuation"], {
    cwd: path.resolve(process.cwd(), "../simulator"),
    env: { ...process.env, APP_ENV: process.env.APP_ENV ?? "local" },
    encoding: "utf8",
  }).trim();

  await duty.reload();
  const asDuty = card(duty, evacuationId);
  await expect(asDuty).toBeVisible();
  await expect(asDuty.getByRole("button", { name: /^Approve/ })).toHaveCount(0);

  const hom = await signedIn(browser, "hom.nairobi");
  const asHom = card(hom, evacuationId);
  await asHom.getByRole("button", { name: "Approve as Head of Mission (1/2)" }).click();
  await expect(asHom.getByTestId("approver-1")).toContainText("✓ Head of Mission");
  // One approval does not execute (AGT-04), and the HoM cannot take step 2.
  await expect(asHom.getByRole("button", { name: /^Approve/ })).toHaveCount(0);
  expect((await proposals()).find((p) => p.id === evacuationId)?.status).toBe("PENDING");

  const hq = await signedIn(browser, "hq.director");
  const asHq = card(hq, evacuationId);
  await asHq.getByRole("button", { name: "Approve as HQ Crisis Director (2/2)" }).click();
  await expect(asHq).toHaveCount(0); // decided: off the pending tab
  const done = await until(
    async () => {
      const p = (await proposals()).find((x) => x.id === evacuationId);
      return p?.status === "APPROVED" ? p : undefined;
    },
    "the evacuation approved",
  );
  expect(done.approvals.map((a) => a.decided_by_name)).toEqual([expect.any(String), expect.any(String)]);
});
