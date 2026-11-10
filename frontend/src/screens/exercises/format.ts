import type { Score } from "../../api/exercises";
import { duration } from "../../api/executive";

function num(v: unknown): number | null {
  return typeof v === "number" ? v : null;
}

/** The figure and target behind a score (plan §8), e.g. "1m 46s · target 2m 00s" or "16 of 17". */
export function measuredText(s: Score): string {
  const m = s.measured;
  if (m.illustrative === true) return "Illustrative";
  const of = (a: unknown, b: unknown, what = "") => {
    const x = num(a);
    const y = num(b);
    return x === null || y === null ? "" : `${x} of ${y}${what}`;
  };
  switch (s.dimension) {
    case "DETECTION": {
      const seconds = num(m.seconds);
      const target = num(m.target_s);
      if (seconds === null) return "No notification sent";
      return `${duration(seconds)}${target === null ? "" : ` · target ${duration(target)}`}`;
    }
    case "ACCOUNTABILITY": {
      const text = of(m.answered, m.asked, " answered");
      return text ? `${text}${typeof m.campaign === "string" ? ` · ${m.campaign}` : ""}` : "No check-in";
    }
    case "DECISION_SPEED": {
      const target = num(m.target_s);
      const text = of(m.within, m.decisions);
      return num(m.decisions) ? `${text} within ${target === null ? "target" : duration(target)}` : "No decision";
    }
    case "COMMUNICATION":
      return num(m.exposed) ? `${of(m.reached, m.exposed, " exposed reached")}` : "Nobody exposed";
    case "PLAN_ADHERENCE":
      return of(m.done, m.steps, " steps done") || "No playbook run";
  }
}
