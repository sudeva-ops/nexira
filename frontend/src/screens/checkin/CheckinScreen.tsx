import { Button, HTMLSelect, NonIdealState } from "@blueprintjs/core";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  useCampaigns,
  useCheckinResponses,
  useCheckinSummary,
  useEscalate,
  usePendingPersonnel,
} from "../../api/checkin";
import { ApiError } from "../../api/client";
import { useIncident } from "../../api/intel";
import { useMe } from "../../api/me";
import { canRecordCheckin, canRequestPartner } from "../../api/permissions";
import { formatTime, HOME_TZ } from "../../app/time";
import { Clip } from "../../ui/Clip";
import { initials, personTypeLabel } from "../../ui/format";
import { Card, ExerciseTag, Kpi } from "../../ui/primitives";
import { Donut } from "./Donut";
import { escalationText } from "./escalation";
import { type RequestFor, RequestDialog } from "../partners/RequestDialog";
import { PhonePreview } from "./PhonePreview";
import { TileRow } from "../../ui/TileRow";
import { Empty } from "../../ui/Empty";
import { SkeletonRows } from "../../ui/Skeleton";

const SAFE = "#32A467";
const HELP = "#E76A6E";
const PENDING = "#404854";

/** DC-01, DC-03 (D-56; plan G-4): with no check-in, the screen's normal layout with nothing in it
 *  yet, not a blank page. Nothing is counted, so every figure is "—". */
function AtRest() {
  const none = "No check-in running";
  return (
    <div className="nx-pad">
      <TileRow label="Personnel figures">
        <Kpi icon="people" label="Personnel accounted" value="—" detail={none} />
        <Kpi icon="tick" label="Safe" value="—" detail={none} />
        <Kpi icon="warning-sign" label="Need help" value="—" detail={none} />
        <Kpi icon="time" label="No response" value="—" detail={none} />
      </TileRow>
      <div className="nx-cigrid">
        <Card icon="people" title="Mission personnel" className="nx-span2">
          <Empty>
            No safety check-in yet. Playbooks send one (PB-07 step 5); personnel and citizens are
            counted here as they answer.
          </Empty>
        </Card>
        <Card icon="feed" title="Live responses" className="nx-side nx-responses">
          <Empty>Answers appear here as they arrive, newest first.</Empty>
        </Card>
      </div>
    </div>
  );
}

