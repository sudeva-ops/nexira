import type { Overview } from "../../api/executive";

/** The trend's illustrative lead-in and its live totals (GFX-05, plan-pilot-gfx G-6). The
 *  illustrative days always come first; the totals count live days only. */
export function trendParts(trend: Overview["trend"]): { faint: number; signals: number; incidents: number } {
  const faint = trend.findIndex((d) => d.source === "LIVE");
  const live = trend.filter((d) => d.source === "LIVE");
  return {
    faint: faint === -1 ? trend.length : faint,
    signals: live.reduce((n, d) => n + d.signals, 0),
    incidents: live.reduce((n, d) => n + d.incidents, 0),
  };
}
