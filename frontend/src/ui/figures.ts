import type { AuditEntry } from "../api/audit";
import type { Reviews } from "../api/aar";
import type { Incident, Severity } from "../api/intel";
import type { PlaybookRun } from "../api/playbooks";
import type { PredictiveOverview } from "../api/predictive";

// DC-01 (D-56; plan G-1..G-4): the figures behind the new tile rows, from data each screen
// already loads. A list the API pages (runs: 50, audit: 200) gives "50+"/"200+" when every
// loaded row is inside the window, never a wrong total.

const DAY_MS = 86_400_000;
const RANK: Record<Severity, number> = { LOW: 0, MODERATE: 1, HIGH: 2, CRITICAL: 3 };

const within = (iso: string, now: number, ms: number) => now - Date.parse(iso) < ms;

/** "37", or "50+" when the page is full and all of it is inside the window. */
export function countOf(inWindow: number, loaded: number, page: number): string {
  return inWindow === loaded && loaded >= page ? `${page}+` : String(inWindow);
}

export function incidentFigures(list: Incident[], now: number) {
  const real = list.filter((i) => !i.exercise); // EXR-03: exercises counted apart
  const active = real.filter((i) => i.status === "ACTIVE");
  const highest = active.reduce<Severity | null>(
    (worst, i) => (worst === null || RANK[i.severity] > RANK[worst] ? i.severity : worst),
    null,
  );
  return {
    active: active.length,
    highest,
    monitoring: real.filter((i) => i.status === "MONITORING").length,
    opened30: real.filter((i) => within(i.opened_at, now, 30 * DAY_MS)).length,
    signals: active.reduce((sum, i) => sum + i.signal_count, 0),
    sources: new Set(active.flatMap((i) => i.sources.map((s) => s.code))).size,
    exercise: list.length - real.length,
  };
}

export const RUNS_PAGE = 50; // useRuns()

export function playbookFigures(runs: PlaybookRun[], now: number) {
  const live = runs.filter((r) => ["SCHEDULED", "RUNNING", "AWAITING_APPROVAL"].includes(r.status));
  const recent = runs.filter((r) => within(r.started_at, now, 30 * DAY_MS));
  return {
    active: live.length,
    armed: live.filter((r) => r.status === "SCHEDULED").length,
    atGate: live.filter((r) => r.steps.some((s) => s.status === "AWAITING_APPROVAL")).length,
    runs30: countOf(recent.length, runs.length, RUNS_PAGE),
    byAgent: recent.filter((r) => r.started_by_type === "AGENT").length,
  };
}

export function predictiveFigures(o: PredictiveOverview) {
  const top = o.rising.reduce<PredictiveOverview["rising"][number] | null>(
    (best, r) => (best === null || r.peak > best.peak ? r : best),
    null,
  );
  // The overview lists every mission (sorted by rise); "rising" is a forecast going up.
  return {
    rising: o.rising.filter((r) => r.change > 0).length,
    crossing: o.rising.filter((r) => r.crosses).length,
    top,
  };
}

export const AUDIT_PAGE = 200; // useAuditLog()

export function auditFigures(log: AuditEntry[], now: number) {
  const day = log.filter((e) => within(e.occurred_at, now, DAY_MS));
  const people = new Set(day.filter((e) => e.actor_type === "USER").map((e) => e.actor_id ?? ""));
  return {
    day: countOf(day.length, log.length, AUDIT_PAGE),
    full: day.length === log.length && log.length >= AUDIT_PAGE,
    people: people.size,
    agents: day.filter((e) => e.actor_type === "AGENT").length,
  };
}

export function reviewFigures(r: Reviews) {
  return {
    reviews: r.reviews.length,
    drafts: r.reviews.filter((x) => x.status === "DRAFT").length,
    final: r.reviews.filter((x) => x.status === "FINAL").length,
    ready: r.ready.length,
    findings: r.reviews.reduce((sum, x) => sum + x.items, 0),
    accepted: r.reviews.reduce((sum, x) => sum + x.accepted, 0),
  };
}
