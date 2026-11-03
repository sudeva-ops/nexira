import type { IconName } from "@blueprintjs/core";

export interface Screen {
  path: string;
  title: string;
  subtitle: string;
  icon: IconName;
  group: "COMMAND" | "MONITOR" | "RESPOND" | "PLAN & INSIGHT" | "ADMIN";
  builtIn: string; // prompt that builds the real screen
  restricted?: "vip"; // in the nav only when GET /api/vip/access says visible (VIP-06)
}

// D-25: the Phase 1 screens, plus the pilot modules approved under D-30. Groups and subtitles follow the demo,
// without "Object explorer" / "AIP" wording (D-19); Audit is not in the demo nav.
// The Presenter bar is not a screen; it renders only in demo mode (Prompt 15).
export const SCREENS: readonly Screen[] = [
  { path: "/", title: "Decision Queue", subtitle: "Command · Agent proposals awaiting human decision", icon: "inbox", group: "COMMAND", builtIn: "Prompt 14" },
  { path: "/agents", title: "AI Agents", subtitle: "Command · Agent roster, autonomy & guardrails", icon: "predictive-analysis", group: "COMMAND", builtIn: "Prompt 14" },
  { path: "/operations", title: "Global Operations", subtitle: "Map · Live situational awareness", icon: "globe", group: "MONITOR", builtIn: "Prompt 8" },
  { path: "/incidents", title: "Incidents", subtitle: "Fused threat intelligence", icon: "warning-sign", group: "MONITOR", builtIn: "Prompt 8" },
  { path: "/people", title: "People & Sites", subtitle: "Location confidence", icon: "people", group: "MONITOR", builtIn: "Prompt 8" },
  { path: "/journeys", title: "Journey Management", subtitle: "Travel risk · Trip approvals & itineraries", icon: "airplane", group: "MONITOR", builtIn: "Prompt 26" },
  { path: "/air", title: "Air Travel Tracking", subtitle: "Travel · Officials in the air, delays & diversions", icon: "satellite", group: "MONITOR", builtIn: "Prompt 31" },
  // §48 Q9: under MONITOR, before Natural Hazards & Climate.
  { path: "/health", title: "Health Intelligence", subtitle: "Health · WHO advisories, outbreaks & medical facilities", icon: "heart", group: "MONITOR", builtIn: "Prompt 63" },
  { path: "/hazards", title: "Natural Hazards & Climate", subtitle: "Hazards · Live events & long-term site exposure", icon: "globe-network", group: "MONITOR", builtIn: "Prompt 57" },
  { path: "/playbooks", title: "Response Playbooks", subtitle: "Workflows · Automated response", icon: "flash", group: "RESPOND", builtIn: "Prompt 11" },
  // D-40: under RESPOND, after Response Playbooks (§53 Q9).
  { path: "/evacuation", title: "Evacuation Management", subtitle: "Response · Manifests, seats & routes", icon: "log-out", group: "RESPOND", builtIn: "Prompt 69" },
  // D-41: under RESPOND, after Evacuation Management (§58 Q9).
  { path: "/fleet", title: "Fleet & Assets", subtitle: "Assets · Vehicles, fuel & availability", icon: "truck", group: "RESPOND", builtIn: "Prompt 75" },
  // D-42: under RESPOND, after Fleet & Assets (§63 Q8); only for those who may see visits.
  { path: "/vip", title: "VIP Protection", subtitle: "Protection · Visits, programme risk & checklist", icon: "shield", group: "RESPOND", builtIn: "Prompt 81", restricted: "vip" },
  { path: "/notifications", title: "Mass Notification", subtitle: "Comms · Multi-channel delivery", icon: "send-message", group: "RESPOND", builtIn: "Prompt 21" },
  { path: "/partners", title: "Assistance Partners", subtitle: "Response · Medical, evacuation & secure transport", icon: "heart", group: "RESPOND", builtIn: "Prompt 46" },
  // D-43: under RESPOND, after Assistance Partners (§68 Q8).
  { path: "/twin", title: "Site Twin", subtitle: "Sites · Floor plan, occupancy & sensors", icon: "grid-view", group: "RESPOND", builtIn: "Prompt 87" },
  { path: "/checkin", title: "Safety Check-in", subtitle: "Workflows · Personnel accountability", icon: "tick-circle", group: "RESPOND", builtIn: "Prompt 11" },
  // Plan-pilot-dx G-9: PLAN & INSIGHT, as the design; Predictive Risk and Executive Overview join it later.
  { path: "/documents", title: "Document Expiry", subtitle: "Compliance · Passports, visas & clearances", icon: "document", group: "PLAN & INSIGHT", builtIn: "Prompt 51" },
  // D-44 (§73 Q8): after Document Expiry; icon box, since Fleet uses truck.
  { path: "/supply", title: "Supply Chain Risk", subtitle: "Third parties · Vendors & logistics routes", icon: "box", group: "PLAN & INSIGHT", builtIn: "Prompt 93" },
  // D-45 (§78 Q7): last under PLAN & INSIGHT, as the design.
  { path: "/executive", title: "Executive Overview", subtitle: "Dashboard · Leadership view", icon: "chart", group: "PLAN & INSIGHT", builtIn: "Prompt 97" },
  { path: "/audit", title: "Audit", subtitle: "Admin · Hash-chained audit log", icon: "history", group: "ADMIN", builtIn: "Prompt 3" },
];
