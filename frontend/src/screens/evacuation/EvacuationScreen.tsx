import { Button, HTMLSelect, Icon, InputGroup, NonIdealState } from "@blueprintjs/core";
import { type CSSProperties, type ReactNode, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { ApiError } from "../../api/client";
import {
  CATEGORY_LABEL,
  defaultMission,
  type Evacuation,
  type EvacuationDetail,
  type EvacuationPermissions,
  LIVE,
  manifestText,
  type Plan,
  total,
  useAdvance,
  useCheckIn,
  useConfirmEvacuation,
  useEvacuation,
  useEvacuationPermissions,
  useEvacuations,
  usePlans,
  useRequestEvacuation,
  useStandDown,
  waitingFor,
  ROLE_LABEL,
} from "../../api/evacuations";
import { type Mission, useMissions } from "../../api/people";
import { formatStamp } from "../../app/time";
import { FlashRow } from "../../ui/motion";
import { Card, Kpi } from "../../ui/primitives";
import { SkeletonRows } from "../../ui/Skeleton";

const ROLE_SEV: Record<string, string> = { PRIMARY: "ok", BACKUP: "low", CONTINGENCY: "low" };
const MESSAGE_STATUS: Record<string, string> = {
  PENDING_APPROVAL: "awaiting a second person",
  SENDING: "sending",
  SENT: "sent",
  CANCELLED: "withdrawn",
  DRAFT: "returned to draft",
};

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "Not done";
}

/** EV-02, EV-07: what is going on, and Activate / Confirm / Withdraw when allowed. */
function Banner({
  plan,
  mission,
  evacuation,
  allowed,
}: {
  plan: Plan | undefined;
  mission: Mission | undefined;
  evacuation: Evacuation | undefined;
  allowed: EvacuationPermissions | undefined;
}) {
  const request = useRequestEvacuation();
  const confirm = useConfirmEvacuation();
  const failed = [request, confirm].find((m) => m.isError);
  const live = evacuation && LIVE.includes(evacuation.status) ? evacuation : undefined;
  const reference = plan?.reference ?? "The plan";
  const primary = plan?.options[0];

  let tone = "";
  let body: ReactNode;
  if (live?.status === "PENDING_ACTIVATION") {
    tone = "amber";
    body = (
      <>
        <b>
          Activation of {reference} requested by {live.requested_by_name ?? "—"} (
          {ROLE_LABEL[live.requested_role] ?? live.requested_role}).
        </b>{" "}
        Waiting for the {waitingFor(live)} to confirm: two people activate an evacuation (D-40).
      </>
    );
  } else if (live?.status === "ACTIVE") {
    tone = "red";
    body = (
      <>
        <b>Evacuation {reference} in progress.</b> {live.checked_in} of {total(live)} evacuees checked in.
      </>
    );
  } else if (evacuation?.status === "COMPLETED") {
    tone = "green";
    body = (
      <>
        <b>{evacuation.reference} complete: the evacuees have arrived.</b> {plan?.destination}.
      </>
    );
  } else if (mission?.incident_id) {
    tone = "amber";
    body = (
      <>
        <b>Evacuation plan {reference} is ready but not activated.</b> {plan?.route_label}
        {primary && ` · ${primary.label}${primary.partner_name ? ` with ${primary.partner_name}` : ""}`}.
        {evacuation?.status === "STOOD_DOWN" && ` The last evacuation was stood down: ${evacuation.stood_down_reason}`}
      </>
    );
  } else {
    body = (
      <>
        <b>No active evacuation.</b> Plans are pre-built for every mission.
      </>
    );
  }

  return (
    <div className={`nx-banner nx-mb ${tone}`} role="status" data-testid="evacuation-banner">
      <Icon icon="airplane" />
      <div className="nx-grow">
        {body}
        {failed && <div className="nx-error">{errorText(failed.error)}</div>}
      </div>
      {!live && allowed?.activate_evacuation && mission && (
        <Button
          intent="danger"
          size="small"
          icon="airplane"
          text="Activate evacuation"
          loading={request.isPending}
          onClick={() => request.mutate(mission.id)}
        />
      )}
      {live?.status === "PENDING_ACTIVATION" && allowed?.confirm_evacuation && (
        <Button
          intent="danger"
          size="small"
          text="Confirm activation"
          loading={confirm.isPending}
          onClick={() => confirm.mutate(live.id)}
        />
      )}
    </div>
  );
}

