import type { IconName } from "@blueprintjs/core";

import type { RunStep } from "../../api/playbooks";
import { roleLabel } from "../../ui/format";

export const ACTION_ICON: Record<string, IconName> = {
  TASK: "tick",
  NOTIFY: "notifications",
  CHECKIN: "tick-circle",
  PARTNER_REQUEST: "heart",
  APPROVAL_GATE: "endorsed",
  BRIEFING: "document",
};

export const STEP_CLASS: Record<string, string> = {
  DONE: "done",
  RUNNING: "run",
  AWAITING_APPROVAL: "await",
  FAILED: "fail",
  SKIPPED: "done",
  PENDING: "pend",
};

/** What a step did, from its result (or what it will do). */
export function stepDetail(step: RunStep): string {
  const r = step.result;
  if (typeof r.error === "string") return `Failed: ${r.error}`;
  if (step.status === "AWAITING_APPROVAL" && step.requires_approval_role) {
    return `Requires ${roleLabel(step.requires_approval_role)} approval`;
  }
  const parts: string[] = [];
  if (typeof r.reference === "string") {
    const channels = Array.isArray(r.channels) ? ` · ${(r.channels as string[]).join(" · ")}` : "";
    parts.push(`${r.reference} · ${String(r.recipients)} recipients${channels}`);
  } else if (typeof r.partner === "string") {
    parts.push(`${r.partner} on standby (simulated)`);
  } else if (typeof r.report === "string") {
    parts.push(r.report);
  } else if (typeof r.summary === "string") {
    parts.push(r.summary);
  } else if (step.status === "PENDING" && step.requires_approval_role) {
    parts.push(`Requires ${roleLabel(step.requires_approval_role)} approval`);
  }
  if (step.approved_by_name) parts.push(`Approved by ${step.approved_by_name}`);
  return parts.join(" · ");
}
