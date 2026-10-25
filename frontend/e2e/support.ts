import { execFileSync } from "node:child_process";
import path from "node:path";

import { type APIRequestContext, type Browser, expect, type Page } from "@playwright/test";

export const KEYCLOAK = process.env.E2E_KEYCLOAK_URL ?? "http://localhost:8080";
export const API = process.env.E2E_API_URL ?? "http://localhost:8000";
export const PASSWORD = process.env.DEMO_USER_PASSWORD ?? "";

export async function token(request: APIRequestContext, username: string): Promise<string> {
  const response = await request.post(
    `${KEYCLOAK}/realms/nexira-demo/protocol/openid-connect/token`,
    { form: { grant_type: "password", client_id: "nexira-dev-cli", username, password: PASSWORD } },
  );
  expect(response.ok()).toBeTruthy();
  return ((await response.json()) as { access_token: string }).access_token;
}

/** A small API client acting as one demo user. */
export async function as(request: APIRequestContext, username: string) {
  const headers = { Authorization: `Bearer ${await token(request, username)}` };
  return {
    get: async <T>(p: string): Promise<T> => {
      const response = await request.get(`${API}${p}`, { headers });
      expect(response.ok(), `GET ${p}`).toBeTruthy();
      return (await response.json()) as T;
    },
    post: (p: string, data: unknown = {}) => request.post(`${API}${p}`, { headers, data }),
    patch: (p: string, data: unknown) => request.patch(`${API}${p}`, { headers, data }),
  };
}

export async function signedIn(browser: Browser, username: string, start = "/"): Promise<Page> {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  await page.goto(start);
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(PASSWORD);
  await page.locator("#kc-login").click();
  await expect(page.getByRole("status", { name: "Realtime live" })).toBeVisible();
  return page;
}

export async function until<T>(read: () => Promise<T | undefined>, what: string, seconds = 60): Promise<T> {
  for (let i = 0; i < seconds * 2; i += 1) {
    const value = await read();
    if (value !== undefined) return value;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`timed out waiting for ${what}`);
}

/** Runs a simulator fixture (local/demo only) and returns its output. */
export function fixture(name: string): string {
  return execFileSync("uv", ["run", "python", "-m", `nexira_sim.fixtures.${name}`], {
    cwd: path.resolve(process.cwd(), "../simulator"),
    env: { ...process.env, APP_ENV: process.env.APP_ENV ?? "local" },
    encoding: "utf8",
  }).trim();
}
