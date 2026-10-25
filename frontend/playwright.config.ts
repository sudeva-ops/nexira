import { defineConfig, devices } from "@playwright/test";

// End-to-end tests against the running stack (`make up`, `make seed`). Run with `make e2e`.
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: 0,
  // The tests share one running stack and one scenario: run them one at a time.
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
