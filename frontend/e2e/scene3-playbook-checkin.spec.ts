import { type APIRequestContext, type Browser, expect, type Page, test } from "@playwright/test";

// Prompt 11: the Duty Officer cannot see the step-7 approve button; the Nairobi
// Head of Mission approves it; check-in numbers update live.

const KEYCLOAK = process.env.E2E_KEYCLOAK_URL ?? "http://localhost:8080";
const API = process.env.E2E_API_URL ?? "http://localhost:8000";
const PASSWORD = process.env.DEMO_USER_PASSWORD ?? "";
const SCENARIO = "NBO-CIVIL-UNREST";

async function token(request: APIRequestContext, username: string): Promise<string> {
  const response = await request.post(
    `${KEYCLOAK}/realms/nexira-demo/protocol/openid-connect/token`,
    { form: { grant_type: "password", client_id: "nexira-dev-cli", username, password: PASSWORD } },
  );
  expect(response.ok()).toBeTruthy();
  return ((await response.json()) as { access_token: string }).access_token;
}

async function signedIn(browser: Browser, username: string, path: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await page.goto(path);
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(PASSWORD);
  await page.locator("#kc-login").click();
  await expect(page.getByRole("status", { name: "Realtime live" })).toBeVisible();
  return page;
}

async function until<T>(read: () => Promise<T | undefined>, what: string): Promise<T> {
  for (let i = 0; i < 60; i += 1) {
    const value = await read();
    if (value !== undefined) return value;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`timed out waiting for ${what}`);
}

test("PB-07 step 7 is approved by the Nairobi HoM only, and check-in updates live", async ({
  browser,
  request,
}) => {
  test.skip(!PASSWORD, "DEMO_USER_PASSWORD is not set (run through `make e2e`)");
  const headers = { Authorization: `Bearer ${await token(request, "duty.officer")}` };
  const get = async <T>(path: string): Promise<T> =>
    (await (await request.get(`${API}${path}`, { headers })).json()) as T;

  // A fresh Nairobi incident: earlier ones are set aside, scene 1 plays.
  for (const incident of await get<{ id: string }[]>("/api/incidents?status=ACTIVE")) {
    await request.patch(`${API}/api/incidents/${incident.id}/status`, {
      headers,
      data: { status: "MONITORING" },
    });
  }
  await request.post(`${API}/api/scenarios/${SCENARIO}/reset`, { headers });
  await request.post(`${API}/api/scenarios/${SCENARIO}/next`, { headers });
  const incidentId = await until(async () => {
    const active = await get<{ id: string; category: string; mission_id: string | null }[]>(
      "/api/incidents?status=ACTIVE",
    );
    return active.find((i) => i.category === "CIVIL_UNREST" && i.mission_id)?.id;
  }, "the Nairobi incident with its exposure");

  const started = await request.post(`${API}/api/playbook-runs`, {
    headers,
    data: { playbook_code: "PB-07", incident_id: incidentId },
  });
  expect(started.status()).toBe(201);
  const runId = ((await started.json()) as { id: string }).id;
  await until(async () => {
    const run = await get<{ status: string }>(`/api/playbook-runs/${runId}`);
    return run.status === "AWAITING_APPROVAL" ? true : undefined;
  }, "step 7");

  const url = `/playbooks?code=PB-07&run=${runId}`;
  const duty = await signedIn(browser, "duty.officer", url);
  await expect(duty.getByTestId("step-7")).toContainText("Awaiting approval");
  await expect(duty.getByRole("button", { name: /Approve as/ })).toHaveCount(0);

  const hom = await signedIn(browser, "hom.nairobi", url);
  await hom.getByRole("button", { name: "Approve as Head of Mission" }).click();
  await expect(hom.getByTestId("step-7")).toContainText("Approved by");
  // The Duty Officer's open page follows without a reload.
  await expect(duty.getByTestId("step-8")).toContainText("Situation report", { timeout: 15_000 });
  await expect(duty.getByText("8/8 complete")).toBeVisible();

  // Check-in: answers recorded through the API show up live.
  const checkin = await until(async () => {
    const campaigns = await get<{ id: string; campaign_type: string; status: string }[]>(
      `/api/campaigns?incident_id=${incidentId}`,
    );
    return campaigns.find((c) => c.campaign_type === "CHECKIN" && c.status === "SENT")?.id;
  }, "the check-in to be sent");
  await duty.goto(`/checkin?campaign=${checkin}`);
  const figures = duty.getByLabel("Personnel figures");
  await expect(figures).toContainText("0 of 17 responded");
  const pending = await get<{ person_id: string }[]>(
    `/api/checkin/${checkin}/people?group=personnel&status=PENDING`,
  );
  for (const p of pending.slice(0, 3)) {
    const answered = await request.post(`${API}/api/checkin/${checkin}/respond`, {
      headers,
      data: { person_id: p.person_id, status: "SAFE" },
    });
    expect(answered.status()).toBe(201);
  }
  await expect(figures).toContainText("3 of 17 responded");
  await expect(duty.getByLabel("Live responses").locator(".nx-pp")).toHaveCount(3);
});
