import { expect, type Page, test } from "@playwright/test";

import { SCREENS } from "../src/app/screens";
import { cspViolations, PASSWORD, signedIn } from "./support";

// UI polish acceptance (Prompt 141; requirements-pilot.md §124, D-54; plan-pilot-uip G-4) on the
// real stack. Every screen the Duty Officer has in the sidebar, at 1440 × 900 and 1920 × 1080:
// no horizontal page scroll, no panel header button on two lines, and no text cut with an
// ellipsis without its full text in a title. Then the specific cases: the Incidents header
// buttons, the Safety Check-in names, and the Air Travel globe inside its map box.

const SIZES = [
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
];
// The Duty Officer's sidebar: no VIP (VIP-06) and no Audit (UIP-07).
const ROUTES = SCREENS.filter((s) => !s.restricted).map((s) => s.path);
const MAPS = new Set(["/operations", "/air"]);

interface Problems {
  scroll: number;
  wrapped: string[];
  cut: string[];
}

async function problems(page: Page): Promise<Problems> {
  return page.evaluate(() => {
    const doc = document.documentElement;
    const describe = (e: Element) =>
      `${e.tagName.toLowerCase()}.${Array.from(e.classList).join(".")} "${(e.textContent ?? "").trim().slice(0, 40)}"`;
    const wrapped = Array.from(document.querySelectorAll(".nx-card-hd .bp6-button"))
      .filter((b) => b.getBoundingClientRect().height > 32)
      .map(describe);
    const cut = Array.from(document.querySelectorAll("body *"))
      .filter((e): e is HTMLElement => e instanceof HTMLElement && e.offsetParent !== null)
      .filter((e) => getComputedStyle(e).textOverflow === "ellipsis" && e.scrollWidth > e.clientWidth + 1)
      .filter((e) => !e.closest("[title]"))
      .map(describe);
    return { scroll: doc.scrollWidth - doc.clientWidth, wrapped, cut };
  });
}

/** The share of a row across the map's middle that differs from the space at its left end. */
async function covered(page: Page, box: { x: number; y: number; width: number; height: number }, y: number) {
  const shot = (await page.screenshot({ clip: box })).toString("base64");
  return page.evaluate(
    async ({ shot, y }) => {
      const img = new Image();
      img.src = `data:image/png;base64,${shot}`;
      await img.decode();
      const canvas = document.createElement("canvas");
      canvas.width = img.width;
      canvas.height = img.height;
      const ctx = canvas.getContext("2d");
      if (!ctx) return 1;
      ctx.drawImage(img, 0, 0);
      const row = Math.round(y < 0 ? img.height + y : y);
      const px = (x: number) => Array.from(ctx.getImageData(x, row, 1, 1).data.slice(0, 3));
      const space = px(Math.round(img.width * 0.02));
      // Clear of the search box (top left) and the globe/flat switch and attribution (right).
      const from = Math.round(img.width * 0.5);
      const to = Math.round(img.width * 0.65);
      let differ = 0;
      for (let x = from; x < to; x += 1) {
        const p = px(x);
        if (p.reduce((sum, v, i) => sum + Math.abs(v - (space[i] ?? 0)), 0) > 24) differ += 1;
      }
      return differ / (to - from);
    },
    { shot, y },
  );
}

test("UI polish: every screen at two sizes, and the specific cases", async ({ browser }) => {
  test.skip(!PASSWORD, "DEMO_USER_PASSWORD is not set (run through `make acceptance`)");
  test.setTimeout(10 * 60_000);
  const page = await signedIn(browser, "duty.officer", "/");
  expect(ROUTES.length, "the Duty Officer's screens").toBeGreaterThan(20);

  // --- 1. Every screen, at both sizes (UIP-02, UIP-03) ------------------------------------------
  const found: string[] = [];
  for (const size of SIZES) {
    await page.setViewportSize(size);
    for (const route of ROUTES) {
      await page.goto(route);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await page.waitForTimeout(MAPS.has(route) ? 4000 : 2000); // the screen's first data
      const p = await problems(page);
      const at = `${route} @ ${size.width}×${size.height}`;
      if (p.scroll > 0) found.push(`${at}: page scrolls sideways by ${p.scroll}px`);
      for (const w of p.wrapped) found.push(`${at}: header button on two lines: ${w}`);
      for (const c of p.cut) found.push(`${at}: cut without a title: ${c}`);
    }
  }
  expect(found, found.join("\n")).toEqual([]);
  await page.setViewportSize(SIZES[0] as (typeof SIZES)[0]);

  // --- 2. Incidents: the header buttons in line, on one line (UIP-02) ---------------------------
  await page.goto("/incidents");
  await page.getByRole("row").filter({ hasText: "Civil unrest" }).first().click();
  const replay = page.getByRole("button", { name: "Replay" });
  await expect(replay).toBeVisible();
  const next = page.locator(".nx-card-actions .bp6-button").last();
  const [a, b] = [await replay.boundingBox(), await next.boundingBox()];
  expect(a && b && Math.abs(a.y - b.y) <= 1 && Math.abs(a.height - b.height) <= 1, "in line, same height").toBe(true);

  // --- 3. Safety Check-in: each name on one line (UIP-05) ---------------------------------------
  await page.goto("/checkin");
  const names = page.getByLabel("Live responses").locator(".nx-pp .n");
  await expect(names.first()).toBeVisible();
  for (const name of await names.all()) {
    const box = await name.boundingBox();
    expect(box?.height ?? 99, (await name.textContent()) ?? "").toBeLessThanOrEqual(20);
  }

  // --- 4. Air Travel: the globe inside its map box (UIP-08) -------------------------------------
  await page.goto("/air");
  const map = page.getByTestId("air-map");
  await expect(map).toBeVisible();
  await page.waitForTimeout(5000); // tiles and the starting view
  const box = await map.boundingBox();
  expect(box).not.toBeNull();
  if (!box) return;
  for (const y of [3, -3]) {
    expect(await covered(page, box, y), `globe at the ${y > 0 ? "top" : "bottom"} edge`).toBeLessThan(0.5);
  }
  await page.context().close();
  expect(cspViolations).toEqual([]);
});
