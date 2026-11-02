import {
  Button,
  HTMLSelect,
  Icon,
  InputGroup,
  NonIdealState,
} from "@blueprintjs/core";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { ApiError } from "../../api/client";
import {
  type Change,
  type ChecklistItem,
  localToIso,
  RISK_SEV,
  type Segment,
  segmentTime,
  STATUS_SEV,
  useDecideChange,
  useProgressSegment,
  useProposeChange,
  useStartVisit,
  useTickItem,
  useVipAccess,
  useVipPermissions,
  useVisit,
  useVisits,
  type VipPermissions,
  type Visit,
  visitDates,
} from "../../api/vip";
import { Card, Kpi } from "../../ui/primitives";
import { SkeletonRows } from "../../ui/Skeleton";

const EAT = "Africa/Addis_Ababa";

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "Not done";
}

function localDate(iso: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: EAT }).format(
    new Date(iso),
  ); // YYYY-MM-DD
}

function localClock(iso: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: EAT,
  }).format(new Date(iso));
}

function Restricted() {
  return (
    <div className="nx-pad">
      <NonIdealState
        icon="lock"
        title="Restricted"
        description="VIP and delegation visits are shown only to the protection roles and the host mission's Head of Mission."
      />
    </div>
  );
}

/** VIP-04: the visit banner; Start visit when allowed; LIVE is programme status only. */
function Banner({
  visit,
  allowed,
}: {
  visit: Visit;
  allowed: VipPermissions | undefined;
}) {
  const start = useStartVisit();
  const live = visit.status === "LIVE";
  return (
    <div
      className={`nx-banner nx-mb${live ? " green" : ""}`}
      data-testid="vip-banner"
    >
      <Icon icon="shield" />
      <div className="nx-grow">
        <b>
          Visit {visit.reference} · {visit.title} · {visitDates(visit)}.
        </b>{" "}
        {visit.trip_reference && (
          <>Linked to trip {visit.trip_reference} (restricted). </>
        )}
        <span className="nx-dim">Principal: {visit.principal_role}.</span>
        {start.isError && (
          <div className="nx-error">{errorText(start.error)}</div>
        )}
      </div>
      {live && (
        <span className="nx-row nx-vip-live">
          <span className="nx-sev ok">LIVE</span>
          <span className="nx-dim">programme status only</span>
        </span>
      )}
      {visit.status === "COMPLETED" && (
        <span className="nx-sev ok">COMPLETED</span>
      )}
      {visit.status === "CANCELLED" && (
        <span className="nx-sev crit" title={visit.cancel_reason ?? undefined}>
          CANCELLED
        </span>
      )}
      {allowed?.start_visit && (
        <Button
          intent="primary"
          size="small"
          text="Start visit"
          loading={start.isPending}
          onClick={() => start.mutate(visit.id)}
        />
      )}
    </div>
  );
}

function Kpis({ visit }: { visit: Visit }) {
  const k = visit.kpis;
  const pending = visit.checklist.filter(
    (c) => !c.done && c.label.toLowerCase().endsWith("venue survey"),
  );
  return (
    <div className="nx-g4 nx-mb">
      <Kpi
        icon="route"
        label="Programme segments"
        value={k.segments}
        detail={`${k.high} rated High`}
        alert={k.high > 0}
      />
      <Kpi
        icon="people"
        label="Close-protection team"
        value={k.team_size ?? "—"}
        detail={`${k.vehicles} vehicle${k.vehicles === 1 ? "" : "s"} · ${k.medics} medic${k.medics === 1 ? "" : "s"}`}
      />
      <Kpi
        icon="office"
        label="Venues surveyed"
        value={`${k.venues_surveyed} / ${k.venues}`}
        detail={
          pending.length
            ? `${pending.map((c) => c.label.replace(/ venue survey$/i, "")).join(", ")} pending`
            : "All surveyed"
        }
        alert={k.venues_surveyed < k.venues}
      />
      <Kpi
        icon="warning-sign"
        label="Visit risk"
        value={visit.risk}
        detail={
          visit.country_risk
            ? `Country risk ${visit.country_risk} · worked out on every read`
            : "Worked out on every read"
        }
        alert={visit.risk === "HIGH" || visit.risk === "CRITICAL"}
      />
    </div>
  );
}

