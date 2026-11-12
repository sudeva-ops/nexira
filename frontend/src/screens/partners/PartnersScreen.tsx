import { Button, Icon } from "@blueprintjs/core";
import { useState } from "react";

import { useCampaigns, useCheckinResponses } from "../../api/checkin";
import { ApiError } from "../../api/client";
import { useIncident } from "../../api/intel";
import { useMe } from "../../api/me";
import {
  coverageSummary,
  OPEN,
  type PartnerRequest,
  type RequestStatus,
  SERVICE_LABEL,
  slaText,
  STATUS_LABEL,
  useCoverage,
  usePartnerRequests,
  usePartners,
  useRequestAction,
} from "../../api/partners";
import { canRequestPartner } from "../../api/permissions";
import { formatStamp } from "../../app/time";
import { initials, plural } from "../../ui/format";
import { FlashRow } from "../../ui/motion";
import { Ring } from "../../ui/Ring";
import { remaining } from "../../ui/spark";
import { useNow } from "../../ui/useNow";
import { Card, Kpi } from "../../ui/primitives";
import { SkeletonRows } from "../../ui/Skeleton";
import { type RequestFor, RequestDialog } from "./RequestDialog";
import { TileRow } from "../../ui/TileRow";
import { Empty } from "../../ui/Empty";

const STATUS_SEV: Record<RequestStatus, string> = {
  REQUESTED: "med",
  ACCEPTED: "low",
  EN_ROUTE: "high",
  COMPLETED: "ok",
  DECLINED: "crit",
  CANCELLED: "",
};
const LOGO = ["#238551", "#2D72D2", "#634DBF", "#C87619", "#147EB3"];

function hhmm(iso: string): string {
  return formatStamp(iso).replace(/:\d\d (?=\S+$)/, " ");
}

/** AS-06: someone answered HELP on the latest check-in and has no request yet. */
function useSos(requests: PartnerRequest[]) {
  const checkin = (useCampaigns().data ?? []).find((c) => c.campaign_type === "CHECKIN");
  const responses = useCheckinResponses(checkin?.id).data ?? [];
  const helped = new Set(requests.filter((r) => r.person_id && r.status !== "CANCELLED").map((r) => r.person_id));
  const waiting = responses.filter(
    (r) => r.status === "NEED_HELP" && r.person_type !== "CITIZEN" && !helped.has(r.person_id),
  );
  return { waiting, incidentId: checkin?.incident_id ?? null };
}

function RequestRow({ r, canAct }: { r: PartnerRequest; canAct: boolean }) {
  const action = useRequestAction();
  const arriving = !!r.eta && !!r.accepted_at && (r.status === "ACCEPTED" || r.status === "EN_ROUTE");
  const now = useNow(arriving);
  return (
    <FlashRow
      data-request={r.reference}
      watch={`${r.status} ${r.eta}`}
      tone={r.status === "DECLINED" ? "danger" : r.status === "COMPLETED" ? "success" : "info"}
    >
      <td className="nx-mono nx-dim">{r.reference}</td>
      <td>
        <b>{r.partner_name}</b>
      </td>
      <td>
        {SERVICE_LABEL[r.service]}
        {r.note ? ` · ${r.note}` : ""}
        <div className="nx-dim">
          {r.person_name ? `${r.person_name}${r.person_role ? ` (${r.person_role})` : ""} · ` : ""}
          {r.mission_code} mission{r.incident_reference ? ` · ${r.incident_reference}` : ""}
          {r.created_by_type === "PLAYBOOK" ? " · by playbook" : ""}
        </div>
      </td>
      <td>
        <span className={`nx-sev ${STATUS_SEV[r.status]}`}>{STATUS_LABEL[r.status].toUpperCase()}</span>
      </td>
      <td className="nx-mono nx-nowrap">
        {arriving && r.accepted_at && r.eta && (
          <Ring left={remaining(r.accepted_at, r.eta, now)} label="Time until the partner arrives" />
        )}{" "}
        {r.eta && OPEN.includes(r.status) ? hhmm(r.eta) : "—"}
      </td>
      <td>
        {canAct && r.status === "EN_ROUTE" && (
          <Button
            size="small"
            text="Complete"
            loading={action.isPending}
            onClick={() => action.mutate({ id: r.id, action: "complete" })}
          />
        )}
        {canAct && OPEN.includes(r.status) && (
          <Button
            size="small"
            minimal
            intent="danger"
            text="Cancel"
            loading={action.isPending}
            onClick={() => action.mutate({ id: r.id, action: "cancel" })}
          />
        )}
        {action.isError && (
          <div className="nx-error">{action.error instanceof ApiError ? action.error.message : "Not done"}</div>
        )}
      </td>
    </FlashRow>
  );
}

