import { expect, type Page, test } from "@playwright/test";

import { SEVERITY_COLOUR } from "../src/map/geo";
import { API, as, cspViolations, KEYCLOAK, PASSWORD, signedIn, until } from "./support";

// Graphics acceptance (Prompt 146; requirements-pilot.md §129, D-55; plan-pilot-gfx) on the real
// stack. `make acceptance` runs it after a reset of its own, before twa-acceptance.
// After the reset: the 30-day trend is not flat and its illustrative days are labelled; the
// Decision Queue and Executive Overview leave no column blank (G-8) at 1440 × 900; the NASA
// imagery loads from /tiles/ and no request leaves the stack; nothing is drawn outside the
// globe's disc on Global Operations and Air Travel. After scene 1: the incident mini-map shows
// the incident and opens Global Operations on it.

interface Incident {
  id: string;
  reference: string;
  severity: keyof typeof SEVERITY_COLOUR;
}

const rgb = (hex: string) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));

/** G-8: in each column of the screen's last grid, how far the lowest card ends above the bottom
 *  of the content area; and whether the content scrolls instead. */
async function blankBelow(page: Page, grid: string) {
  return page.evaluate((grid) => {
    const pad = document.querySelector(".nx-pad");
    const rows = document.querySelectorAll(grid);
    const last = rows[rows.length - 1];
    if (!pad?.parentElement || !last) return null;
    const area = pad.parentElement;
    const bottom = area.getBoundingClientRect().bottom;
    const columns = Array.from(last.children).map((column) => {
      const cards = column.matches(".nx-card") ? [column] : Array.from(column.querySelectorAll(".nx-card"));
      return Math.round(bottom - Math.max(...cards.map((c) => c.getBoundingClientRect().bottom)));
    });
    return { columns, limit: Math.round(window.innerHeight / 3), scrolls: area.scrollHeight > area.clientHeight + 1 };
  }, grid);
}

/** GFX-04: along the middle row of the map, the space from each edge to just short of the globe's
 *  rim. Each 16 px stretch's median colour must match the space at the map's left edge: a star is
 *  a dot and does not move a median, a band or glow would. The space itself must be dark and
 *  plain. Returns the worst distance from it. */
async function outsideTheDisc(page: Page, testId: string) {
  const map = page.getByTestId(testId);
  const box = await map.boundingBox();
  if (!box) return null;
  const shot = (await page.screenshot({ clip: box })).toString("base64");
  return page.evaluate(
    async (shot) => {
      const img = new Image();
      img.src = `data:image/png;base64,${shot}`;
      await img.decode();
      const canvas = document.createElement("canvas");
      canvas.width = img.width;
      canvas.height = img.height;
      const ctx = canvas.getContext("2d");
      if (!ctx) return null;
      ctx.drawImage(img, 0, 0);
      const y = Math.round(img.height / 2);
      const row = ctx.getImageData(0, y, img.width, 1).data;
      const px = (x: number) => [row[4 * x] ?? 0, row[4 * x + 1] ?? 0, row[4 * x + 2] ?? 0];
      const median = (xs: number[]) => xs.sort((a, b) => a - b)[Math.floor(xs.length / 2)] ?? 0;
      const stretch = (a: number) =>
        [0, 1, 2].map((c) => median(Array.from({ length: 16 }, (_, i) => px(a + i)[c] ?? 0)));
      const space = stretch(4);
      const off = (p: number[]) => p.reduce((sum, v, i) => sum + Math.abs(v - (space[i] ?? 0)), 0);
      // The rim: the first run of 8 pixels in a row that are not space (a star is 1-3 px wide).
      const rim = (from: number, step: number) => {
        let run = 0;
        for (let x = from; x >= 0 && x < img.width; x += step) {
          run = off(px(x)) > 30 ? run + 1 : 0;
          if (run === 8) return x - 7 * step;
        }
        return -1;
      };
      const left = rim(0, 1);
      const right = rim(img.width - 1, -1);
      if (left < 0 || right < 0) return null;
      let worst = 0;
      const stretches: [number, number][] = [];
      for (let x = 4; x + 16 <= left - 16; x += 16) stretches.push([x, x + 16]);
      for (let x = right + 16; x + 16 <= img.width - 4; x += 16) stretches.push([x, x + 16]);
      for (const [a] of stretches) worst = Math.max(worst, off(stretch(a)));
      return { space, left, right, width: img.width, stretches: stretches.length, worst };
    },
    shot,
  );
}

