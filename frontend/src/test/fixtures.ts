// API responses shaped like the NBO-CIVIL-UNREST scene 2 state (decisions.md §7).
import type {
  Exposure,
  Incident,
  IncidentDetail,
  OperationsSummary,
  Signal,
  SourceRef,
} from "../api/intel";
import type { Me } from "../api/me";
import type { Mission, Page, Person, SitesPage } from "../api/people";

export const NBO_ID = "m-nbo";
const NOW = new Date().toISOString();

/** xs[i], failing the test if it is missing (the tsconfig checks indexed access). */
export function at<T>(xs: readonly T[], i: number): T {
  const x = xs[i];
  if (x === undefined) throw new Error(`no element ${i}`);
  return x;
}

const DATAMINR: SourceRef = { code: "DATAMINR", name: "Dataminr", simulated: true };
const MAX: SourceRef = { code: "MAX", name: "MAX Security", simulated: true };
const RISKLINE: SourceRef = { code: "RISKLINE", name: "Riskline", simulated: true };
export const SOURCES = [DATAMINR, MAX, RISKLINE];

export const INCIDENT: Incident = {
  id: "inc-1042",
  reference: "INC-2026-1042",
  title: "Civil unrest · Nairobi CBD · Kenyatta Avenue",
  category: "CIVIL_UNREST",
  severity: "CRITICAL",
  signal_severity: "HIGH",
  status: "ACTIVE",
  confidence: 92,
  mission_id: NBO_ID,
  lat: -1.2838,
  lon: 36.8245,
  impact_radius_m: 5000,
  place_label: "Nairobi CBD · Kenyatta Avenue",
  opened_at: NOW,
  last_signal_at: NOW,
  signal_count: 3,
  sources: SOURCES,
};

function signal(id: number, source: SourceRef, provider: string, norm: Signal["norm_severity"]): Signal {
  return {
    id,
    source_code: source.code,
    source_name: source.name,
    source_simulated: true,
    external_id: `x-${id}`,
    title: `${source.name} report`,
    provider_category: "Unrest",
    provider_severity: provider,
    norm_category: "CIVIL_UNREST",
    norm_severity: norm,
    norm_status: "FUSED",
    lat: -1.28,
    lon: 36.82,
    place_label: "Nairobi",
    occurred_at: NOW,
    received_at: NOW,
    incident_id: INCIDENT.id,
    incident_reference: INCIDENT.reference,
  };
}

export const SIGNALS: Signal[] = [
  signal(3, RISKLINE, "Moderate", "MODERATE"),
  signal(2, MAX, "Level 4", "HIGH"),
  signal(1, DATAMINR, "High", "HIGH"),
];

export const PETER: Exposure = {
  subject_type: "PERSON",
  subject_id: "p-peter",
  name: "Peter Mwangi",
  kind: "LOCAL_STAFF",
  mission_code: "NBO",
  lat: -1.2985,
  lon: 36.8195,
  distance_m: 1718,
  confidence: 91,
  location_source: "MOBILE_GPS",
  place_label: "Haile Selassie Ave",
};

export const DETAIL: IncidentDetail = {
  ...INCIDENT,
  mission_code: "NBO",
  exposure_summary: {
    staff: 14,
    delegates: 3,
    citizens: 212,
    people: 229,
    sites: 3,
    mission_sites: 2,
    protected_sites: 2,
    trips: 1,
  },
  exposure: [
    PETER,
    {
      subject_type: "PERSON",
      subject_id: "p-hana",
      name: "Hana Takeda",
      kind: "DIPLOMAT",
      mission_code: "NBO",
      lat: -1.2676,
      lon: 36.8108,
      distance_m: 2352,
      confidence: 72,
      location_source: "CALENDAR_HR",
      place_label: "Westlands",
    },
  ],
  signals: [...SIGNALS].reverse(),
  timeline: [
    {
      id: 1,
      event_type: "SIGNAL",
      summary: "Opened from Dataminr: High → HIGH. Confidence 60%.",
      actor_type: "SYSTEM",
      actor_id: "intel.fusion",
      occurred_at: NOW,
      data: {},
    },
    {
      id: 2,
      event_type: "ESCALATED",
      summary: "Severity HIGH → CRITICAL: protected mission site in the impact zone (D-11).",
      actor_type: "SYSTEM",
      actor_id: "intel.exposure",
      occurred_at: NOW,
      data: {},
    },
  ],
};