function changeText(change: Change): string {
  if (change.make_virtual) return "replace with a virtual alternative";
  if (!change.new_starts_at) return "change";
  return `move to ${localClock(change.new_starts_at)}${change.new_ends_at ? `–${localClock(change.new_ends_at)}` : ""}`;
}

/** VIP-05: propose a new time or a virtual alternative, with a reason (G-5). */
function ProposeForm({
  segment,
  onDone,
}: {
  segment: Segment;
  onDone: () => void;
}) {
  const propose = useProposeChange();
  const [kind, setKind] = useState<"time" | "virtual">("time");
  const [time, setTime] = useState(localClock(segment.starts_at));
  const [reason, setReason] = useState("");
  const ready =
    reason.trim() && (kind === "virtual" || /^\d{2}:\d{2}$/.test(time));
  return (
    <div
      className="nx-vip-form"
      aria-label={`Propose a change to segment ${segment.seq}`}
    >
      <div className="nx-row nx-vip-form-row">
        <HTMLSelect
          minimal
          aria-label="Change"
          value={kind}
          onChange={(e) => setKind(e.currentTarget.value as "time" | "virtual")}
          options={[
            { value: "time", label: "New start time" },
            ...(segment.virtual
              ? []
              : [{ value: "virtual", label: "Virtual alternative" }]),
          ]}
        />
        {kind === "time" && (
          <InputGroup
            small
            type="time"
            aria-label="New start"
            value={time}
            onChange={(e) => setTime(e.currentTarget.value)}
          />
        )}
        <InputGroup
          small
          className="nx-grow"
          aria-label="Reason"
          placeholder="Reason (audited)"
          value={reason}
          onChange={(e) => setReason(e.currentTarget.value)}
        />
        <Button
          size="small"
          intent="primary"
          text="Propose"
          disabled={!ready}
          loading={propose.isPending}
          onClick={() =>
            propose.mutate(
              kind === "virtual"
                ? {
                    segmentId: segment.id,
                    reason: reason.trim(),
                    make_virtual: true,
                  }
                : {
                    segmentId: segment.id,
                    reason: reason.trim(),
                    new_starts_at: localToIso(
                      localDate(segment.starts_at),
                      time,
                    ),
                  },
              { onSuccess: onDone },
            )
          }
        />
        <Button size="small" minimal text="Cancel" onClick={onDone} />
      </div>
      <div className="nx-dim nx-vip-note">
        The risk follows the place, not the time: a new time keeps it while the
        incident is active; a virtual alternative has no venue risk. A second
        person decides.
      </div>
      {propose.isError && (
        <div className="nx-error">{errorText(propose.error)}</div>
      )}
    </div>
  );
}

/** A change waiting for a decision: Approve and Reject for the decider, "waiting" for others. */
function PendingChange({
  change,
  allowed,
}: {
  change: Change;
  allowed: VipPermissions | undefined;
}) {
  const decide = useDecideChange();
  const may = allowed?.decide_vip_change.includes(change.id) ?? false;
  return (
    <div className="nx-banner nx-vip-change" data-testid="vip-change">
      <Icon icon="exchange" />
      <div className="nx-grow">
        <b>Change proposed:</b> {changeText(change)} · “{change.reason}” ·{" "}
        {change.proposed_by_name}
        {!may && (
          <div className="nx-dim">
            Waiting for the Head of Mission or the HQ Crisis Director (another
            person).
          </div>
        )}
        {decide.isError && (
          <div className="nx-error">{errorText(decide.error)}</div>
        )}
      </div>
      {may && (
        <>
          <Button
            size="small"
            intent="success"
            text="Approve"
            loading={decide.isPending && decide.variables?.approve === true}
            onClick={() => decide.mutate({ id: change.id, approve: true })}
          />
          <Button
            size="small"
            text="Reject"
            loading={decide.isPending && decide.variables?.approve === false}
            onClick={() => decide.mutate({ id: change.id, approve: false })}
          />
        </>
      )}
    </div>
  );
}

