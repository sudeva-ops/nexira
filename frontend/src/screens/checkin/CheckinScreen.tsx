import { Button, HTMLSelect, NonIdealState, Spinner } from "@blueprintjs/core";
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
import { canRecordCheckin } from "../../api/permissions";
import { formatTime, HOME_TZ } from "../../app/time";
import { initials, personTypeLabel } from "../../ui/format";
import { Card, Kpi } from "../../ui/primitives";
import { Donut } from "./Donut";
import { escalationText } from "./escalation";
import { PhonePreview } from "./PhonePreview";

const SAFE = "#32A467";
const HELP = "#E76A6E";
const PENDING = "#404854";

/** Safety Check-in (CHK-01..03, D-28). */
export function CheckinScreen() {
  const [params, setParams] = useSearchParams();
  const checkins = (useCampaigns().data ?? []).filter((c) => c.campaign_type === "CHECKIN");
  const campaign = checkins.find((c) => c.id === params.get("campaign")) ?? checkins[0];
  const summary = useCheckinSummary(campaign?.id).data;
  const responses = useCheckinResponses(campaign?.id).data ?? [];
  const pending = usePendingPersonnel(campaign?.id).data ?? [];
  const incident = useIncident(campaign?.incident_id ?? undefined).data;
  const me = useMe().data;
  const escalate = useEscalate(campaign?.id ?? "");
  const canRecord = !!incident && canRecordCheckin(me, incident.mission_id);

  if (!campaign) {
    return (
      <NonIdealState
        icon="tick-circle"
        title="No active safety check-in"
        description="Check-ins are launched by playbooks (PB-07 step 5)."
      />
    );
  }
  if (!summary) return <Spinner />;
  const p = summary.personnel;
  const c = summary.citizens;
  return (
    <div className="nx-pad">
      {checkins.length > 1 && (
        <HTMLSelect
          aria-label="Check-in"
          value={campaign.id}
          onChange={(e) => setParams({ campaign: e.currentTarget.value })}
          options={checkins.map((x) => ({ value: x.id, label: `${x.reference} · ${x.recipients} recipients` }))}
        />
      )}
      <div className="nx-g4" aria-label="Personnel figures">
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
      </div>
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
          actions={<span className="nx-chip"><i style={{ background: SAFE }} />Live</span>}
        >
          <div className="nx-plist" aria-label="Live responses">
            {responses.length ? (
              responses.map((r) => (
                <div key={r.person_id} className="nx-pp">
                  <div className="nx-av" style={{ background: "#4C90F033", color: "#8ABBFF" }}>
                    {initials(r.full_name)}
                  </div>
                  <div className="nx-grow">
                    <div className="n">{r.full_name}</div>
                    <div className="r">{r.role_title ?? personTypeLabel(r.person_type)}</div>
                  </div>
                  <span className={`nx-sev ${r.status === "SAFE" ? "ok" : "crit"}`}>
                    {r.status === "SAFE" ? "SAFE" : "NEEDS HELP"}
                  </span>
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
    </div>
  );
}