function ManifestCard({
  detail,
  allowed,
  loading,
}: {
  detail: EvacuationDetail | undefined;
  allowed: EvacuationPermissions | undefined;
  loading: boolean;
}) {
  const checkIn = useCheckIn();
  const active = detail?.status === "ACTIVE";
  return (
    <Card
      icon="people"
      title="Evacuation manifest"
      sub={detail ? `${detail.reference} · locked at activation` : "Mission personnel, dependants & citizens"}
    >
      {loading ? (
        <SkeletonRows />
      ) : !detail || detail.status === "PENDING_ACTIVATION" ? (
        <NonIdealState
          icon="people"
          title="No manifest yet"
          description="It is built and locked when two people activate the evacuation (EV-03)."
        />
      ) : (
        <>
          {!detail.names_shown && (
            <div className="nx-bd nx-dim" role="note">
              Names are shown to responders and the mission&apos;s Head of Mission; you see counts only.
            </div>
          )}
          <table className="nx-table-plain nx-ev-table" aria-label="Evacuation manifest">
            <thead>
              <tr>
                <th>Name</th>
                <th>Category</th>
                <th>Travel docs</th>
                <th>Seat</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {detail.manifest.map((e) => (
                <FlashRow key={e.id} data-entry={e.id} watch={`${e.status} ${e.seat ?? ""}`} tone="success">
                  <td>{e.name ? <b>{e.name}</b> : <span className="nx-dim">—</span>}</td>
                  <td>{e.category ? CATEGORY_LABEL[e.category] : "—"}</td>
                  <td>
                    {e.document_flag === null ? (
                      "—"
                    ) : e.document_flag ? (
                      <span className="nx-sev med">EXPIRING</span>
                    ) : (
                      <span className="nx-sev ok">VALID</span>
                    )}
                  </td>
                  <td className="nx-mono">{e.status === "CHECKED_IN" ? (e.seat ?? "No seat") : "—"}</td>
                  <td className="nx-nowrap">
                    {e.status === "CHECKED_IN" ? (
                      <span className="nx-sev ok">CHECKED IN</span>
                    ) : (
                      <span className="nx-sev med">EXPECTED</span>
                    )}
                    {active && e.status === "EXPECTED" && allowed?.check_in_evacuee && (
                      <Button
                        minimal
                        size="small"
                        text="Check in"
                        loading={checkIn.isPending && checkIn.variables?.entry === e.id}
                        onClick={() => checkIn.mutate({ id: detail.id, entry: e.id })}
                      />
                    )}
                  </td>
                </FlashRow>
              ))}
            </tbody>
          </table>
          {checkIn.isError && <div className="nx-bd nx-error">{errorText(checkIn.error)}</div>}
        </>
      )}
    </Card>
  );
}

function SequenceCard({
  evacuation,
  plan,
  allowed,
}: {
  evacuation: Evacuation | undefined;
  plan: Plan | undefined;
  allowed: EvacuationPermissions | undefined;
}) {
  const advance = useAdvance();
  const next = evacuation?.status === "ACTIVE" && evacuation.step !== null ? evacuation.step + 1 : null;
  const nextName = next ? evacuation?.steps[next - 1]?.name : undefined;
  return (
    <Card icon="route" title="Evacuation sequence" sub={plan ? `${plan.muster_name} · ${plan.route_label}` : undefined}>
      <div className="nx-bd">
        <div className="nx-tl" aria-label="Evacuation sequence">
          {(evacuation?.steps ?? []).map((s) => (
            <div key={s.step} style={{ "--c": s.at ? "#32A467" : "#404854" } as CSSProperties} data-step={s.step}>
              <b className={s.at ? undefined : "nx-dim"}>{s.name}</b>
              <br />
              <span>{s.at ? formatStamp(s.at) : "—"}</span>
            </div>
          ))}
          {!evacuation && <div className="nx-dim">Starts when the evacuation is activated.</div>}
        </div>
        {next && next <= 6 && allowed?.advance_evacuation && evacuation && (
          <Button
            size="small"
            icon="arrow-right"
            text={`Next step: ${nextName}`}
            loading={advance.isPending}
            onClick={() => advance.mutate({ id: evacuation.id, step: next })}
          />
        )}
        {advance.isError && <div className="nx-error">{errorText(advance.error)}</div>}
      </div>
    </Card>
  );
}

