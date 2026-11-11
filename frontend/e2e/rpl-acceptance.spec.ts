import { expect, type Page, test } from "@playwright/test";

import { API, as, cspViolations, KEYCLOAK, PASSWORD, signedIn } from "./support";

// Incident Replay acceptance (Prompt 126; requirements-pilot.md §102, D-51; plan-pilot-rpl §6) on
// the real stack. `make acceptance` runs it after the After-Action Review spec, which leaves
// INC-<year>-1042 at MONITORING with AAR-<year>-1042 open on it. It only reads: it opens the
// replay from the incident and the review, checks the start and the end of the window against
// the Incidents and Safety Check-in screens, scrubs to the first check-in answer, follows a link
// with &t=, and checks that no name appears and no request leaves the stack.

interface Answer {
  at: string;
  status: "SAFE" | "NEED_HELP";
}
interface Replay {
  window: { start: string; end: string };
  incident: { id: string; reference: string; status: string; opened_at: string };
  signals: { received_at: string }[];
  people: { exposed_at: string }[];
  checkin: {
    reference: string;
    sent_at: string | null;
    personnel: Answer[][];
    tally_end: { safe: number; need_help: number; pending: number };
  } | null;
  timeline: { at: string; source: string; text: string }[];
  annotations: { kind: string; symbol: string | null; until: string | null }[];
}

const year = new Date().getUTCFullYear();
const INCIDENT = `INC-${year}-1042`;
const REVIEW = `AAR-${year}-1042`;
// Seeded people and demo users (simulated); none may appear on the replay (RPL-05).
const NAMES = [
  "Peter Mwangi",
  "Hana Takeda",
  "Grace Wanjiru",
  "Omar Siddiqui",
  "Elena Costa",
  "Layla Haddad",
  "Daniel Mercer",
  "Martin Keller",
  "James Otieno",
];

const ms = (iso: string) => Date.parse(iso);
const kpi = (page: Page, label: string) => page.locator(".nx-kpi", { hasText: label }).locator(".v");

/** The personnel tally at t from the payload, as "safe / needs help / waiting" (RPL-04). */
function tallyAt(r: Replay, t: number): string {
  const counts = { SAFE: 0, NEED_HELP: 0, WAITING: 0 };
  for (const answers of r.checkin?.personnel ?? []) {
    const latest = answers.filter((a) => ms(a.at) <= t).at(-1);
    counts[latest?.status ?? "WAITING"] += 1;
  }
  return `${counts.SAFE} / ${counts.NEED_HELP} / ${counts.WAITING}`;
}

async function noNames(page: Page, who: string) {
  const text = (await page.locator(".nx-rpl-page").textContent()) ?? "";
  for (const name of NAMES) expect(text, `${who}: ${name}`).not.toContain(name);
}

