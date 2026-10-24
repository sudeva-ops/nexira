import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

// Prompt 8: start scene 1 through the API, and the incident appears on the
// Global Operations map without a page reload (PLT-05, OPS-01).

const KEYCLOAK = process.env.E2E_KEYCLOAK_URL ?? "http://localhost:8080";
const API = process.env.E2E_API_URL ?? "http://localhost:8000";
const PASSWORD = process.env.DEMO_USER_PASSWORD ?? "";
const SCENARIO = "NBO-CIVIL-UNREST";

async function apiToken(request: APIRequestContext, username: string): Promise<string> {
  // The local-only nexira-dev-cli client (password grant); never in a pilot realm.
  const response = await request.post(
    `${KEYCLOAK}/realms/nexira-demo/protocol/openid-connect/token`,
    { form: { grant_type: "password", client_id: "nexira-dev-cli", username, password: PASSWORD } },
  );
  expect(response.ok()).toBeTruthy();
  return ((await response.json()) as { access_token: string }).access_token;
}

async function signIn(page: Page, username: string) {
  await page.goto("/operations");
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(PASSWORD);
  await page.locator("#kc-login").click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Global Operations");
}

test("scene 1 puts the incident on the map without a reload", async ({ page, request }) => {
  test.skip(!PASSWORD, "DEMO_USER_PASSWORD is not set (run through `make e2e`)");
  const token = await apiToken(request, "duty.officer");
  const headers = { Authorization: `Bearer ${token}` };

  // A clean start: no ACTIVE incident for the signals to join, scenario at scene 0.
  const active = (await (
    await request.get(`${API}/api/incidents?status=ACTIVE`, { headers })
  ).json()) as { id: string }[];
  for (const incident of active) {
    const response = await request.patch(`${API}/api/incidents/${incident.id}/status`, {
      headers,
      data: { status: "MONITORING" },
    });
    expect(response.ok()).toBeTruthy();
  }
  expect((await request.post(`${API}/api/scenarios/${SCENARIO}/reset`, { headers })).ok()).toBeTruthy();

  await signIn(page, "duty.officer");
  await expect(page.getByRole("status", { name: "Realtime live" })).toBeVisible();
  const markers = page.locator('[data-testid^="incident-marker-"]');
  await expect(markers).toHaveCount(0);
  // Marks this document; a reload would lose it.
  await page.evaluate(() => {
    (window as unknown as { nxNoReload: boolean }).nxNoReload = true;
  });

  const next = await request.post(`${API}/api/scenarios/${SCENARIO}/next`, { headers });
  expect(next.ok()).toBeTruthy();

  await expect(markers.first()).toBeVisible({ timeout: 10_000 });
  await expect(markers.first()).toHaveAttribute("data-testid", /incident-marker-INC-\d{4}-\d{4}/);
  expect(await page.evaluate(() => (window as unknown as { nxNoReload?: boolean }).nxNoReload)).toBe(
    true,
  );
  await expect(page.getByLabel("Live intelligence feed")).toContainText("Dataminr (simulated)");
});
