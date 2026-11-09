import type { Metric } from "../../api/aar";
import { duration } from "../../api/executive";

/** "1m 45s" or "94%"; "—" without a figure. */
export function metricValue(m: Metric): string {
  if (m.value === null) return "—";
  return m.unit === "%" ? `${Math.round(m.value)}%` : duration(m.value);
}

export function metricTarget(m: Metric): string {
  if (m.target === null) return "";
  return `target ${m.unit === "%" ? `${m.target}%` : duration(m.target)}`;
}

/** Today plus n days as YYYY-MM-DD, the default due date. */
export function inDays(n: number, now: Date = new Date()): string {
  return new Date(now.getTime() + n * 86_400_000).toISOString().slice(0, 10);
}
