// Events carry ids only (PLT-05), so the header names the kind of event, not what it is about.

const EVENT_LABEL: Record<string, string> = {
  SIGNAL_INGESTED: "New signal",
  INCIDENT_CREATED: "Incident opened",
  INCIDENT_UPDATED: "Incident updated",
  INCIDENT_NOTE_ADDED: "Incident note",
  EXPOSURE_COMPUTED: "Exposure computed",
  PLAYBOOK_RUN_STARTED: "Playbook started",
  PLAYBOOK_RUN_UPDATED: "Playbook updated",
  PLAYBOOK_STEP: "Playbook step",
  PLAYBOOK_STEP_APPROVED: "Playbook step approved",
  CAMPAIGN_QUEUED: "Notification queued",
  CAMPAIGN_UPDATED: "Notification updated",
  CHECKIN_UPDATED: "Check-in response",
  CHECKIN_ESCALATED: "Check-in escalated",
  TRIP_UPDATED: "Trip updated",
  FLIGHT_UPDATED: "Flight updated",
  FLIGHT_POSITIONS: "Flight positions",
  PARTNER_REQUEST_UPDATED: "Partner request",
  WEATHER_UPDATED: "Weather updated",
  PROPOSAL_CREATED: "New proposal",
  PROPOSAL_UPDATED: "Proposal decided",
  PROPOSAL_EXPIRED: "Proposal expired",
};

export function eventLabel(event: string): string {
  return EVENT_LABEL[event] ?? event.charAt(0) + event.slice(1).toLowerCase().replaceAll("_", " ");
}
