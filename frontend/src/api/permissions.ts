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
