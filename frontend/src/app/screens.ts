import type { IconName } from "@blueprintjs/core";

export interface Screen {
  path: string;
  title: string;
  subtitle: string;
  icon: IconName;
  group: "COMMAND" | "MONITOR" | "RESPOND" | "PLAN & INSIGHT" | "ADMIN";
  builtIn: string; // prompt that builds the real screen
  // In the nav only when GET /api/vip/access says visible (VIP-06), or for administrators (UIP-07).
  // Display only: the API enforces every check (D-04).
  restricted?: "vip" | "admin";
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
  { path: "/health", title: "Health Intelligence", subtitle: "Health · WHO advisories, outbreaks & medical facilities", icon: "symbol-cross", group: "MONITOR", builtIn: "Prompt 63" },
  { path: "/hazards", title: "Natural Hazards & Climate", subtitle: "Hazards · Live events & long-term site exposure", icon: "globe-network", group: "MONITOR", builtIn: "Prompt 57" },
  { path: "/playbooks", title: "Response Playbooks", subtitle: "Workflows · Automated response", icon: "flash", group: "RESPOND", builtIn: "Prompt 11" },
  // D-40: under RESPOND, after Response Playbooks (§53 Q9).
  { path: "/evacuation", title: "Evacuation Management", subtitle: "Response · Manifests, seats & routes", icon: "log-out", group: "RESPOND", builtIn: "Prompt 69" },
  // D-41: under RESPOND, after Evacuation Management (§58 Q9).
  { path: "/fleet", title: "Fleet & Assets", subtitle: "Assets · Vehicles, fuel & availability", icon: "truck", group: "RESPOND", builtIn: "Prompt 75" },
  // D-42: under RESPOND, after Fleet & Assets (§63 Q8); only for those who may see visits.
  { path: "/vip", title: "VIP Protection", subtitle: "Protection · Visits, programme risk & checklist", icon: "shield", group: "RESPOND", builtIn: "Prompt 81", restricted: "vip" },
  { path: "/notifications", title: "Mass Notification", subtitle: "Comms · Multi-channel delivery", icon: "send-message", group: "RESPOND", builtIn: "Prompt 21" },
  { path: "/partners", title: "Assistance Partners", subtitle: "Response · Medical, evacuation & secure transport", icon: "helper-management", group: "RESPOND", builtIn: "Prompt 46" },
  // D-43: under RESPOND, after Assistance Partners (§68 Q8).
  { path: "/twin", title: "Site Twin", subtitle: "Sites · Floor plan, occupancy & sensors", icon: "grid-view", group: "RESPOND", builtIn: "Prompt 87" },
  { path: "/checkin", title: "Safety Check-in", subtitle: "Workflows · Personnel accountability", icon: "tick-circle", group: "RESPOND", builtIn: "Prompt 11" },
  // D-50 (§98 Q8): after Safety Check-in, as the design; not the design's "AIP" wording (D-19).
  { path: "/copilot", title: "AI Risk Copilot", subtitle: "Grounded on live platform data", icon: "chat", group: "RESPOND", builtIn: "Prompt 120" },
  // Plan-pilot-dx G-9: PLAN & INSIGHT, as the design.
  { path: "/documents", title: "Document Expiry", subtitle: "Compliance · Passports, visas & clearances", icon: "document", group: "PLAN & INSIGHT", builtIn: "Prompt 51" },
  // D-44 (§73 Q8): after Document Expiry; icon box, since Fleet uses truck.
  { path: "/supply", title: "Supply Chain Risk", subtitle: "Third parties · Vendors & logistics routes", icon: "box", group: "PLAN & INSIGHT", builtIn: "Prompt 93" },
  // D-46 (§83 Q8): before Executive Overview, as the design.
  { path: "/predictive", title: "Predictive Risk", subtitle: "Analytics · 14-day risk forecast", icon: "trending-up", group: "PLAN & INSIGHT", builtIn: "Prompt 104" },
  // D-48 (§93 Q11): before After-Action Review, as the design.
  { path: "/exercises", title: "Exercise & Training", subtitle: "Readiness · Drills & scoring", icon: "target", group: "PLAN & INSIGHT", builtIn: "Prompt 116" },
  // D-47 (§88 Q10): after Predictive Risk, as the design.
  { path: "/aar", title: "After-Action Review", subtitle: "Learning · Timeline, lessons & actions", icon: "clipboard-file", group: "PLAN & INSIGHT", builtIn: "Prompt 110" },
  // D-45 (§78 Q7): last under PLAN & INSIGHT, as the design.
  { path: "/executive", title: "Executive Overview", subtitle: "Dashboard · Leadership view", icon: "chart", group: "PLAN & INSIGHT", builtIn: "Prompt 97" },
  { path: "/audit", title: "Audit", subtitle: "Admin · Hash-chained audit log", icon: "history", group: "ADMIN", builtIn: "Prompt 3", restricted: "admin" },
];

// Screens reached from another screen, not from the sidebar: the header still names them.
export const SUB_SCREENS: readonly Screen[] = [
  // RPL-06 (D-51): from Incidents, After-Action Review and Exercise & Training.
  { path: "/incidents/replay", title: "Incident Replay", subtitle: "Played back from the record", icon: "play", group: "MONITOR", builtIn: "Prompt 123" },
];
