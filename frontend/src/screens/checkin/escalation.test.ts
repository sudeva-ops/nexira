import type { CheckinPerson, CheckinSummary } from "../../api/checkin";
import { escalationText } from "./escalation";

const SENT = "2026-10-25T06:00:00Z";
const summary = (pending: number): CheckinSummary => ({
  campaign_id: "c",
  reference: "NTF-3103",
  incident_id: null,
  status: "SENT",
  sent_at: SENT,
  escalate_after_s: 20,
  personnel: { recipients: 17, safe: 16 - pending, need_help: 1, pending, accounted_pct: 0 },
  citizens: { recipients: 0, safe: 0, need_help: 0, pending: 0, accounted_pct: 0 },
});
const hana = (escalated: boolean) => ({ escalated }) as CheckinPerson;

describe("escalation status", () => {
  const at = (s: number) => new Date(SENT).getTime() + s * 1000;

  it("comes from the escalation records, not the clock", () => {
    expect(escalationText(summary(1), [hana(false)], at(5))).toMatch(/^Auto-escalation at /);
    expect(escalationText(summary(1), [hana(false)], at(25))).toBe("Escalation due");
    expect(escalationText(summary(1), [hana(true)], at(25))).toBe("Escalated");
    expect(escalationText(summary(0), [], at(25))).toBe("—");
  });
});