/** The next step a segment can take in programme order (plan §5). */
function nextStep(
  segments: Segment[],
  segment: Segment,
): "Start" | "Complete" | null {
  if (segment.status === "IN_PROGRESS") return "Complete";
  if (segment.status !== "PLANNED") return null;
  return segments.every((s) => s.seq >= segment.seq || s.status === "COMPLETED")
    ? "Start"
    : null;
}

function ProgrammeCard({
  visit,
  allowed,
}: {
  visit: Visit;
  allowed: VipPermissions | undefined;
}) {
  const progress = useProgressSegment();
  const [proposing, setProposing] = useState<string>();
  const segments = visit.segments;
  const flagged = segments.filter((s) => s.recommendation || s.pending_change);
  return (
    <Card
      icon="route"
      title="Programme & route risk"
      sub="Risk from incidents, weather and attendees, on every read"
    >
      <table className="nx-table-plain nx-vip-table" aria-label="Programme">
        <thead>
          <tr>
            <th>Segment</th>
            <th>Time</th>
            <th>Risk</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {segments.map((s, i) => {
            const step = allowed?.progress_visit ? nextStep(segments, s) : null;
            return (
              <tr key={s.id} data-seq={s.seq}>
                <td>
                  <b>{s.title}</b>
                  {s.virtual && <span className="nx-dim"> · virtual</span>}
                </td>
                <td className="nx-mono nx-vip-time">
                  {segmentTime(s, segments[i - 1])}
                </td>
                <td>
                  <span className={`nx-sev ${RISK_SEV[s.risk]}`}>{s.risk}</span>
                  {s.reasons.map((r) => (
                    <div key={r.text} className="nx-dim nx-vip-reason">
                      {r.incident_id ? (
                        <Link to={`/incidents?id=${r.incident_id}`}>
                          {r.text}
                        </Link>
                      ) : (
                        r.text
                      )}
                    </div>
                  ))}
                </td>
                <td>
                  <span className={`nx-sev ${STATUS_SEV[s.status]}`}>
                    {s.status.replace("_", " ")}
                  </span>
                  {step && (
                    <Button
                      minimal
                      size="small"
                      text={step}
                      aria-label={`${step} segment ${s.seq}`}
                      loading={
                        progress.isPending && progress.variables === s.id
                      }
                      onClick={() => progress.mutate(s.id)}
                    />
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {progress.isError && (
        <div className="nx-bd nx-error">{errorText(progress.error)}</div>
      )}
      {flagged.map((s) => (
        <div key={s.id} className="nx-bd">
          {s.recommendation && (
            <div
              className="nx-banner amber nx-vip-flag"
              data-testid="vip-recommendation"
            >
              <Icon icon="warning-sign" />
              <div className="nx-grow">
                <b>{s.title} flagged High.</b>{" "}
                {s.reasons.find((r) => r.level === "HIGH")?.text}.
                Recommendation: {s.recommendation.toLowerCase()}.
              </div>
              {allowed?.propose_vip_change.includes(s.id) &&
                proposing !== s.id && (
                  <Button
                    size="small"
                    text="Propose change"
                    onClick={() => setProposing(s.id)}
                  />
                )}
            </div>
          )}
          {proposing === s.id && (
            <ProposeForm segment={s} onDone={() => setProposing(undefined)} />
          )}
          {s.pending_change && (
            <PendingChange change={s.pending_change} allowed={allowed} />
          )}
        </div>
      ))}
    </Card>
  );
}

function DetailCard({ visit }: { visit: Visit }) {
  const d = visit.detail;
  const vehicles = d.vehicles
    .map(
      (v) =>
        `${v.code}${v.armoured ? " (armoured)" : ""} · ${v.state.replace("_", " ").toLowerCase()}`,
    )
    .join(" · ");
  const medical = [
    d.medic ? "Medic with the team" : null,
    d.medical.facility_name,
    d.medical.partner_name && `${d.medical.partner_name} standby`,
  ]
    .filter(Boolean)
    .join(" · ");
  const rows: [string, string][] = [
    ["Team lead", d.team_lead ?? "—"],
    ["Advance team", d.advance_team ?? "—"],
    ["Vehicles", vehicles || "—"],
    ["Medical", medical || "—"],
    ["Safe havens", d.safe_havens.join(" · ") || "—"],
  ];
  return (
    <Card
      icon="people"
      title="Protection detail"
      sub="Labels and counts only (sample)"
    >
      <table
        className="nx-table-plain nx-vip-table"
        aria-label="Protection detail"
      >
        <tbody>
          {rows.map(([label, value]) => (
            <tr key={label}>
              <td className="nx-dim">{label}</td>
              <td>
                <b>{value}</b>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function dueLabel(item: ChecklistItem): string {
  const due = new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  }).format(new Date(`${item.due_on}T00:00:00Z`));
  return item.overdue ? `overdue · due ${due}` : `due ${due}`;
}

function ChecklistCard({
  visit,
  allowed,
}: {
  visit: Visit;
  allowed: VipPermissions | undefined;
}) {
  const tick = useTickItem();
  return (
    <Card icon="tick-circle" title="Pre-visit checklist">
      <ul className="nx-bd nx-vip-checklist" aria-label="Pre-visit checklist">
        {visit.checklist.map((c) => (
          <li key={c.id} className="nx-row" data-done={c.done}>
            <Icon
              icon={c.done ? "tick-circle" : "circle"}
              intent={c.done ? "success" : undefined}
            />
            <span className="nx-grow">{c.label}</span>
            {c.done ? (
              <span className="nx-dim">{c.done_by_name}</span>
            ) : (
              <>
                <span className={c.overdue ? "nx-error" : "nx-dim"}>
                  {dueLabel(c)}
                </span>
                {allowed?.tick_vip_checklist && (
                  <Button
                    minimal
                    size="small"
                    text="Mark done"
                    aria-label={`Mark done: ${c.label}`}
                    loading={tick.isPending && tick.variables === c.id}
                    onClick={() => tick.mutate(c.id)}
                  />
                )}
              </>
            )}
          </li>
        ))}
      </ul>
      {tick.isError && (
        <div className="nx-bd nx-error">{errorText(tick.error)}</div>
      )}
    </Card>
  );
}

/** VIP & Delegation Protection (VIP-01..07; D-42). Restricted (VIP-06); simulated (D-19). */
export function VipScreen() {
  const access = useVipAccess();
  const visible = access.data?.visible ?? false;
  const visits = useVisits(visible);
  const [params, setParams] = useSearchParams();
  const list = visits.data ?? [];
  const visitId = params.get("visit") ?? list[0]?.id;
  const visit = useVisit(visible ? visitId : undefined);
  const allowed = useVipPermissions(visible ? visitId : undefined).data;

  if (access.isLoading)
    return (
      <div className="nx-pad">
        <SkeletonRows rows={6} />
      </div>
    );
  if (!visible) return <Restricted />;
  if (visits.isSuccess && !list.length) {
    return (
      <div className="nx-pad">
        <NonIdealState
          icon="shield"
          title="No visits"
          description="No VIP or delegation visit in your missions."
        />
      </div>
    );
  }
  if (visit.error instanceof ApiError && visit.error.status === 404)
    return <Restricted />;
  const shown = visit.data;
  return (
    <div className="nx-pad">
      {list.length > 1 && (
        <div className="nx-row nx-mb nx-ev-picker">
          <span className="nx-dim">Visit</span>
          <HTMLSelect
            minimal
            aria-label="Visit"
            value={visitId}
            onChange={(e) => setParams({ visit: e.currentTarget.value })}
            options={list.map((v) => ({
              value: v.id,
              label: `${v.reference} · ${v.title}`,
            }))}
          />
        </div>
      )}
      {!shown ? (
        <SkeletonRows rows={8} />
      ) : (
        <>
          <Banner visit={shown} allowed={allowed} />
          <Kpis visit={shown} />
          <div className="nx-ev-grid nx-vip-grid">
            <ProgrammeCard visit={shown} allowed={allowed} />
            <div className="nx-col">
              <DetailCard visit={shown} />
              <ChecklistCard visit={shown} allowed={allowed} />
            </div>
          </div>
          <div className="nx-dim nx-vip-source">
            {shown.source} · no position of the principal, team or motorcade is
            stored or shown
          </div>
        </>
      )}
    </div>
  );
}