function OptionsCard({ plan, evacuation }: { plan: Plan | undefined; evacuation: Evacuation | undefined }) {
  const status = (partner: string | null) =>
    evacuation?.partner_requests.find((r) => r.partner_name === partner)?.status;
  return (
    <Card icon="globe" title="Options" sub={plan ? `${plan.reference} · to ${plan.destination} (simulated)` : undefined}>
      {!plan ? (
        <div className="nx-bd nx-dim">No evacuation plan for this mission.</div>
      ) : (
        <table className="nx-table-plain nx-ev-table" aria-label="Evacuation options">
          <tbody>
            {plan.options.map((o) => (
              <tr key={o.role} data-option={o.role}>
                <td>
                  {o.label}
                  <div className="nx-dim">
                    {o.seats ? `${o.seats} seats · ` : ""}
                    {o.partner_name
                      ? `${o.partner_name}${status(o.partner_name) ? ` · ${status(o.partner_name)?.toLowerCase().replace("_", " ")}` : ""}`
                      : "No partner"}
                  </div>
                </td>
                <td className="nx-ev-right">
                  <span className={`nx-sev ${ROLE_SEV[o.role] ?? "low"}`}>{o.role}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {evacuation?.message_reference && (
        <div className="nx-bd nx-dim">
          Movement message {evacuation.message_reference} ·{" "}
          {MESSAGE_STATUS[evacuation.message_status ?? ""] ?? evacuation.message_status} ·{" "}
          <Link to="/notifications">Mass Notification</Link>
        </div>
      )}
    </Card>
  );
}

/** EV-07: before the flight, with a reason; a pending request is withdrawn the same way. */
function StandDown({ evacuation, allowed }: { evacuation: Evacuation; allowed: EvacuationPermissions | undefined }) {
  const standDown = useStandDown();
  const [reason, setReason] = useState("");
  if (!allowed?.stand_down_evacuation || !LIVE.includes(evacuation.status)) return null;
  const label = evacuation.status === "PENDING_ACTIVATION" ? "Withdraw request" : "Stand down";
  return (
    <Card icon="disable" title={label}>
      <div className="nx-bd nx-row nx-ev-standdown">
        <InputGroup
          aria-label="Reason"
          maxLength={500}
          placeholder="Reason (audited)"
          value={reason}
          onChange={(e) => setReason(e.currentTarget.value)}
        />
        <Button
          size="small"
          intent="danger"
          text={label}
          disabled={!reason.trim()}
          loading={standDown.isPending}
          onClick={() => standDown.mutate({ id: evacuation.id, reason: reason.trim() })}
        />
      </div>
      {standDown.isError && <div className="nx-bd nx-error">{errorText(standDown.error)}</div>}
    </Card>
  );
}

/** Evacuation Management (EV-01..09; D-40). Plans, scanner, charter and convoy are simulated (D-19). */
export function EvacuationScreen() {
  const [params, setParams] = useSearchParams();
  const missions = [...(useMissions().data ?? [])].sort((a, b) => a.code.localeCompare(b.code));
  const all = useEvacuations();
  const plans = usePlans().data ?? [];
  const missionId =
    params.get("mission") ?? (all.data && missions.length ? defaultMission(all.data, missions) : undefined);
  const mission = missions.find((m) => m.id === missionId);
  const plan = plans.find((p) => p.mission_id === missionId);
  const latest = (all.data ?? []).find((e) => e.mission_id === missionId);
  const detail = useEvacuation(latest?.id);
  const allowed = useEvacuationPermissions(missionId).data;
  const shown = detail.data ?? latest;
  const primary = plan?.options[0];

  return (
    <div className="nx-pad">
      <div className="nx-row nx-mb nx-ev-picker">
        <span className="nx-dim">Mission</span>
        <HTMLSelect
          minimal
          aria-label="Mission"
          value={missionId ?? ""}
          onChange={(e) => setParams({ mission: e.currentTarget.value })}
          options={missions.map((m) => ({ value: m.id, label: `${m.code} · ${m.city}` }))}
        />
        <span className="nx-grow" />
        <span className="nx-dim">{plan?.source ?? "Illustrative evacuation plan (simulated)"}</span>
      </div>
      <Banner plan={plan} mission={mission} evacuation={latest} allowed={allowed} />
      <div className="nx-g4 nx-mb">
        <Kpi
          icon="people"
          label="Evacuees on manifest"
          value={shown && shown.status !== "PENDING_ACTIVATION" ? total(shown) : "—"}
          detail={shown && shown.status !== "PENDING_ACTIVATION" ? manifestText(shown) : "Built at activation"}
        />
        <Kpi
          icon="tick-circle"
          label="Checked in"
          value={shown?.activated_at ? `${shown.checked_in} / ${total(shown)}` : "—"}
          detail={shown?.activated_at ? "At the muster point" : "—"}
        />
        <Kpi
          icon="airplane"
          label="Seats available"
          value={primary?.seats ?? "—"}
          detail={primary ? `${primary.label} (simulated)` : "No primary option"}
        />
        <Kpi
          icon="warning-sign"
          label="Documents flagged"
          value={shown?.activated_at ? shown.documents_flagged : "—"}
          detail="Could block evacuation (DX-03)"
          alert={!!shown?.documents_flagged}
        />
      </div>
      <div className="nx-ev-grid">
        <ManifestCard detail={detail.data} allowed={allowed} loading={!!latest && detail.isLoading} />
        <div className="nx-col">
          <SequenceCard evacuation={shown?.activated_at ? shown : undefined} plan={plan} allowed={allowed} />
          <OptionsCard plan={plan} evacuation={shown} />
          {shown && <StandDown evacuation={shown} allowed={allowed} />}
        </div>
      </div>
    </div>
  );
}
