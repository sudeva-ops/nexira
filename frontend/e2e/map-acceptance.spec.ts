import { expect, type Page, test } from "@playwright/test";

import { API, as, cspViolations, KEYCLOAK, PASSWORD, signedIn, until } from "./support";

// Map tools acceptance (Prompt 133; requirements-pilot.md §114, D-52; plan-pilot-map §5) on the
// real stack. `make acceptance` runs it in the first batch, after the Document Expiry spec has
// set INC-<year>-1042 ACTIVE again. Annotations near the incident with a second browser as the
// Viewer; Nearby from the Nairobi embassy; the four searches; the audit. The map is a canvas, so
// what it draws is read from the map element's data-annotations and data-marked.

interface Incident {
  id: string;
  reference: string;
  status: string;
  lon: number;
  lat: number;
  impact_radius_m: number;
  exposure_summary: { staff: number; delegates: number; citizens: number };
  timeline: { event_type: string; summary: string }[];
}
interface Nearby {
  people: { staff: number; delegates: number; citizens: number; others: number; named: { name: string }[]; unnamed: number };
  sites: { name: string }[];
  vehicles: { code: string }[];
  incidents: { reference: string }[];
  annotations: { label: string }[];
}

const year = new Date().getUTCFullYear();
const INCIDENT = `INC-${year}-1042`;
const CHECKPOINT = "Checkpoint · Uhuru Highway";
const AREA = "Avoid: crowd at the CBD";
const MARK_AT = [0.62, 0.4] as const; // on the map, away from the incident's own marker
const AREA_AT = [
  [0.3, 0.6],
  [0.42, 0.55],
  [0.38, 0.72],
] as const;

async function at(page: Page, [fx, fy]: readonly [number, number], button: "left" | "right" = "left") {
  const box = await page.getByTestId("operations-map").boundingBox();
  if (!box) throw new Error("no map");
  // The mouse, not locator.click: Playwright would scroll the map's overflow box (Prompt 126).
  await page.mouse.click(box.x + box.width * fx, box.y + box.height * fy, { button });
}

const shown = (page: Page) => page.getByTestId("operations-map");

