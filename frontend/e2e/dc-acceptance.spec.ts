import { expect, type Page, test } from "@playwright/test";

import { SCREENS } from "../src/app/screens";
import { cspViolations, PASSWORD, signedIn } from "./support";

// Design consistency acceptance (Prompt 150; requirements-pilot.md §134, D-56; plan-pilot-dc) on
// the real stack. `make acceptance` runs it straight after gfx-acceptance: a fresh reset and
// scene 1 only, so Safety Check-in and After-Action Review are still at rest. Every screen in
// the Administrator's sidebar (Audit included; VIP is not in it, VIP-06), at 1440 × 900:
// - DC-01: the six screens this module gave a tile row have one, of 4 or 5 tiles;
// - DC-03: no page-filling empty state, unless the screen cannot work (no access, an error);
// - DC-04: once loaded, no spinner outside a button or dialog;
// - DC-07: no sentence in the monospace font;
// - DC-05: at most one chip in a card header.

const ROUTES = SCREENS.filter((s) => s.restricted !== "vip").map((s) => s.path);
const TILE_ROWS = ["/incidents", "/playbooks", "/predictive", "/audit", "/checkin", "/aar"];
const MAPS = new Set(["/operations", "/air"]);

interface Found {
  tiles: number;
  pageEmpty: string[];
  spinners: number;
  monoSentences: string[];
  chips: string[];
}

async function inspect(page: Page): Promise<Found> {
  return page.evaluate(() => {
    const visible = (e: Element) => e instanceof HTMLElement && e.offsetParent !== null;
    // DC-03: a whole-page empty state, unless it says the screen cannot work (G-6).
    const cannotWork = /only|restricted|not found|could not|no access/i;
    const pageEmpty = Array.from(document.querySelectorAll(".bp6-non-ideal-state"))
      .filter(visible)
      .filter((e) => !e.closest(".nx-card")) // inside a panel it fills the panel, not the page
      .map((e) => (e.textContent ?? "").trim().slice(0, 80))
      .filter((text) => !cannotWork.test(text));
    // DC-04: spinners outside a button or dialog.
    const spinners = Array.from(document.querySelectorAll(".bp6-spinner"))
      .filter(visible)
      .filter((e) => !e.closest(".bp6-button, .bp6-dialog, .bp6-overlay")).length;
    // DC-07: an element in the monospace font whose own text reads as a sentence: four or more
    // words, three of them lower-case words (codes, references, times and figures are not).
    const monoSentences: string[] = [];
    for (const e of Array.from(document.querySelectorAll(".nx-view *"))) {
      if (!visible(e) || !/monospace|Consolas/i.test(getComputedStyle(e).fontFamily)) continue;
      const own = Array.from(e.childNodes)
        .filter((n) => n.nodeType === Node.TEXT_NODE)
        .map((n) => n.textContent ?? "")
        .join(" ")
        .trim();
      const words = own.split(/\s+/).filter(Boolean);
      if (words.length >= 4 && words.filter((w) => /^[a-z][a-z'’]+[.,;:]?$/.test(w)).length >= 3) {
        monoSentences.push(`${e.tagName.toLowerCase()}.${Array.from(e.classList).join(".")} "${own.slice(0, 60)}"`);
      }
    }
    // DC-05: one chip per card header at most.
    const chips = Array.from(document.querySelectorAll(".nx-card-hd"))
      .filter((h) => h.querySelectorAll(".nx-chip").length > 1)
      .map((h) => (h.querySelector("h3")?.textContent ?? "").trim());
    return {
      tiles: document.querySelectorAll(".nx-tiles .nx-kpi").length,
      pageEmpty,
      spinners,
      monoSentences,
      chips,
    };
  });
}

test("Design consistency: tile rows, one empty and loading state, monospace for data, one chip", async ({
  browser,
}) => {
  test.skip(!PASSWORD, "DEMO_USER_PASSWORD is not set (run through `make acceptance`)");
  test.setTimeout(8 * 60_000);
  const page = await signedIn(browser, "admin", "/");
  expect(ROUTES).toContain("/audit");
  expect(ROUTES.length, "the Administrator's screens").toBeGreaterThan(20);

  const problems: string[] = [];
  for (const route of ROUTES) {
    await page.goto(route);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    // Loaded: no skeleton left (or 10 s), then the maps' first draw.
    await page
      .waitForFunction(() => document.querySelectorAll(".nx-view .bp6-skeleton").length === 0, undefined, {
        timeout: 10_000,
      })
      .catch(() => problems.push(`${route}: still loading after 10 s`));
    await page.waitForTimeout(MAPS.has(route) ? 3000 : 1000);
    const f = await inspect(page);
    console.log("dc", route, JSON.stringify({ tiles: f.tiles, spinners: f.spinners }));
    if (TILE_ROWS.includes(route) && (f.tiles < 4 || f.tiles > 5)) problems.push(`${route}: ${f.tiles} tiles, not 4 or 5`);
    for (const e of f.pageEmpty) problems.push(`${route}: page-filling empty state "${e}"`);
    if (f.spinners) problems.push(`${route}: ${f.spinners} spinner(s) once loaded`);
    for (const m of f.monoSentences) problems.push(`${route}: a sentence in monospace: ${m}`);
    for (const c of f.chips) problems.push(`${route}: more than one chip in "${c}"`);
  }
  expect(problems, problems.join("\n")).toEqual([]);
  await page.context().close();
  expect(cspViolations).toEqual([]);
});