test("Incident Replay acceptance: opens, start and end of the window, scrub, no names, link", async ({
  browser,
  request,
}) => {
  test.skip(!PASSWORD, "DEMO_USER_PASSWORD is not set (run through `make acceptance`)");
  test.setTimeout(180_000);
  const duty = await as(request, "duty.officer");
  const incident = (await duty.get<{ id: string; reference: string; status: string }[]>("/api/incidents")).find(
    (i) => i.reference === INCIDENT,
  );
  expect(incident?.status, "run after the After-Action Review spec").toBe("MONITORING");
  if (!incident) return;
  const replay = await duty.get<Replay>(`/api/incidents/${incident.id}/replay`);
  const body = JSON.stringify(replay);
  // ANN-06 (Prompt 133): the map spec's checkpoint (withdrawn) and area are on the replay, by
  // kind only: no label, no reason (plan-pilot-map G-4).
  expect(replay.annotations.map((a) => [a.kind, a.symbol, a.until !== null])).toEqual(
    expect.arrayContaining([
      ["MARK", "CHECKPOINT", true],
      ["AREA", null, false],
    ]),
  );
  const marks = replay.timeline.filter((e) => e.source === "ANNOTATION").map((e) => e.text);
  expect(marks).toEqual(
    expect.arrayContaining([
      "Map annotation added: Checkpoint.",
      "Map annotation added: Area.",
      "Map annotation withdrawn: Checkpoint.",
    ]),
  );
  for (const text of ["Uhuru Highway", "crowd at the CBD", "Cleared by police"]) expect(body).not.toContain(text);
  for (const name of NAMES) expect(body, name).not.toContain(name);
  const start = ms(replay.window.start);
  const end = ms(replay.window.end);
  const at = (t: number) => `/incidents/replay?id=${incident.id}&t=${Math.round((t - start) / 1000)}`;

  // Every request the browsers make stays on the stack (D-24, AGENTS.md).
  const hosts = new Set<string>();
  const watch = (page: Page) => page.on("request", (r) => hosts.add(new URL(r.url()).host));

  // --- 1. Opens from the incident detail and from the review (RPL-06) -------------------------
  const page = await signedIn(browser, "duty.officer", `/incidents?id=${incident.id}`);
  watch(page);
  const exposed = page.locator(".nx-istat > div", { hasText: "People" }).locator("b").first();
  await expect(exposed).toHaveText("229"); // the Incidents screen's figure, for the end below
  await page.getByRole("button", { name: "Replay", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/incidents/replay\\?id=${incident.id}`));
  await expect(page.locator(".nx-rpl-head")).toContainText(INCIDENT);
  await expect(page.getByText("Positions as now; the platform keeps no location history")).toBeVisible();
  await noNames(page, "duty.officer");

  const review = (await duty.get<{ reviews: { id: string; reference: string; incident_id: string }[] }>("/api/aar")).reviews.find(
    (r) => r.reference === REVIEW,
  );
  expect(review?.incident_id).toBe(incident.id);
  await page.goto(`/aar?review=${review?.id}`);
  await page.getByRole("button", { name: "Replay", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/incidents/replay\\?id=${incident.id}`));
  await expect(page.locator(".nx-rpl-head")).toContainText(INCIDENT);

  // --- 2. The start of the window: the first signal only, no people, no check-in (RPL-02, -04) -
  expect(replay.signals.filter((s) => ms(s.received_at) <= start)).toHaveLength(1);
  expect(replay.people.filter((p) => ms(p.exposed_at) <= start)).toHaveLength(0);
  await page.goto(at(start));
  await expect(page.getByRole("slider", { name: "Moment" })).toHaveValue("0");
  await expect(page.getByLabel("Elapsed")).toHaveText("+0:00");
  await expect(kpi(page, "Signals")).toHaveText("1");
  await expect(kpi(page, "People exposed")).toHaveText("0");
  await expect(kpi(page, "Check-in · personnel")).toHaveText("—");

  // --- 3. The end: 229 exposed, 15 / 1 / 1, as the Incidents and Safety Check-in screens -------
  const checkin = replay.checkin;
  expect(checkin?.tally_end).toMatchObject({ safe: 15, need_help: 1, pending: 1 });
  await page.goto(at(end + 1000)); // past the end opens at the end
  await expect(kpi(page, "Signals")).toHaveText(String(replay.signals.length));
  await expect(kpi(page, "People exposed")).toHaveText("229");
  await expect(kpi(page, "Check-in · personnel")).toHaveText("15 / 1 / 1");
  const campaign = (await duty.get<{ id: string; reference: string }[]>(`/api/campaigns?incident_id=${incident.id}`)).find(
    (c) => c.reference === checkin?.reference,
  );
  const screen = await signedIn(browser, "duty.officer", `/checkin?campaign=${campaign?.id}`);
  watch(screen);
  const figures = screen.getByLabel("Personnel figures");
  await expect(figures.locator(".nx-kpi", { hasText: "Safe" }).locator(".v")).toHaveText("15");
  await expect(figures.locator(".nx-kpi", { hasText: "Need help" }).locator(".v")).toHaveText("1");
  await expect(figures.locator(".nx-kpi", { hasText: "No response" }).locator(".v")).toHaveText("1");
  await screen.context().close();

  // --- 4. Scrub to the first answer: the answers given by then and no later ones (RPL-03) -----
  const first = replay.timeline.find((e) => e.source === "CHECKIN" && e.text.endsWith("a person needs help."));
  expect(first, "a check-in answer on the timeline").toBeTruthy();
  const t = ms(first?.at ?? "");
  const then = tallyAt(replay, t);
  expect(then).not.toBe("15 / 1 / 1");
  await page.getByRole("button", { name: /a person needs help\.$/ }).first().click();
  await expect(kpi(page, "Check-in · personnel")).toHaveText(then);
  await expect(page.getByLabel("Replay timeline").locator(".current")).toContainText("a person needs help.");
  const later = replay.timeline.filter((e) => ms(e.at) > t).length;
  await expect(page.getByLabel("Replay timeline").locator(".ahead")).toHaveCount(later);
  await expect(page).toHaveURL(/&t=\d+$/);
  const link = new URL(page.url());
  await page.context().close();

  // --- 5. The link opens at that moment, for the Viewer, with no names (RPL-05, RPL-07) -------
  const seconds = Number(link.searchParams.get("t"));
  const viewer = await signedIn(browser, "viewer", `${link.pathname}${link.search}`);
  watch(viewer);
  await expect(viewer.getByLabel("Elapsed")).toHaveText(`+${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`);
  await expect(kpi(viewer, "Check-in · personnel")).toHaveText(tallyAt(replay, start + seconds * 1000));
  await expect(kpi(viewer, "People exposed")).toHaveText("229");
  await noNames(viewer, "viewer");
  await viewer.context().close();

  // --- 6. Nothing left the stack ----------------------------------------------------------------
  const stack = new Set([new URL(API).host, new URL(KEYCLOAK).host]);
  const outside = [...hosts].filter((h) => !stack.has(h) && !/^(localhost|127\.0\.0\.1)(:\d+)?$/.test(h));
  expect(outside, "requests outside the stack").toEqual([]);
  expect(cspViolations).toEqual([]);
});