test("Map tools acceptance: annotations live to the Viewer, Nearby, search, the audit", async ({ browser, request }) => {
  test.skip(!PASSWORD, "DEMO_USER_PASSWORD is not set (run through `make acceptance`)");
  test.setTimeout(240_000);
  const duty = await as(request, "duty.officer");
  const viewer = await as(request, "viewer");
  const admin = await as(request, "admin");
  const listed = (await duty.get<Incident[]>("/api/incidents")).find((i) => i.reference === INCIDENT);
  expect(listed?.status, "run after the Document Expiry spec").toBe("ACTIVE");
  if (!listed) return;
  const incident = () => duty.get<Incident>(`/api/incidents/${listed.id}`);
  const auditBefore = (await admin.get<{ action: string }[]>("/api/audit?entity_type=map_annotation&limit=500")).length;

  // --- 1. The Duty Officer marks a checkpoint and draws an area (ANN-01) ----------------------
  const page = await signedIn(browser, "duty.officer", `/operations?incident=${listed.id}`);
  const hosts = new Set<string>();
  const asked: string[] = [];
  page.on("request", (r) => {
    hosts.add(new URL(r.url()).host);
    asked.push(decodeURIComponent(r.url()));
  });
  const reader = await signedIn(browser, "viewer", `/operations?incident=${listed.id}`);
  await expect(reader.getByRole("toolbar", { name: "Annotate" })).toHaveCount(0); // §115 Q2
  const tools = page.getByRole("toolbar", { name: "Annotate" });
  await expect(tools.getByRole("button", { name: "Mark" })).toBeEnabled({ timeout: 20_000 }); // zoomed in
  await expect(shown(reader)).toHaveAttribute("data-annotations", "0");
  await page.waitForTimeout(2_000); // the camera settles on the zone

  await tools.getByRole("button", { name: "Mark" }).click();
  await at(page, MARK_AT);
  const mark = page.getByRole("dialog", { name: "New mark" });
  await mark.getByLabel("Label").fill(CHECKPOINT);
  await expect(mark.getByLabel("Incident")).toHaveValue(listed.id); // the selected incident
  await mark.getByRole("button", { name: "Add" }).click();
  await expect(mark).toHaveCount(0);
  // ANN-02: live on the Viewer's map within 2 seconds.
  const added = Date.now();
  await expect(shown(reader)).toHaveAttribute("data-annotations", "1", { timeout: 5_000 });
  const live = Date.now() - added;
  expect(live, "ms to the Viewer's map").toBeLessThan(2_000);

  await tools.getByRole("button", { name: "Area" }).click();
  for (const point of AREA_AT) await at(page, point);
  await page.keyboard.press("Enter");
  const area = page.getByRole("dialog", { name: "New area" });
  await area.getByLabel("Label").fill(AREA);
  await area.getByRole("button", { name: "Add" }).click();
  await expect(area).toHaveCount(0);
  await expect(shown(page)).toHaveAttribute("data-annotations", "2");
  await expect(shown(reader)).toHaveAttribute("data-annotations", "2", { timeout: 5_000 });

  // --- 2. The Viewer reads, by role, and cannot add (ANN-02, ANN-04) ---------------------------
  // The Viewer's map is not framed exactly as the Duty Officer's, so what it is given is read
  // from the API as the Viewer; the card is checked on the Duty Officer's map below.
  const given = await viewer.get<{ annotations: { label: string; role: string; can_edit: boolean }[]; can_add: boolean }>(
    "/api/annotations",
  );
  expect(given.can_add).toBe(false);
  expect(given.annotations.filter((a) => [CHECKPOINT, AREA].includes(a.label)).map((a) => [a.role, a.can_edit])).toEqual([
    ["Duty Officer", false],
    ["Duty Officer", false],
  ]);
  expect(JSON.stringify(given)).not.toContain("Daniel Mercer"); // the Duty Officer's name
  const refused = await viewer.post("/api/annotations", {
    kind: "MARK",
    symbol: "NOTE",
    shape: { type: "Point", coordinates: [36.82, -1.29] },
    label: "Not allowed",
  });
  expect(refused.status()).toBe(403);

  // --- 3. The Duty Officer withdraws the checkpoint; it leaves both maps (ANN-03) -------------
  await at(page, MARK_AT);
  const mine = page.getByRole("dialog", { name: `Annotation: ${CHECKPOINT}` });
  await expect(mine).toContainText("Duty Officer ·"); // ANN-04: the role, not the name
  await expect(mine).toContainText(INCIDENT);
  expect(await mine.textContent()).not.toContain("Daniel Mercer");
  await mine.getByRole("button", { name: "Withdraw" }).click();
  await mine.getByLabel("Reason").fill("Cleared by police");
  await mine.getByRole("button", { name: "Withdraw" }).click();
  await expect(shown(page)).toHaveAttribute("data-annotations", "1");
  await expect(shown(reader)).toHaveAttribute("data-annotations", "1", { timeout: 5_000 });

  // ANN-06: the incident's timeline has both, and the withdrawal.
  const entries = (await incident()).timeline.filter((e) => e.event_type === "ANNOTATION").map((e) => e.summary);
  expect(entries).toEqual(
    expect.arrayContaining([
      `Annotation added: Checkpoint · ${CHECKPOINT}.`,
      `Annotation added: Area · ${AREA}.`,
      `Annotation withdrawn: Checkpoint · ${CHECKPOINT} (Cleared by police).`,
    ]),
  );

  // --- 4. Nearby (NBY-01..04) -------------------------------------------------------------------
  const detail = await incident();
  // At the incident's centre and radius, the groups are the exposure's (plan G-5).
  const zone = await duty.get<Nearby>(
    `/api/nearby?lon=${detail.lon}&lat=${detail.lat}&radius_m=${detail.impact_radius_m}`,
  );
  expect([zone.people.staff, zone.people.delegates, zone.people.citizens]).toEqual([
    detail.exposure_summary.staff,
    detail.exposure_summary.delegates,
    detail.exposure_summary.citizens,
  ]);
  const embassy = (await duty.get<{ items: { name: string; lat: number; lon: number }[] }>("/api/sites?q=Embassy Nairobi"))
    .items.find((s) => s.name === "Embassy Nairobi");
  expect(embassy).toBeTruthy();
  if (!embassy) return;
  const near = `/operations?near=${embassy.lat},${embassy.lon}&r=10`;
  const around = await duty.get<Nearby>(`/api/nearby?lon=${embassy.lon}&lat=${embassy.lat}&radius_m=10000`);
  expect(around.sites.map((s) => s.name)).toContain("Embassy Nairobi");
  expect(around.vehicles.length).toBeGreaterThan(0);
  expect(around.incidents.map((i) => i.reference)).toContain(INCIDENT);
  expect(around.annotations.map((a) => a.label)).toEqual([AREA]); // the checkpoint is withdrawn
  await page.goto(near);
  const panel = page.getByLabel("What's nearby");
  await expect(panel).toContainText(`${around.people.staff} staff`, { timeout: 20_000 });
  await expect(panel).toContainText(`${around.people.citizens} citizens`);
  await expect(panel).toContainText("Embassy Nairobi");
  await expect(panel).toContainText(INCIDENT);
  await expect(panel).toContainText(AREA);
  await expect(panel).toContainText(around.vehicles[0]?.code ?? "VH-");
  const named = around.people.named.slice(0, 5).map((p) => p.name);
  expect(named.length).toBeGreaterThan(0);
  for (const name of named) await expect(panel).toContainText(name);
  // The Viewer: the same counts, no names (NBY-03).
  const seen = await viewer.get<Nearby>(`/api/nearby?lon=${embassy.lon}&lat=${embassy.lat}&radius_m=10000`);
  expect([seen.people.staff, seen.people.citizens, seen.people.named]).toEqual([around.people.staff, around.people.citizens, []]);
  await reader.goto(near);
  const theirs = reader.getByLabel("What's nearby");
  await expect(theirs).toContainText("more not named for your role", { timeout: 20_000 });
  const text = (await theirs.textContent()) ?? "";
  for (const name of named) expect(text, name).not.toContain(name);
  await reader.context().close();

  // --- 5. Search, in the browser only (SRC-01..04) ---------------------------------------------
  await page.goto("/operations");
  await expect(page.getByText("GLOBAL VIEW")).toBeVisible({ timeout: 20_000 });
  const box = page.getByRole("combobox", { name: "Search the map" });
  await page.keyboard.press("/");
  await expect(box).toBeFocused();
  await box.fill("NBO");
  await expect(page.getByRole("option").first()).toContainText("Nairobi · NBO");
  await page.keyboard.press("Enter");
  const nbo = (await duty.get<{ code: string; lat: number; lon: number }[]>("/api/missions")).find((m) => m.code === "NBO");
  await expect(shown(page)).toHaveAttribute("data-marked", `${nbo?.lat},${nbo?.lon}`);
  await box.fill("geo:-4.04,39.67");
  await page.keyboard.press("Enter");
  await expect(shown(page)).toHaveAttribute("data-marked", "-4.04,39.67"); // Mombasa
  await box.fill("Kampala");
  await expect(page.getByRole("option", { name: /Kampala.*UG/ })).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(shown(page)).toHaveAttribute("data-marked", /^0\.3\d*,32\.5\d*$/);
  await box.fill(INCIDENT);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`incident=${listed.id}`));
  await expect(page.getByLabel("Exposure summary")).toBeVisible();
  const stack = new Set([new URL(API).host, new URL(KEYCLOAK).host]);
  const outside = [...hosts].filter((h) => !stack.has(h) && !/^(localhost|127\.0\.0\.1)(:\d+)?$/.test(h));
  expect(outside, "requests outside the stack").toEqual([]);
  expect(asked.filter((u) => /kampala|geo:-4\.04/i.test(u)), "a request carrying the search").toEqual([]);
  await page.context().close();

  // --- 6. Audited, and the chain verifies (ANN-05, D-20) ---------------------------------------
  const trail = await until(async () => {
    const rows = await admin.get<{ action: string; actor_type: string }[]>(
      "/api/audit?entity_type=map_annotation&limit=500",
    );
    return rows.length >= auditBefore + 3 ? rows : undefined;
  }, "the annotation audit");
  expect(trail.slice(0, trail.length - auditBefore).map((r) => r.action).sort()).toEqual([
    "ANNOTATION.ADD",
    "ANNOTATION.ADD",
    "ANNOTATION.WITHDRAW",
  ]);
  expect(new Set(trail.map((r) => r.actor_type))).toEqual(new Set(["USER"]));
  expect(await admin.get<{ intact: boolean }>("/api/audit/verify")).toMatchObject({ intact: true });
  expect(cspViolations).toEqual([]);
});
