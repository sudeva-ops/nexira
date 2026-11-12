import { describe, expect, it } from "vitest";

import type { AuditEntry } from "../api/audit";
import type { Reviews, ReviewSummary } from "../api/aar";
import type { ExerciseSummary } from "../api/exercises";
import type { Incident } from "../api/intel";
import type { PlaybookRun } from "../api/playbooks";
import type { PredictiveOverview } from "../api/predictive";
import {
  auditFigures,
  countOf,
  exerciseMonths,
  incidentFigures,
  playbookFigures,
  predictiveFigures,
  reviewFigures,
} from "./figures";

const NOW = Date.parse("2026-11-12T12:00:00Z");
const ago = (h: number) => new Date(NOW - h * 3_600_000).toISOString();

describe("countOf (DC-01)", () => {
  it("says 200+ only when the whole page is inside the window", () => {
    expect(countOf(37, 200, 200)).toBe("37");
    expect(countOf(200, 200, 200)).toBe("200+");
    expect(countOf(12, 12, 200)).toBe("12");
  });
});

describe("incidentFigures (G-1)", () => {
  const inc = (over: Partial<Incident>) =>
    ({ status: "ACTIVE", severity: "HIGH", opened_at: ago(1), signal_count: 2, sources: [{ code: "DMR" }], ...over }) as Incident;
  it("counts active and monitoring, the worst severity, signals and sources, exercises apart", () => {
    const f = incidentFigures(
      [
        inc({ severity: "CRITICAL", sources: [{ code: "DMR" }, { code: "MAX" }] as Incident["sources"] }),
        inc({ severity: "MODERATE", signal_count: 1 }),
        inc({ status: "MONITORING", opened_at: ago(24 * 40) }),
        inc({ exercise: true, severity: "CRITICAL" }),
      ],
      NOW,
    );
    expect(f).toEqual({ active: 2, highest: "CRITICAL", monitoring: 1, opened30: 2, signals: 3, sources: 2, exercise: 1 });
  });
  it("has no highest severity with nothing active", () => {
    expect(incidentFigures([], NOW).highest).toBeNull();
  });
});

describe("playbookFigures (G-2)", () => {
  const run = (over: Partial<PlaybookRun>) =>
    ({ status: "COMPLETED", started_at: ago(2), started_by_type: "USER", steps: [], ...over }) as unknown as PlaybookRun;
  it("counts live runs, armed ones, runs at a gate and runs in 30 days", () => {
    const f = playbookFigures(
      [
        run({ status: "RUNNING", started_by_type: "AGENT", steps: [{ status: "AWAITING_APPROVAL" }] as PlaybookRun["steps"] }),
        run({ status: "SCHEDULED" }),
        run({}),
        run({ started_at: ago(24 * 31) }),
      ],
      NOW,
    );
    expect(f).toEqual({ active: 2, armed: 1, atGate: 1, runs30: "3", byAgent: 1 });
  });
});

describe("predictiveFigures (G-3)", () => {
  it("counts missions whose forecast goes up, threshold crossings and the highest peak", () => {
    const o = {
      threshold: 70,
      rising: [
        { mission_code: "BGW", peak: 62, change: 12, crosses: false },
        { mission_code: "NBO", peak: 81, change: 5, crosses: true },
        { mission_code: "OSL", peak: 20, change: -3, crosses: false },
      ],
    } as PredictiveOverview;
    const f = predictiveFigures(o);
    expect([f.rising, f.crossing, f.top?.mission_code]).toEqual([2, 1, "NBO"]);
    expect(predictiveFigures({ ...o, rising: [] }).top).toBeNull();
  });
});

describe("auditFigures (G-4)", () => {
  const entry = (h: number, actor_type: AuditEntry["actor_type"], actor_id = "x") =>
    ({ occurred_at: ago(h), actor_type, actor_id }) as AuditEntry;
  it("counts the last 24 hours and the people acting in them", () => {
    const f = auditFigures([entry(1, "USER", "a"), entry(2, "USER", "a"), entry(3, "USER", "b"), entry(4, "AGENT"), entry(30, "USER", "c")], NOW);
    expect(f).toEqual({ day: "4", full: false, people: 2, agents: 1 });
  });
  it("says 200+ when all 200 loaded entries are from the last day", () => {
    const f = auditFigures(Array.from({ length: 200 }, () => entry(1, "SYSTEM")), NOW);
    expect([f.day, f.full]).toEqual(["200+", true]);
  });
});

describe("reviewFigures (G-4)", () => {
  it("counts reviews by status, those ready, findings and accepted actions", () => {
    const review = (status: ReviewSummary["status"], items: number, accepted: number) =>
      ({ status, items, accepted }) as ReviewSummary;
    const r = { reviews: [review("DRAFT", 4, 1), review("FINAL", 6, 3)], ready: [{}, {}] } as Reviews;
    expect(reviewFigures(r)).toEqual({ reviews: 2, drafts: 1, final: 1, ready: 2, findings: 10, accepted: 4 });
  });
});

describe("exerciseMonths (DC-02)", () => {
  const ex = (ended: string, source: ExerciseSummary["source"], status: ExerciseSummary["status"] = "COMPLETED") =>
    ({ ended_at: ended, source, status }) as ExerciseSummary;
  it("counts completed exercises per month, the seeded history before the first real one lighter", () => {
    const now = Date.parse("2026-05-20T00:00:00Z");
    const f = exerciseMonths(
      [
        ex("2026-01-10T00:00:00Z", "ILLUSTRATIVE"),
        ex("2026-02-10T00:00:00Z", "ILLUSTRATIVE"),
        ex("2026-04-02T00:00:00Z", "EXERCISE"),
        ex("2026-04-03T00:00:00Z", "EXERCISE", "ABANDONED"),
      ],
      now,
    );
    expect(f).toEqual({ values: [1, 1, 0, 1, 0], faint: 3 });
  });
  it("draws nothing lighter without seeded history, and all of it with no real exercise", () => {
    const now = Date.parse("2026-03-01T00:00:00Z");
    expect(exerciseMonths([ex("2026-02-01T00:00:00Z", "EXERCISE")], now).faint).toBe(0);
    expect(exerciseMonths([ex("2026-02-01T00:00:00Z", "ILLUSTRATIVE")], now).faint).toBe(3);
  });
});
