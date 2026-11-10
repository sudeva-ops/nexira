import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { Exercise, Exercises, ExerciseSummary, Template } from "../../api/exercises";
import { DETAIL, INCIDENT, VIEWER } from "../../test/fixtures";
import { DUTY_OFFICER, mockServer, type Reply, renderApp } from "../../test/render";
import { measuredText } from "./format";

const NOW = new Date().toISOString();
const summary = (id: string, extra: Partial<ExerciseSummary> = {}): ExerciseSummary => ({
  id,
  name: "Civil unrest drill",
  kind: "TABLETOP",
  status: "COMPLETED",
  source: "ILLUSTRATIVE",
  mission_id: "m-nbo",
  mission_code: "NBO",
  scenario_code: null,
  incident_id: null,
  incident_reference: null,
  overall_score: 79,
  participants: 14,
  started_at: "2026-10-19T08:00:00Z",
  ended_at: "2026-10-19T10:00:00Z",
  ...extra,
});

const DONE: Exercise = {
  ...summary("x-done", {
    name: "Nairobi civil unrest",
    kind: "FUNCTIONAL",
    source: "EXERCISE",
    scenario_code: "NBO-CIVIL-UNREST",
    incident_id: "inc-1042",
    incident_reference: "INC-2026-1042",
    overall_score: 99,
    participants: 16,
    ended_at: NOW,
  }),
  reason: null,
  run: null,
  can_act: false,
  scores: [
    { dimension: "DETECTION", score: 100, measured: { seconds: 105.65, target_s: 120 } },
    {
      dimension: "ACCOUNTABILITY",
      score: 94,
      measured: { answered: 16, asked: 17, campaign: "NTF-3103" },
    },
    { dimension: "DECISION_SPEED", score: 100, measured: { within: 6, decisions: 6, target_s: 300 } },
    {
      dimension: "COMMUNICATION",
      score: 100,
      measured: { reached: 229, exposed: 229, simulated_delivery: true },
    },
    { dimension: "PLAN_ADHERENCE", score: 100, measured: { done: 8, steps: 8 } },
  ],
};

const RUNNING: Exercise = {
  ...summary("x-run", {
    name: "Nairobi civil unrest",
    kind: "FUNCTIONAL",
    status: "RUNNING",
    source: "EXERCISE",
    scenario_code: "NBO-CIVIL-UNREST",
    overall_score: null,
    participants: null,
    started_at: NOW,
    ended_at: null,
  }),
  reason: null,
  scores: [],
  can_act: true,
  run: {
    status: "PAUSED",
    current_scene: 1,
    scenes: [
      { scene_no: 0, name: "Calm" },
      { scene_no: 1, name: "Signals" },
      { scene_no: 2, name: "Impact" },
    ],
  },
};

const ILLUSTRATIVE: Exercise = {
  ...summary("x-paris", { mission_code: "PAR", overall_score: 72 }),
  reason: null,
  run: null,
  can_act: false,
  scores: [
    { dimension: "DETECTION", score: 74, measured: { illustrative: true } },
    { dimension: "ACCOUNTABILITY", score: 71, measured: { illustrative: true } },
    { dimension: "DECISION_SPEED", score: 73, measured: { illustrative: true } },
    { dimension: "COMMUNICATION", score: 69, measured: { illustrative: true } },
    { dimension: "PLAN_ADHERENCE", score: 73, measured: { illustrative: true } },
  ],
};

const LIST: Exercises = {
  kpis: { this_year: 37, average: 84, average_last_year: null, took_part: 1104, personnel: 1338, templates: 4 },
  exercises: [DONE, ILLUSTRATIVE],
};

const template = (code: string, mission: string, theme: string, extra: Partial<Template> = {}): Template => ({
  code,
  name: `${mission} scenario`,
  mission_id: `m-${mission}`,
  mission_code: mission,
  theme,
  scenes: 6,
  running: false,
  can_launch: true,
  ...extra,
});
const TEMPLATES = [
  template("NBO-CIVIL-UNREST", "NBO", "Civil unrest"),
  template("DAC-CYCLONE", "DAC", "Natural hazard"),
];