/** Assistance Partners (AS-01..08; D-36). Partners and their answers are simulated (D-19). */
export function PartnersScreen() {
  const me = useMe().data;
  const partners = usePartners();
  const list = partners.data ?? [];
  const requests = usePartnerRequests().data ?? [];
  const coverage = coverageSummary(useCoverage().data ?? []);
  const sos = useSos(requests);
  const incident = useIncident(sos.incidentId ?? undefined).data;
  const [target, setTarget] = useState<RequestFor | null>(null);
  const open = requests.filter((r) => OPEN.includes(r.status));
  const first = sos.waiting[0];
  const mayRequestAnywhere = canRequestPartner(me, null);

  return (
    <div className="nx-pad">
      {first && canRequestPartner(me, incident?.mission_id ?? null) && (
        <div className="nx-banner red nx-mb" role="alert">
          <Icon icon="warning-sign" />
          <div className="nx-grow">
            <b>
              {first.full_name}
              {first.role_title ? ` (${first.role_title})` : ""} needs help
            </b>{" "}
            on {incident?.reference ?? "the latest check-in"}
            {sos.waiting.length > 1 ? `, and ${sos.waiting.length - 1} more` : ""}. The platform suggests the nearest
            capable partner; you decide.
          </div>
          <Button
            intent="danger"
            icon="heart"
            text="Request help"
            onClick={() =>
              setTarget({
                kind: "sos",
                personId: first.person_id,
                personName: first.full_name,
                incidentId: sos.incidentId,
              })
            }
          />
        </div>
      )}
      <TileRow>
        <Kpi
          icon="heart"
          label="Contracted partners"
          value={list.length}
          detail="Medical · evacuation · security · welfare"
        />
        <Kpi
          icon="flash"
          label="Active requests"
          value={open.length}
          detail={open.length ? `${open.filter((r) => r.status === "EN_ROUTE").length} en route` : "No active requests"}
          alert={open.length > 0}
        />
        <Kpi
          icon="globe"
          label="Coverage of missions"
          value={`${coverage.covered} / ${coverage.total}`}
          detail={coverage.gaps.length ? `${coverage.gaps.length} gaps flagged` : "Every service everywhere"}
        />
        <Kpi icon="satellite" label="Partner systems" value="Simulated" detail="No partner is contacted (D-36)" />
      </TileRow>

      <div className="nx-partners-grid">
        <Card icon="heart" title="Partner network" sub="Fictional partners · simulated">
          {partners.isLoading ? (
            <SkeletonRows />
          ) : list.length === 0 ? (
            <Empty>No partners. Seeded with `make reset-demo` (D-36).</Empty>
          ) : (
            <div className="nx-plist" aria-label="Partner network">
              {list.map((p, n) => {
                const engaged = open.some((r) => r.partner_id === p.id);
                return (
                  <div key={p.id} className="nx-pp" data-partner={p.code}>
                    <div className="nx-av nx-logo" style={{ background: LOGO[n % LOGO.length] }}>
                      {initials(p.name)}
                    </div>
                    <div className="nx-grow">
                      <div className="n">{p.name}</div>
                      <div className="r">{p.services.map((s) => SERVICE_LABEL[s]).join(" · ")}</div>
                      <div className="r nx-dim">
                        {p.coverage.length} countries · {slaText(p.sla_minutes)} · {p.hours}
                      </div>
                    </div>
                    <span className={`nx-sev ${engaged ? "med" : "ok"}`}>{engaged ? "ENGAGED" : "AVAILABLE"}</span>
                    {mayRequestAnywhere || me?.roles.some((r) => r.code === "HEAD_OF_MISSION") ? (
                      <Button size="small" text="Request" onClick={() => setTarget({ kind: "partner", partner: p })} />
                    ) : null}
                  </div>
                );
              })}
            </div>
          )}
        </Card>
        <div className="nx-col">
          <Card icon="flash" title="Requests" chip={{ text: plural(requests.length, "request"), tone: "live" }}>
            {requests.length === 0 ? (
              <Empty>No requests. Partners are engaged by playbooks or by a person.</Empty>
            ) : (
              <table className="nx-table-plain" aria-label="Partner requests">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Partner</th>
                    <th>Request</th>
                    <th>Status</th>
                    <th>ETA</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {requests.map((r) => (
                    <RequestRow key={r.id} r={r} canAct={canRequestPartner(me, r.mission_id)} />
                  ))}
                </tbody>
              </table>
            )}
          </Card>
          <Card icon="map" title="Coverage gaps" sub="Per mission and service (AS-07)">
            {coverage.gaps.length === 0 ? (
              <div className="nx-feed-empty nx-dim">Every mission has every service.</div>
            ) : (
              <ul className="nx-bd nx-gaps" aria-label="Coverage gaps">
                {coverage.gaps.map((g) => (
                  <li key={g.mission_id}>
                    <b>
                      {g.city} ({g.code})
                    </b>{" "}
                    · no {g.missing.map((s) => SERVICE_LABEL[s].toLowerCase()).join(", ")}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
      {target && <RequestDialog target={target} onClose={() => setTarget(null)} />}
    </div>
  );
}
