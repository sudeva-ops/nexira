import type { Answer, Replay } from "../../api/replay";
import { standing } from "../../map/annotations";

// RPL-02, RPL-04 (plan-pilot-rpl §2): the incident at a moment t (ms since the epoch), from the
// one payload. Pure, so the screen, the map and the tests agree.

export type PersonState = "NOT_ASKED" | "WAITING" | "SAFE" | "NEED_HELP";

/** A person's colour by their check-in state at the moment (RPL-02). */
export const STATE_COLOUR: Record<PersonState, string> = {
  NOT_ASKED: "#8F99A8",
  WAITING: "#FBB360",
  SAFE: "#32A467",
  NEED_HELP: "#E76A6E",
};

export interface Tally {
  recipients: number;
  safe: number;
  need_help: number;
  pending: number;
}

export interface Moment {
  elapsedMs: number;
  signals: Replay["signals"];
  zone: boolean; // the impact zone shows once the incident is open
  people: { lon: number; lat: number; state: PersonState }[];
  exposed: number; // people exposed by t, placed or not
  sites: Replay["sites"];
  tally: Tally | null; // null until the check-in is sent
  annotations: Replay["annotations"]; // standing at t (ANN-06)
}

/** At 1× the whole play axis lasts this long (§103 Q3, quiet stretches shortened: G-9). */
export const PLAY_MS = 60_000;
export const SPEEDS = [0.5, 1, 2, 4] as const;

const ms = (iso: string) => Date.parse(iso);

export function bounds(r: Replay): { start: number; end: number } {
  return { start: ms(r.window.start), end: ms(r.window.end) };
}

/** A quiet stretch of the record longer than this plays as this long (plan G-9). */
export const QUIET_MS = 30_000;

/** The play axis: the record's moments in order, with every quiet stretch shortened to QUIET_MS,
 * so an hour's silence after the response does not squeeze the response into seconds. */
export interface Axis {
  total: number; // play length, record ms
  record: number[]; // knots on the record axis
  play: number[]; // the same knots on the play axis
  breaks: { from: number; to: number; quietMs: number }[]; // on the play axis
}

export function axis(r: Replay): Axis {
  const { start, end } = bounds(r);
  const times = new Set<number>([start, end, ms(r.incident.opened_at)]);
  for (const s of r.signals) times.add(ms(s.received_at));
  for (const p of r.people) {
    times.add(ms(p.exposed_at));
    for (const a of p.answers) times.add(ms(a.at));
  }
  for (const s of r.sites) times.add(ms(s.exposed_at));
  if (r.checkin?.sent_at) times.add(ms(r.checkin.sent_at));
  for (const e of r.timeline) times.add(ms(e.at));
  const record = [...times].filter((x) => x >= start && x <= end).sort((a, b) => a - b);
  const play = [0];
  const breaks: Axis["breaks"] = [];
  for (let i = 1; i < record.length; i += 1) {
    const gap = (record[i] ?? 0) - (record[i - 1] ?? 0);
    const before = play[i - 1] ?? 0;
    if (gap > QUIET_MS) breaks.push({ from: before, to: before + QUIET_MS, quietMs: gap });
    play.push(before + Math.min(gap, QUIET_MS));
  }
  return { total: Math.max(play[play.length - 1] ?? 0, 1), record, play, breaks };
}

function across(from: number[], to: number[], x: number): number {
  if (x <= (from[0] ?? 0)) return to[0] ?? 0;
  for (let i = 1; i < from.length; i += 1) {
    const a = from[i - 1] ?? 0;
    const b = from[i] ?? 0;
    if (x <= b) {
      const k = b === a ? 1 : (x - a) / (b - a);
      return (to[i - 1] ?? 0) + k * ((to[i] ?? 0) - (to[i - 1] ?? 0));
    }
  }
  return to[to.length - 1] ?? 0;
}

/** A record moment on the play axis, and back. */
export const toPlay = (a: Axis, t: number) => across(a.record, a.play, t);
export const toRecord = (a: Axis, p: number) => across(a.play, a.record, p);

/** How far along the play axis a real millisecond moves at a speed (§103 Q3: 60 s at 1×). */
export function rate(a: Axis, speed: number): number {
  return (a.total / PLAY_MS) * speed;
}

function latest(answers: Answer[], t: number): Answer | null {
  let found: Answer | null = null;
  for (const a of answers) if (ms(a.at) <= t) found = a;
  return found;
}

export function stateAt(r: Replay, t: number): Moment {
  const sent = r.checkin?.sent_at ? ms(r.checkin.sent_at) : null;
  const asking = sent !== null && sent <= t;
  const shown = r.people.filter((p) => ms(p.exposed_at) <= t);
  const people = shown.flatMap((p) => {
    if (p.lon === null || p.lat === null) return [];
    const answer = latest(p.answers, t);
    const state: PersonState =
      !p.asked || !asking ? "NOT_ASKED" : answer ? answer.status : "WAITING";
    return [{ lon: p.lon, lat: p.lat, state }];
  });
  let tally: Tally | null = null;
  if (r.checkin && asking) {
    tally = { recipients: r.checkin.personnel.length, safe: 0, need_help: 0, pending: 0 };
    for (const answers of r.checkin.personnel) {
      const a = latest(answers, t);
      if (a?.status === "SAFE") tally.safe += 1;
      else if (a?.status === "NEED_HELP") tally.need_help += 1;
      else tally.pending += 1;
    }
  }
  return {
    elapsedMs: Math.max(0, t - bounds(r).start),
    signals: r.signals.filter((s) => ms(s.received_at) <= t),
    zone: ms(r.incident.opened_at) <= t,
    people,
    exposed: shown.length,
    sites: r.sites.filter((s) => ms(s.exposed_at) <= t),
    tally,
    annotations: standing(r.annotations, t),
  };
}

/** The index of the timeline entry in force at t (the last one at or before it), or -1. */
export function entryAt(r: Replay, t: number): number {
  let found = -1;
  r.timeline.forEach((e, i) => {
    if (ms(e.at) <= t) found = i;
  });
  return found;
}

/** The moment of the next (+1) or previous (-1) entry from t, inside the window. */
export function step(r: Replay, t: number, direction: 1 | -1): number {
  const { start, end } = bounds(r);
  const times = r.timeline.map((e) => ms(e.at));
  if (direction === 1) return times.find((x) => x > t) ?? end;
  return [...times].reverse().find((x) => x < t) ?? start;
}

/** "+12:34", or "+1:02:03" past an hour. */
export function elapsed(msValue: number): string {
  const s = Math.floor(msValue / 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `+${h}:${pad(m)}:${pad(s % 60)}` : `+${m}:${pad(s % 60)}`;
}
