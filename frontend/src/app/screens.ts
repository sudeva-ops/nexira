import type { IconName } from "@blueprintjs/core";

export interface Screen {
  path: string;
  title: string;
  subtitle: string;
  icon: IconName;
  group: "DECIDE" | "MONITOR" | "RESPOND" | "ADMIN";
  builtIn: string; // prompt that builds the real screen
}

// D-25: the Phase 1 screens, and only these. The Presenter bar is not a
// screen; it renders only in demo mode (Prompt 15).
export const SCREENS: readonly Screen[] = [
  { path: "/", title: "Decision Queue", subtitle: "Agent proposals awaiting a decision", icon: "inbox", group: "DECIDE", builtIn: "Prompt 14" },
  { path: "/agents", title: "AI Agents", subtitle: "Autonomy levels, policy floors, kill switch", icon: "predictive-analysis", group: "DECIDE", builtIn: "Prompt 14" },
  { path: "/operations", title: "Global Operations", subtitle: "Map · Live situational awareness", icon: "globe", group: "MONITOR", builtIn: "Prompt 8" },
  { path: "/incidents", title: "Incidents", subtitle: "Fused threat intelligence", icon: "warning-sign", group: "MONITOR", builtIn: "Prompt 8" },
  { path: "/people", title: "People & Sites", subtitle: "Location confidence", icon: "people", group: "MONITOR", builtIn: "Prompt 8" },
  { path: "/playbooks", title: "Response Playbooks", subtitle: "Workflows · Automated response", icon: "flash", group: "RESPOND", builtIn: "Prompt 11" },
  { path: "/checkin", title: "Safety Check-in", subtitle: "Workflows · Personnel accountability", icon: "tick-circle", group: "RESPOND", builtIn: "Prompt 11" },
  { path: "/audit", title: "Audit", subtitle: "Hash-chained audit log", icon: "history", group: "ADMIN", builtIn: "Prompt 3" },
];
