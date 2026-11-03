import { expect, test } from "@playwright/test";

import { as, cspViolations, PASSWORD, signedIn } from "./support";

// Executive Overview acceptance (Prompt 98; requirements-pilot.md §77, D-45) on the real stack.
// `make acceptance` runs it after the Evacuation spec (Playwright orders files by name). The
// calm state and the Nairobi figures are checked in the Phase 1 spec, the only place they exist
// (plan-pilot-exe G-1). Here: the screen agrees with the API, Nairobi's incident drives it, the
// briefing is an audited export with no names, and the Viewer sees the same page.

interface Overview {
  posture: { level: string };
  active_incidents: number;
  accounted: { pct: number | null };
  readiness: { mean: number | null };
  attention: {
    mission_code: string;
    city: string;
    drivers: { kind: string; reference: string | null }[];
  }[];
  timeline: { incident: { reference: string } | null };
}

const year = new Date().getUTCFullYear();
const INCIDENT = `INC-${year}-1042`;
// Seeded staff and travellers (simulated); none may appear on the overview or the briefing.
const NAMES = [
  "Peter Mwangi",
  "Hana Takeda",
  "Grace Wanjiru",
  "Omar Siddiqui",
  "Elena Costa",
];

test("Executive Overview acceptance: the figures, Nairobi's drivers, the briefing, the Viewer", async ({
  browser,
  request,
}) => {
  test.skip(
    !PASSWORD,
    "DEMO_USER_PASSWORD is not set (run through `make acceptance`)",
  );
  test.setTimeout(180_000);
  const duty = await as(request, "duty.officer");
  const admin = await as(request, "admin");
  const incidents =
    await duty.get<{ id: string; reference: string; status: string }[]>(
      "/api/incidents",
    );
  const nairobi = incidents.find((i) => i.reference === INCIDENT);
  expect(
    nairobi?.status,
    "run after the Phase 1 and Document Expiry specs",
  ).toBe("ACTIVE");

  // --- 1. The screen shows the API's figures (EXE-01, EXE-05) ---------------------------------
  const o = await duty.get<Overview>("/api/executive/overview");
  expect(o.active_incidents).toBeGreaterThan(0);
  expect(o.posture.level).not.toBe("GUARDED"); // an ACTIVE incident at least makes it ELEVATED
  const page = await signedIn(browser, "duty.officer", "/executive");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Executive Overview",
  );
  await expect(page.getByText(o.posture.level, { exact: true })).toBeVisible();
  await expect(
    page.getByText(`${o.readiness.mean}/100`, { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", {
      name: /Last 30 days: \d+ incidents from \d+ signals/,
    }),
  ).toBeVisible();
  await expect(page.getByLabel("Risk exposure by region")).toContainText(
    "Africa",
  );

  // --- 2. Nairobi requires attention, driven by its incident (EXE-02) ------------------------
  const nbo = o.attention.find((a) => a.mission_code === "NBO");
  expect(nbo?.drivers.find((d) => d.kind === "INCIDENT")?.reference).toBe(
    INCIDENT,
  );
  const table = page.getByRole("table", {
    name: "Missions requiring attention",
  });
  await expect(table.locator('tr[data-mission="NBO"]')).toContainText(INCIDENT);
  if (o.timeline.incident) {
    await expect(
      page.getByText(`${o.timeline.incident.reference} · response timeline`),
    ).toBeVisible();
  }
  for (const name of NAMES) expect(JSON.stringify(o), name).not.toContain(name);
  expect(await page.content()).not.toContain("Peter Mwangi");

  // --- 3. The briefing: print-ready, audited, no names (EXE-03, EXE-04) ----------------------
  const before = (
    await admin.get<{ action: string }[]>(
      "/api/audit?entity_type=executive_overview&limit=500",
    )
  ).filter((e) => e.action === "EXECUTIVE.EXPORT").length;
  await page.getByRole("button", { name: "Export briefing" }).click();
  const briefing = page.getByTestId("briefing");
  await expect(briefing.getByRole("heading", { level: 1 })).toHaveText(
    "Leadership briefing",
  );
  await expect(briefing).toContainText("Simulated data");
  await expect(briefing.getByLabel("Headline figures")).toContainText(
    o.posture.level,
  );
  await expect(
    briefing.getByRole("table", { name: "Briefing missions" }),
  ).toContainText("Nairobi");
  await expect(page.getByRole("navigation")).toHaveCount(0); // standalone, no shell
  const text = (await briefing.textContent()) ?? "";
  for (const name of NAMES) expect(text, name).not.toContain(name);
  const exports = await admin.get<{ action: string; actor_type: string }[]>(
    "/api/audit?entity_type=executive_overview&limit=500",
  );
  expect(exports.filter((e) => e.action === "EXECUTIVE.EXPORT")).toHaveLength(
    before + 1,
  );
  expect(
    await admin.get<{ intact: boolean }>("/api/audit/verify"),
  ).toMatchObject({ intact: true });

  // --- 4. The Viewer sees the same page (EXE-04) ----------------------------------------------
  const viewer = await signedIn(browser, "viewer", "/executive");
  await expect(
    viewer.getByText(o.posture.level, { exact: true }),
  ).toBeVisible();
  await expect(
    viewer
      .getByRole("table", { name: "Missions requiring attention" })
      .locator('tr[data-mission="NBO"]'),
  ).toContainText(INCIDENT);
  await viewer.context().close();

  expect(cspViolations).toEqual([]);
});
