import type { RecentChange } from "../../api/executive";
import { formatDate } from "../../app/time";

const DAY_MS = 86_400_000;

/** GFX-06 (D-55): what Recent activity says when nothing opened or closed in the last 7 days. It
 *  names the last incident on record, or says there is none; it never invents one. */
export function quietLine(last: RecentChange | null | undefined, now: Date): string {
  if (!last) return "No incident on record yet. Nothing opened or closed in the last 7 days.";
  const days = Math.max(0, Math.floor((now.getTime() - new Date(last.at).getTime()) / DAY_MS));
  const change = last.change === "OPENED" ? "opened" : "closed";
  return `Quiet for ${days} ${days === 1 ? "day" : "days"} · last incident ${last.reference} ${last.title}, ${change} ${formatDate(last.at)}.`;
}
