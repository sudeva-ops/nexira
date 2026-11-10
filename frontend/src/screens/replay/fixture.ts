import type { Replay } from "../../api/replay";

// A small incident for the replay tests: signal at 0 s, opened at 2 s, exposed at 3 s, the
// check-in sent at 10 s, answers at 20 s and 40 s; the window ends at 60 s.
export const T0 = Date.parse("2026-11-10T08:00:00Z");
export const at = (s: number) => new Date(T0 + s * 1000).toISOString();

export const REPLAY: Replay = {
  window: { start: at(0), end: at(60) },
  incident: {
    id: "inc-1042",
    reference: "INC-2026-1042",
    title: "Civil unrest, Nairobi CBD",
    severity: "HIGH",
    status: "MONITORING",
    lon: 36.82,
    lat: -1.29,
    impact_radius_m: 5000,
    opened_at: at(2),
    exercise: false,
  },
  signals: [{ received_at: at(0), lon: 36.82, lat: -1.29, severity: "HIGH" }],
  people: [
    { index: 0, lon: 36.81, lat: -1.28, exposed_at: at(3), personnel: true, asked: true, answers: [{ at: at(20), status: "SAFE" }] },
    { index: 1, lon: 36.83, lat: -1.3, exposed_at: at(3), personnel: true, asked: true, answers: [{ at: at(40), status: "NEED_HELP" }] },
    { index: 2, lon: 36.82, lat: -1.29, exposed_at: at(3), personnel: true, asked: true, answers: [] },
    { index: 3, lon: 36.8, lat: -1.27, exposed_at: at(3), personnel: false, asked: false, answers: [] },
    { index: 4, lon: null, lat: null, exposed_at: at(3), personnel: false, asked: false, answers: [] },
  ],
  sites: [{ name: "Embassy", lon: 36.82, lat: -1.28, exposed_at: at(3) }],
  trips: 1,
  checkin: {
    reference: "NTF-3101",
    sent_at: at(10),
    personnel: [[{ at: at(20), status: "SAFE" }], [{ at: at(40), status: "NEED_HELP" }], []],
    tally_end: { recipients: 3, safe: 1, need_help: 1, pending: 1 },
  },
  timeline: [
    { at: at(0), source: "INCIDENT", text: "First signal received.", site_id: null, sensor: null },
    { at: at(2), source: "INCIDENT", text: "Incident INC-2026-1042 opened.", site_id: null, sensor: null },
    { at: at(10), source: "NOTIFICATION", text: "NTF-3101 sent: checkin, 3 recipients.", site_id: null, sensor: null },
    { at: at(40), source: "CHECKIN", text: "Check-in NTF-3101: a person needs help.", site_id: null, sensor: null },
  ],
};
