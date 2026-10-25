import type { Proposal } from "../../api/proposals";
import { roleLabel } from "../../ui/format";

export const REJECT_REASONS = ["Not needed", "Wrong timing", "Insufficient evidence", "Handled offline"];

/** "Decide in 12:04", "OVERDUE", or "" when there is no deadline. */
export function countdown(deadline: string | null, now: number): string {
  if (!deadline) return "";
  const s = Math.round((new Date(deadline).getTime() - now) / 1000);
  if (s <= 0) return "OVERDUE";
  return `Decide in ${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** The step this user would decide, as "Head of mission (1/2)". */
export function nextStep(p: Proposal): string | null {
  const open = p.approvals.find((a) => a.decision === null);
  if (!open) return null;
  const total = p.approvals.length;
  return `${roleLabel(open.required_role)}${total > 1 ? ` (${open.step_no}/${total})` : ""}`;
}

export interface QueueMetrics {
  pending: number;
  proactive: number;
  medianDecideS: number | null;
  acceptedPct: number | null;
  decided: number;
}

const HUMAN_DECIDED = ["APPROVED", "EDITED_APPROVED", "REJECTED", "FAILED"];

/** DQ-08, from the proposals themselves. */
export function metrics(proposals: Proposal[]): QueueMetrics {
  const decided = proposals.filter((p) => HUMAN_DECIDED.includes(p.status) && p.decided_at);
  const times = decided
    .map((p) => (new Date(p.decided_at ?? 0).getTime() - new Date(p.created_at).getTime()) / 1000)
    .sort((a, b) => a - b);
  const accepted = decided.filter((p) => p.status !== "REJECTED").length;
  return {
    pending: proposals.filter((p) => p.status === "PENDING").length,
    proactive: proposals.filter((p) => p.is_proactive).length,
    medianDecideS: times.length ? Math.round(times[Math.floor(times.length / 2)] ?? 0) : null,
    acceptedPct: decided.length ? Math.round((accepted / decided.length) * 100) : null,
    decided: decided.length,
  };
}

/** Pending first by deadline, then the rest newest first. */
export function queueOrder(a: Proposal, b: Proposal): number {
  if (a.status === "PENDING" && b.status === "PENDING") {
    return (a.deadline_at ?? "9").localeCompare(b.deadline_at ?? "9");
  }
  if (a.status === "PENDING") return -1;
  if (b.status === "PENDING") return 1;
  return b.created_at.localeCompare(a.created_at);
}