function setup(me = DUTY_OFFICER, extra: Record<string, Reply> = {}) {
  return mockServer({
    "GET /api/me": { body: me },
    "GET /api/proposals": { body: [] },
    "GET /api/exercises": { body: LIST },
    "GET /api/exercises/templates": { body: TEMPLATES },
    "GET /api/exercises/running": { body: [] },
    "GET /api/exercises/x-done": { body: DONE },
    "GET /api/exercises/x-paris": { body: ILLUSTRATIVE },
    ...extra,
  });
}

const posts = (fetchMock: ReturnType<typeof setup>) =>
  fetchMock.mock.calls
    .filter(([, init]) => init?.method === "POST")
    .map(([url, init]) => [String(url), init?.body]);

afterEach(() => vi.unstubAllGlobals());

describe("Exercise & Training", () => {
  it("shows the KPIs, the recent exercises and the last one's scoring breakdown", async () => {
    setup();
    renderApp("/exercises");
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Exercise & Training");
    const figures = await screen.findByLabelText("Exercise figures");
    expect(figures).toHaveTextContent("84 / 100");
    expect(figures).toHaveTextContent(`— vs ${new Date().getFullYear() - 1}`);
    expect(figures).toHaveTextContent("1,104");
    expect(figures).toHaveTextContent("83% of personnel");
    expect(await within(figures).findByText("Civil unrest · Natural hazard")).toBeInTheDocument();

    const table = screen.getByRole("table", { name: "Recent exercises" });
    const paris = table.querySelector('[data-exercise="x-paris"]') as HTMLElement;
    expect(paris).toHaveTextContent("Illustrative");
    expect(paris).toHaveTextContent("19 Oct 2026"); // the date alone, never a cut-off time
    expect(paris.querySelector(".nx-bar > i")).toHaveClass("warn"); // 72: amber below 80
    expect(table.querySelector('[data-exercise="x-done"] .nx-bar > i')).not.toHaveClass("warn");

    const breakdown = await screen.findByLabelText("Scoring breakdown");
    const row = (d: string) => breakdown.querySelector(`[data-dimension="${d}"]`);
    expect(row("DETECTION")).toHaveTextContent("Detection → alert100");
    expect(row("DETECTION")).toHaveTextContent("1m 46s · target 2m 00s");
    expect(row("ACCOUNTABILITY")).toHaveTextContent("16 of 17 answered · NTF-3103");
    expect(row("COMMUNICATION")).toHaveTextContent("229 of 229 exposed reached · simulated delivery");
    expect(row("OVERALL")).toHaveTextContent("Overall99");
    expect(breakdown).toHaveTextContent("INC-2026-1042 · 16 took part");
  });

  it("selects an illustrative exercise and labels its breakdown", async () => {
    setup();
    renderApp("/exercises");
    const table = await screen.findByRole("table", { name: "Recent exercises" });
    await userEvent.click(table.querySelector('[data-exercise="x-paris"]') as HTMLElement);
    const breakdown = await screen.findByLabelText("Scoring breakdown");
    expect(await within(breakdown).findByText(/Illustrative: seeded history/)).toBeInTheDocument();
    expect(breakdown.querySelector('[data-dimension="DETECTION"]')).toHaveTextContent("Illustrative");
  });

  it("launches an exercise from a template and a kind", async () => {
    const fetchMock = setup(DUTY_OFFICER, { "POST /api/exercises": { status: 201, body: RUNNING } });
    renderApp("/exercises");
    const form = await screen.findByLabelText("Launch an exercise");
    await userEvent.selectOptions(within(form).getByLabelText("Template"), "DAC-CYCLONE");
    await userEvent.selectOptions(within(form).getByLabelText("Kind"), "FULL_SCALE");
    await userEvent.click(within(form).getByRole("button", { name: "Launch" }));
    expect(posts(fetchMock)).toEqual([
      ["/api/exercises", JSON.stringify({ template: "DAC-CYCLONE", kind: "FULL_SCALE" })],
    ]);
  });

  it("plays, ends and abandons a running exercise, never showing a scene's expected result", async () => {
    const fetchMock = setup(DUTY_OFFICER, {
      "GET /api/exercises": { body: { ...LIST, exercises: [RUNNING, DONE] } },
      "GET /api/exercises/x-run": { body: RUNNING },
      "POST /api/exercises/x-run/next": { body: RUNNING },
      "POST /api/exercises/x-run/end": { body: DONE },
      "POST /api/exercises/x-run/abandon": { body: { ...RUNNING, status: "ABANDONED" } },
    });
    renderApp("/exercises");
    const controls = await screen.findByLabelText("Running exercise");
    expect(within(controls).getByLabelText("Current scene")).toHaveTextContent("Scene 1 of 2 · Signals");
    expect(await screen.findByText("Scored from the record when the exercise ends.")).toBeInTheDocument();
    await userEvent.click(within(controls).getByRole("button", { name: "Next inject" }));
    await userEvent.click(within(controls).getByRole("button", { name: "Abandon" }));
    const confirm = within(controls).getByRole("button", { name: "Confirm" });
    expect(confirm).toBeDisabled(); // a reason first
    await userEvent.type(within(controls).getByLabelText("Reason"), "Called off");
    await userEvent.click(confirm);
    await userEvent.click(within(controls).getByRole("button", { name: "End exercise" }));
    expect(posts(fetchMock)).toEqual([
      ["/api/exercises/x-run/next", "{}"],
      ["/api/exercises/x-run/abandon", JSON.stringify({ reason: "Called off" })],
      ["/api/exercises/x-run/end", "{}"],
    ]);
  });

  it("lets the Viewer read and nothing more", async () => {
    setup(VIEWER, {
      "GET /api/exercises": { body: { ...LIST, exercises: [RUNNING, DONE] } },
      "GET /api/exercises/x-run": { body: { ...RUNNING, can_act: false } },
      "GET /api/exercises/templates": { body: TEMPLATES.map((t) => ({ ...t, can_launch: false })) },
    });
    renderApp("/exercises");
    const controls = await screen.findByLabelText("Running exercise");
    expect(within(controls).getByLabelText("Current scene")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Launch|Next inject|End exercise|Abandon/ })).toBeNull();
    expect(screen.queryByLabelText("Launch an exercise")).toBeNull();
  });

  it("shows the SIMULATED EXERCISE banner on every screen while one runs", async () => {
    setup(DUTY_OFFICER, {
      "GET /api/exercises/running": { body: [RUNNING] },
      "GET /api/incidents": { body: [{ ...INCIDENT, exercise: true }] },
      [`GET /api/incidents/${INCIDENT.id}`]: { body: { ...DETAIL, exercise: true } },
    });
    renderApp("/incidents");
    expect(await screen.findByLabelText("Exercise running")).toHaveTextContent(
      "SIMULATED EXERCISE · Nairobi civil unrest (NBO)",
    );
    const register = await screen.findByRole("table", { name: "Incident register" });
    expect(within(register).getByLabelText("Exercise")).toHaveTextContent("EXERCISE");
  });
});

describe("measuredText", () => {
  it("states each figure, or what is missing", () => {
    expect(measuredText({ dimension: "DETECTION", score: null, measured: {} })).toBe("No notification sent");
    expect(measuredText({ dimension: "ACCOUNTABILITY", score: null, measured: {} })).toBe("No check-in");
    expect(
      measuredText({ dimension: "DECISION_SPEED", score: 83, measured: { within: 5, decisions: 6, target_s: 300 } }),
    ).toBe("5 of 6 within 5m 00s");
    expect(measuredText({ dimension: "DECISION_SPEED", score: null, measured: { within: 0, decisions: 0 } })).toBe(
      "No decision",
    );
    expect(measuredText({ dimension: "COMMUNICATION", score: null, measured: { reached: 0, exposed: 0 } })).toBe(
      "Nobody exposed",
    );
    expect(measuredText({ dimension: "PLAN_ADHERENCE", score: null, measured: {} })).toBe("No playbook run");
  });
});