export const SUMMARY: OperationsSummary = {
  missions: 36,
  missions_elevated: 5,
  missions_critical: 1,
  personnel: 1338,
  personnel_located: 1338,
  avg_location_confidence: 93.4,
  citizens: 1212,
  mission_sites: 74,
  trips_active: 1,
  travellers_active: 3,
  signals_24h: 4,
  incidents_active: 2,
  highest_active_severity: "CRITICAL",
};

export const NAIROBI: Mission = {
    id: NBO_ID,
    code: "NBO",
    city: "Nairobi",
    country_code: "KE",
    lat: -1.2921,
    lon: 36.8219,
    risk_level: "LOW",
    display_risk: "CRITICAL",
    incident_id: INCIDENT.id,
    incident_reference: INCIDENT.reference,
    personnel: 17,
    citizens: 212,
};
export const MISSIONS: Mission[] = [NAIROBI];

export const PEOPLE: Page<Person> = {
  total: 2,
  items: [
    {
      id: "p-peter",
      full_name: "Peter Mwangi",
      person_type: "LOCAL_STAFF",
      role_title: "Driver",
      mission_code: "NBO",
      place_label: "Haile Selassie Ave",
      lat: -1.2985,
      lon: 36.8195,
      location_source: "MOBILE_GPS",
      confidence: 91,
      located_at: NOW,
      in_zone: true,
      incident_reference: INCIDENT.reference,
    },
    {
      id: "p-omar",
      full_name: "Omar Said",
      person_type: "LOCAL_STAFF",
      role_title: null,
      mission_code: "CAI",
      place_label: "Zamalek",
      lat: 30.05,
      lon: 31.25,
      location_source: "MANUAL",
      confidence: 60,
      located_at: NOW,
      in_zone: false,
      incident_reference: null,
    },
  ],
};

export const SITES: SitesPage = {
  total: 2,
  mission_property: 1,
  items: [
    {
      id: "s-emb",
      name: "Embassy Nairobi",
      site_type: "EMBASSY",
      mission_code: "NBO",
      city: "Nairobi",
      lat: -1.295,
      lon: 36.808,
      readiness_score: 88,
      last_drill_on: new Date(Date.now() - 21 * 86_400_000).toISOString().slice(0, 10),
      in_zone: true,
    },
    {
      id: "s-hotel",
      name: "Hotel Upper Hill",
      site_type: "HOTEL",
      mission_code: "NBO",
      city: "Nairobi",
      lat: -1.2975,
      lon: 36.824,
      readiness_score: null,
      last_drill_on: null,
      in_zone: true,
    },
  ],
};

export const VIEWER: Me = {
  id: "u-viewer",
  display_name: "Vera Pohl",
  email: "viewer@demo.nexira.invalid",
  roles: [{ code: "VIEWER", mission_id: null, mission_code: null }],
};

export const HOM_CAIRO: Me = {
  id: "u-hom-cai",
  display_name: "Cairo HoM",
  email: "hom.cairo@demo.nexira.invalid",
  roles: [{ code: "HEAD_OF_MISSION", mission_id: "m-cai", mission_code: "CAI" }],
};

export const HOM_NAIROBI: Me = {
  id: "u-hom-nbo",
  display_name: "Nairobi HoM",
  email: "hom.nairobi@demo.nexira.invalid",
  roles: [{ code: "HEAD_OF_MISSION", mission_id: NBO_ID, mission_code: "NBO" }],
};
