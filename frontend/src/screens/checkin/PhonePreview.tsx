import { HTMLSelect, Icon } from "@blueprintjs/core";
import { useState } from "react";

import type { Campaign, CheckinPerson } from "../../api/checkin";
import { useRespond } from "../../api/checkin";
import { ApiError } from "../../api/client";
import { formatTime, HOME_TZ } from "../../app/time";

/** D-28: what staff see on their phone. Answering here records the answer for the
 *  chosen recipient through POST /api/checkin/{id}/respond, as that person would. */
export function PhonePreview({
  campaign,
  pending,
  canAnswer,
}: {
  campaign: Campaign;
  pending: CheckinPerson[];
  canAnswer: boolean;
}) {
  const [personId, setPersonId] = useState("");
  const [answered, setAnswered] = useState<string | null>(null);
  const respond = useRespond(campaign.id);
  const chosen = personId || pending[0]?.person_id || "";
  const now = new Date();
  const send = (status: "SAFE" | "NEED_HELP") =>
    respond.mutate(
      { person_id: chosen, status },
      { onSuccess: () => setAnswered(status === "SAFE" ? "safe" : "help") },
    );

  return (
    <div>
      <div className="nx-phone-label">WHAT STAFF SEE</div>
      <div className="nx-phone" aria-label="Phone preview">
        <div className="notch" />
        <div className="scr">
          <div className="time">{formatTime(now, HOME_TZ).slice(0, 5)}</div>
          <div className="date">
            {now.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })}
          </div>
          {answered ? (
            <div className="ntf nx-center">
              <div className={`nx-phone-ok ${answered}`}>
                <Icon icon={answered === "safe" ? "tick" : "warning-sign"} />
              </div>
              <div className="b">Thank you — status shared</div>
              <div className="x">
                {answered === "safe"
                  ? "Your mission security team can see you are safe."
                  : "Your mission security team has been told you need help."}
              </div>
              <button type="button" className="nx-phone-reset" onClick={() => setAnswered(null)}>
                Answer for someone else
              </button>
            </div>
          ) : (
            <div className="ntf">
              <div className="h">
                <span className="ap">
                  <Icon icon="shield" size={11} />
                </span>
                NEXIRA · SAFETY CHECK-IN
                <span className="nx-push">now</span>
              </div>
              <div className="b">⚠ {campaign.reference}</div>
              <div className="x">
                {campaign.message} <b>Are you safe?</b>
              </div>
              {canAnswer && pending.length > 0 ? (
                <>
                  <HTMLSelect
                    className="nx-phone-who"
                    aria-label="Answer as"
                    value={chosen}
                    onChange={(e) => setPersonId(e.currentTarget.value)}
                    options={pending.map((p) => ({ value: p.person_id, label: p.full_name }))}
                  />
                  <div className="acts">
                    <button type="button" className="safe" onClick={() => send("SAFE")} disabled={respond.isPending}>
                      I'm safe
                    </button>
                    <button type="button" className="help" onClick={() => send("NEED_HELP")} disabled={respond.isPending}>
                      I need help
                    </button>
                  </div>
                  {respond.isError && (
                    <div className="nx-error">
                      {respond.error instanceof ApiError ? respond.error.message : "Not recorded"}
                    </div>
                  )}
                </>
              ) : (
                <div className="x nx-dim">
                  {canAnswer ? "Everyone in the preview list has answered." : "Preview only."}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
      {canAnswer && <div className="nx-phone-hint">Simulated device · answers go through the API</div>}
    </div>
  );
}
