import type { Draft, NtfCampaign } from "../../api/notifications";

export const EMPTY: Draft = {
  kind: "ALERT",
  message: "",
  channels: ["APP", "SMS"],
  missions: [],
  person_types: null,
  exposed_to_incident: false,
  incident_id: null,
  translations: {},
  template_id: null,
};

export function draftOf(c: NtfCampaign): Draft {
  return {
    kind: c.campaign_type === "TEST" ? "ALERT" : c.campaign_type,
    message: c.message,
    channels: c.channels,
    missions: c.audience_filter.missions ?? [],
    person_types: c.audience_filter.person_types ?? null,
    exposed_to_incident: !!c.audience_filter.exposed,
    incident_id: c.incident_id,
    translations: c.translations,
    template_id: c.template_id,
  };
}
