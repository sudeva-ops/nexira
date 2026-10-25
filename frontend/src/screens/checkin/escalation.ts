import type { CheckinPerson, CheckinSummary } from "../../api/checkin";
import { formatTime, HOME_TZ } from "../../app/time";

/** From the escalation records, not the clock: "Escalated" only once it happened. */
export function escalationText(summary: CheckinSummary, pending: CheckinPerson[], now = Date.now()): string {
  if (!summary.personnel.pending) return "—";
  if (pending.some((p) => p.escalated)) return "Escalated";
  if (!summary.sent_at) return "Sending…";
  const due = new Date(summary.sent_at).getTime() + summary.escalate_after_s * 1000;
  return due <= now ? "Escalation due" : `Auto-escalation at ${formatTime(new Date(due), HOME_TZ)}`;
}