test("Graphics: the trend, resting layouts, NASA imagery, the globe's edge and the mini-map", async ({
  browser,
  request,
}) => {
  test.skip(!PASSWORD, "DEMO_USER_PASSWORD is not set (run through `make acceptance`)");
  test.setTimeout(6 * 60_000);
  const duty = await as(request, "duty.officer");
  expect(await duty.get<Incident[]>("/api/incidents?status=ACTIVE"), "run from `make reset-demo`").toEqual([]);
  const page = await signedIn(browser, "duty.officer", "/");
  const stack = new Set([new URL(page.url()).origin, new URL(KEYCLOAK).origin, new URL(API).origin]);
  const leaving: string[] = [];
  page.on("request", (r) => {
    const url = new URL(r.url());
    if (url.protocol.startsWith("http") && !stack.has(url.origin)) leaving.push(r.url());
  });

  // --- 1. The 30-day trend: not flat, illustrative days labelled (GFX-05) ----------------------
  await page.goto("/executive");
  const trend = page.getByRole("img", { name: /^Last 30 days/ });
  await expect(trend).toBeVisible();
  const label = (await trend.getAttribute("aria-label")) ?? "";
  const faint = Number(/the first (\d+) days illustrative/.exec(label)?.[1] ?? 0);
  expect(faint, label).toBeGreaterThanOrEqual(20);
  const heights = await trend.locator("rect[height]").evaluateAll((rs) => rs.map((r) => r.getAttribute("height")));
  expect(new Set(heights).size, "bars of different heights").toBeGreaterThan(5);
  expect(await trend.locator("title", { hasText: "(illustrative)" }).count()).toBe(faint);
  await expect(page.getByText(`first ${faint} days illustrative`)).toBeVisible();

  // --- 2. No column left blank at 1440 × 900 (GFX-06, G-8) --------------------------------------
  for (const [route, grid] of [
    ["/executive", ".nx-exe-grid"],
    ["/", ".nx-queue"],
  ] as const) {
    await page.goto(route);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    if (route === "/") await expect(page.getByLabel("Watching now")).toContainText("Missions");
    else await expect(page.getByLabel("Recent activity")).toBeVisible();
    await page.waitForTimeout(1500); // the cards' data
    const blank = await blankBelow(page, grid);
    console.log("g8", route, JSON.stringify(blank));
    expect(blank, route).not.toBeNull();
    if (!blank || blank.scrolls) continue;
    for (const gap of blank.columns) expect(gap, `${route}: blank below a column`).toBeLessThanOrEqual(blank.limit);
  }

  // --- 3. NASA imagery from /tiles/, and nothing leaves the stack (GFX-01, GFX-02) --------------
  const imagery = page.waitForResponse((r) => r.url().includes("/tiles/earth-day.pmtiles") && r.ok());
  await page.goto("/operations");
  const tile = await imagery;
  expect(new URL(tile.url()).origin).toBe(new URL(page.url()).origin);
  await expect(page.locator(".maplibregl-ctrl-attrib")).toContainText("Imagery: NASA");

  // --- 4. Nothing outside the globe's disc (GFX-04) ---------------------------------------------
  for (const [route, testId] of [
    ["/operations", "operations-map"],
    ["/air", "air-map"],
  ] as const) {
    if (route !== "/operations") await page.goto(route);
    await expect(page.getByTestId(testId)).toBeVisible();
    await page.waitForTimeout(5000); // tiles, the starting view and the sweep
    const edge = await outsideTheDisc(page, testId);
    console.log("disc", route, JSON.stringify(edge));
    expect(edge, `${route}: the globe's rim is found`).not.toBeNull();
    if (!edge) continue;
    expect(edge.stretches, `${route}: space on both sides`).toBeGreaterThan(4);
    expect(Math.max(...edge.space), `${route}: the space is dark`).toBeLessThanOrEqual(48);
    expect(edge.worst, `${route}: something drawn outside the disc`).toBeLessThanOrEqual(12);
    if (route === "/operations") {
      // The radar sweep, the band this requirement was written for, is clipped to the rim.
      const clip = await page.locator(".nx-mapwrap").evaluate((e) => getComputedStyle(e, "::after").clipPath);
      expect(clip, "the sweep is clipped to the globe").toMatch(/^circle\(/);
    }
  }

  // --- 5. After scene 1, the mini-map shows the incident and opens Global Operations (GFX-08) ---
  await page.getByRole("toolbar", { name: "Presenter" }).getByRole("button", { name: "Next scene" }).click();
  const year = new Date().getFullYear();
  const incident = await until(
    async () => (await duty.get<Incident[]>("/api/incidents?status=ACTIVE")).find((i) => i.reference === `INC-${year}-1042`),
    "INC-1042 after scene 1",
  );
  await page.goto(`/incidents?id=${incident.id}`);
  const mini = page.getByTestId("mini-map");
  await expect(mini.locator("canvas")).toBeVisible();
  await page.waitForTimeout(3000); // tiles and the layers' data
  const box = await mini.boundingBox();
  expect(box).not.toBeNull();
  if (!box) return;
  const centre = { x: Math.round(box.x + box.width / 2) - 1, y: Math.round(box.y + box.height / 2) - 1, width: 3, height: 3 };
  const shot = (await page.screenshot({ clip: centre })).toString("base64");
  const colour = await page.evaluate(async (shot) => {
    const img = new Image();
    img.src = `data:image/png;base64,${shot}`;
    await img.decode();
    const canvas = document.createElement("canvas");
    canvas.width = img.width;
    canvas.height = img.height;
    const ctx = canvas.getContext("2d");
    ctx?.drawImage(img, 0, 0);
    return Array.from(ctx?.getImageData(1, 1, 1, 1).data.slice(0, 3) ?? []);
  }, shot);
  const want = rgb(SEVERITY_COLOUR[incident.severity]);
  console.log("marker", JSON.stringify({ colour, want }));
  expect(
    colour.reduce((sum, v, i) => sum + Math.abs(v - (want[i] ?? 0)), 0),
    "the incident's marker at the centre",
  ).toBeLessThanOrEqual(30);
  await page.getByRole("button", { name: `Open ${incident.reference} in Global Operations` }).click();
  await expect(page).toHaveURL(new RegExp(`/operations\\?incident=${incident.id}$`));
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Global Operations");

  await page.context().close();
  expect(leaving, "requests that left the stack").toEqual([]);
  expect(cspViolations).toEqual([]);
});
