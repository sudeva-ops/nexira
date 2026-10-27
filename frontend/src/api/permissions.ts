import type { Me } from "./me";

// For hiding actions only; the backend decides (PLT-02). Mirrors the role lists
// in backend/app/modules/intel/router.py. GET /api/me/permissions (plan G-07)
// will replace this when the approval screens arrive.
const STATUS_ROLES = ["DUTY_OFFICER", "SECURITY_OFFICER", "HEAD_OF_MISSION", "HQ_CRISIS_DIRECTOR"];
const NOTE_ROLES = [...STATUS_ROLES, "CONSULAR_OFFICER", "TRAVEL_DESK"];

/** D-05/D-06: unscoped grants act anywhere; a mission grant only on that mission. */
function holds(me: Me | undefined, roles: string[], missionId: string | null): boolean {
  return (
    me?.roles.some(
      (r) => roles.includes(r.code) && (r.mission_id === null || r.mission_id === missionId),
    ) ?? false
  );
}

export function canChangeIncidentStatus(me: Me | undefined, missionId: string | null): boolean {
  return holds(me, STATUS_ROLES, missionId);
}

export function canAddIncidentNote(me: Me | undefined, missionId: string | null): boolean {
  return holds(me, NOTE_ROLES, missionId);
}

// backend/app/modules/playbooks/service.py START_ROLES and
// backend/app/modules/checkin/router.py RESPOND_ROLES. Step approvals do not use
// this file: they come from GET /api/me/permissions (approvals.can_decide()).
const START_ROLES = ["DUTY_OFFICER", "SECURITY_OFFICER"];
const RESPOND_ROLES = [
  "DUTY_OFFICER",
  "SECURITY_OFFICER",
  "CONSULAR_OFFICER",
  "HEAD_OF_MISSION",
  "HQ_CRISIS_DIRECTOR",
];

export function canStartPlaybook(me: Me | undefined, missionId: string | null): boolean {
  return holds(me, START_ROLES, missionId);
}

// backend/app/modules/travel/trips.py CREATORS. Every other trip action comes from
// GET /api/me/permissions (trips.permissions()).
const TRIP_CREATORS = ["TRAVEL_DESK", "DUTY_OFFICER"];

export function canPlanTrip(me: Me | undefined): boolean {
  return me?.roles.some((r) => TRIP_CREATORS.includes(r.code)) ?? false;
}

export function canRecordCheckin(me: Me | undefined, missionId: string | null): boolean {
  return holds(me, RESPOND_ROLES, missionId);
}