/** Safety Check-in (CHK-01..03, D-28). */
export function CheckinScreen() {
  const [params, setParams] = useSearchParams();
  const campaigns = useCampaigns();
  const checkins = (campaigns.data ?? []).filter((c) => c.campaign_type === "CHECKIN");
  const campaign = checkins.find((c) => c.id === params.get("campaign")) ?? checkins[0];
  const summary = useCheckinSummary(campaign?.id).data;
  const responses = useCheckinResponses(campaign?.id).data ?? [];
  const pending = usePendingPersonnel(campaign?.id).data ?? [];
  const incident = useIncident(campaign?.incident_id ?? undefined).data;
  const me = useMe().data;
  const escalate = useEscalate(campaign?.id ?? "");
  const canRecord = !!incident && canRecordCheckin(me, incident.mission_id);
  // AS-06: next to each HELP, a partner request (suggested; a person decides).
  const canRequest = !!incident && canRequestPartner(me, incident.mission_id);
  const [helpFor, setHelpFor] = useState<RequestFor | null>(null);

  if (campaigns.isPending) return <SkeletonRows rows={6} />;
  if (campaigns.isError) return <NonIdealState icon="error" title="The check-ins could not be loaded" />;
  if (!campaign) return <AtRest />; // loaded, and no check-in yet
  if (!summary) return <SkeletonRows rows={6} />;
  const p = summary.personnel;
  const c = summary.citizens;
  return (
    <div className="nx-pad">
      {checkins.length > 1 && (
        <HTMLSelect
          aria-label="Check-in"
          value={campaign.id}
          onChange={(e) => setParams({ campaign: e.currentTarget.value })}
          options={checkins.map((x) => ({ value: x.id, label: `${x.reference} · ${x.recipients} recipients${x.exercise ? " · EXERCISE" : ""}` }))}
        />
      )}
      {summary.exercise && (
        <div className="nx-row nx-mb">
          <ExerciseTag on />
          <span className="nx-dim">This check-in belongs to an exercise; it is left out of leadership figures.</span>
        </div>
      )}
      <TileRow label="Personnel figures">
        <Kpi
          icon="people"
          label="Personnel accounted"
          value={`${Math.round(p.accounted_pct)}%`}
          detail={`${p.safe + p.need_help} of ${p.recipients} responded`}
        />
        <Kpi icon="tick" label="Safe" value={<span className="nx-safe">{p.safe}</span>} detail="Confirmed via app / SMS" />
        <Kpi
          icon="warning-sign"
          label="Need help"
          value={<span className="nx-help">{p.need_help}</span>}
          alert={p.need_help > 0}
          detail={p.need_help ? "On the incident timeline" : "—"}
        />
        <Kpi
          icon="time"
          label="No response"
          value={<span className="nx-pending">{p.pending}</span>}
          detail={escalationText(summary, pending)}
        />
      </TileRow>
      <div className="nx-cigrid">
        <Card
          icon="people"
          title="Mission personnel"
          sub={`${campaign.reference} · ${incident?.reference ?? ""} · ${p.recipients}`}
        >
          <div className="nx-bd nx-row nx-ci-donut">
            <div className="nx-donut">
              <Donut
                values={[p.safe, p.need_help, p.pending]}
                colours={[SAFE, HELP, PENDING]}
                label={`${p.safe} safe, ${p.need_help} need help, ${p.pending} pending`}
              />
              <div className="nx-donut-c">
                <div className="nx-mono">{Math.round(p.accounted_pct)}%</div>
                <div className="nx-dim">accounted</div>
              </div>
            </div>
            <div className="nx-ci-legend">
              <div className="nx-row">
                <span className="nx-chip"><i style={{ background: SAFE }} />Safe</span>
                <b>{p.safe}</b>
              </div>
              <div className="nx-row">
                <span className="nx-chip"><i style={{ background: HELP }} />Need help</span>
                <b>{p.need_help}</b>
              </div>
              <div className="nx-row">
                <span className="nx-chip"><i style={{ background: PENDING }} />Pending</span>
                <b>{p.pending}</b>
              </div>
              {canRecord && p.pending + c.pending > 0 && (
                <Button
                  size="small"
                  text="Escalate non-responders"
                  loading={escalate.isPending}
                  onClick={() => escalate.mutate(undefined)}
                />
              )}
              {escalate.isSuccess && (
                <span className="nx-dim">
                  {escalate.data.personnel.length + (escalate.data.citizens ? 1 : 0)
                    ? "Escalated"
                    : "Already escalated"}
                </span>
              )}
              {escalate.isError && (
                <span className="nx-error">
                  {escalate.error instanceof ApiError ? escalate.error.message : "Not escalated"}
                </span>
              )}
            </div>
          </div>
          <div className="nx-bd">
            <div className="nx-lbl">Registered citizens · {c.recipients}</div>
            <div className="nx-bar nx-citizens" aria-label="Citizens">
              <i style={{ width: `${(c.safe / (c.recipients || 1)) * 100}%`, background: SAFE }} />
              <i style={{ width: `${(c.need_help / (c.recipients || 1)) * 100}%`, background: HELP }} />
            </div>
            <div className="nx-row nx-dim nx-ci-counts">
              <span><b className="nx-safe">{c.safe}</b> safe</span>
              <span><b className="nx-help">{c.need_help}</b> need help</span>
              <span><b>{c.pending}</b> pending</span>
              <span className="nx-grow" />
              <span>{campaign.channels.join(" · ")} (simulated)</span>
            </div>
          </div>
        </Card>
        <Card
          icon="feed"
          title="Live responses"
          className="nx-side nx-responses"
          chip={{ text: "Live", tone: "live" }}
        >
          <div className="nx-plist" aria-label="Live responses">
            {responses.length ? (
              responses.map((r) => (
                <div key={r.person_id} className="nx-pp">
                  <div className="nx-av" style={{ background: "#4C90F033", color: "#8ABBFF" }}>
                    {initials(r.full_name)}
                  </div>
                  <div className="nx-grow">
                    <div className="n">
                      <Clip text={r.full_name} />
                    </div>
                    <div className="r">{r.role_title ?? personTypeLabel(r.person_type)}</div>
                  </div>
                  <span className={`nx-sev ${r.status === "SAFE" ? "ok" : "crit"}`}>
                    {r.status === "SAFE" ? "SAFE" : "NEEDS HELP"}
                  </span>
                  {canRequest && r.status === "NEED_HELP" && (
                    <Button
                      size="small"
                      minimal
                      icon="heart"
                      text="Request partner"
                      onClick={() =>
                        setHelpFor({
                          kind: "sos",
                          personId: r.person_id,
                          personName: r.full_name,
                          incidentId: campaign.incident_id,
                        })
                      }
                    />
                  )}
                  <span className="nx-dim nx-mono nx-ci-time">
                    {r.responded_at ? formatTime(new Date(r.responded_at), HOME_TZ) : ""}
                  </span>
                </div>
              ))
            ) : (
              <div className="nx-feed-empty nx-dim">Waiting for responses…</div>
            )}
          </div>
        </Card>
        <PhonePreview campaign={campaign} pending={pending} canAnswer={canRecord} />
      </div>
      {helpFor && <RequestDialog target={helpFor} onClose={() => setHelpFor(null)} />}
    </div>
  );
}
