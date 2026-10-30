import { Button, HTMLSelect, Icon, NonIdealState } from "@blueprintjs/core";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { useMe } from "../../api/me";
import { useMissions } from "../../api/people";
import { canPlanTrip } from "../../api/permissions";
import { type Trip, type TripDetail as Detail, type TripFilters, useTrip, useTrips } from "../../api/trips";
import { HOME_TZ, formatDays } from "../../app/time";
import { FlashRow } from "../../ui/motion";
import { Card, Kpi, Sev } from "../../ui/primitives";
import { SkeletonRows } from "../../ui/Skeleton";
import { RiskCard, TripDetail } from "./TripDetail";
import { TripPlanner } from "./TripPlanner";

const APPROVAL: Record<string, [string, string]> = {
  DRAFT: ["Draft", "nx-dim"],
  PENDING: ["Pending", "nx-pending"],
  APPROVED: ["Approved", "nx-safe"],
  REJECTED: ["Rejected", "nx-dim"],
  CANCELLED: ["Cancelled", "nx-dim"],
};
const RISKS = ["LOW", "MODERATE", "HIGH", "CRITICAL"] as const;

/** Today in the home zone, as YYYY-MM-DD (trip dates are calendar days). */
function homeToday(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: HOME_TZ }).format(new Date());
}

function where(t: Trip, today: string): [string, string] {
  if (t.impacted_by.length) return [`Impacted · ${t.impacted_by.join(", ")}`, "nx-impacted"];
  if (t.approval_status === "CANCELLED") return ["—", "nx-dim"];
  if (t.risk_changed) return [`Risk now ${t.live_risk}`, "nx-pending"];
  if (today > t.ends_on) return ["Completed", "nx-dim"];
  if (today >= t.starts_on) return ["In country", ""];
  return ["Planned", "nx-dim"];
}

/** Journey Management (JR-01..09; D-30, D-32): plan, approve and follow trips. */
export function JourneysScreen() {
  const [params, setParams] = useSearchParams();
  const [filters, setFilters] = useState<TripFilters>({});
  const [planning, setPlanning] = useState<Detail | "new" | null>(null);
  const [today] = useState(homeToday);
  const trips = useTrips(filters);
  const all = useTrips({}).data ?? [];
  const missions = useMissions().data ?? [];
  const me = useMe().data;
  const selectedId = params.get("trip") ?? undefined;
  const selected = useTrip(selectedId).data;
  const select = (id: string) => setParams({ trip: id });

  const list = trips.data ?? [];
  const live = all.filter((t) => t.approval_status === "PENDING" || t.approval_status === "APPROVED");
  const active = live.filter((t) => t.ends_on >= today);
  const risky = active.filter((t) => t.live_risk === "HIGH" || t.live_risk === "CRITICAL");
  const briefed = active.filter((t) => t.checklist.security_briefing).length;
  const impacted = all.filter((t) => t.impacted_by.length);
  const set = (change: TripFilters) => setFilters({ ...filters, ...change });

  return (
    <div className="nx-pad">
      {impacted.map((t) => (
        <div key={t.id} className="nx-banner red nx-mb" role="alert">
          <Icon icon="warning-sign" />
          <div>
            <b>
              {t.reference} impacted by {t.impacted_by.join(", ")}.
            </b>{" "}
            {t.travellers_count} traveller{t.travellers_count === 1 ? "" : "s"} in {t.destination} are in the
            incident's exposure.
          </div>
        </div>
      ))}
      <div className="nx-g4">
        <Kpi icon="airplane" label="Active trips" value={active.length} detail="Pending or approved, not yet over" />
        <Kpi
          icon="time"
          label="Pending approvals"
          value={live.filter((t) => t.approval_status === "PENDING").length}
          detail="A second person decides (D-32)"
          alert={live.some((t) => t.approval_status === "PENDING")}
        />
        <Kpi
          icon="warning-sign"
          label="High-risk destinations"
          value={risky.length}
          detail={`Rated HIGH or above now${all.some((t) => t.risk_changed) ? " · risk rose since approval" : ""}`}
          alert={all.some((t) => t.risk_changed)}
        />
        <Kpi
          icon="tick"
          label="Pre-travel briefings"
          value={active.length ? `${Math.round((briefed / active.length) * 100)}%` : "—"}
          detail="Of active trips"
        />
      </div>

      <div className="nx-ntf-grid">
        <Card
          icon="airplane"
          title="Trips"
          sub={`${list.length} shown`}
          actions={
            <div className="nx-row">
              <HTMLSelect
                minimal
                aria-label="Filter by status"
                value={filters.status ?? ""}
                onChange={(e) => set({ status: e.currentTarget.value || undefined })}
                options={[
                  { value: "", label: "All statuses" },
                  ...Object.entries(APPROVAL)
                    .filter(([value]) => value !== "REJECTED")
                    .map(([value, [label]]) => ({ value, label })),
                ]}
              />
              <HTMLSelect
                minimal
                aria-label="Filter by risk"
                value={filters.risk ?? ""}
                onChange={(e) => set({ risk: e.currentTarget.value || undefined })}
                options={[{ value: "", label: "All risks" }, ...RISKS.map((r) => ({ value: r, label: r }))]}
              />
              <HTMLSelect
                minimal
                aria-label="Filter by mission"
                value={filters.mission_id ?? ""}
                onChange={(e) => set({ mission_id: e.currentTarget.value || undefined })}
                options={[{ value: "", label: "All missions" }, ...missions.map((m) => ({ value: m.id, label: m.code }))]}
              />
              <HTMLSelect
                minimal
                aria-label="Filter by impact"
                value={filters.impacted ?? ""}
                onChange={(e) => set({ impacted: e.currentTarget.value || undefined })}
                options={[
                  { value: "", label: "Impacted or not" },
                  { value: "true", label: "Impacted" },
                  { value: "false", label: "Not impacted" },
                ]}
              />
              {canPlanTrip(me) && (
                <Button small intent="primary" icon="plus" text="Plan a trip" onClick={() => setPlanning("new")} />
              )}
            </div>
          }
        >
          {trips.isLoading ? (
            <SkeletonRows />
          ) : list.length === 0 ? (
            <NonIdealState icon="airplane" title="No trips" description="Nothing matches these filters." />
          ) : (
            <div className="nx-ntf-scroll">
              <table className="nx-table-plain" aria-label="Trips">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Trip</th>
                    <th>Route</th>
                    <th>Dates</th>
                    <th>Destination risk</th>
                    <th>Approval</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {list.map((t) => {
                    const [status, statusClass] = where(t, today);
                    return (
                      <FlashRow
                        key={t.id}
                        watch={`${t.approval_status} ${t.risk_level} ${status}`}
                        tone={t.approval_status === "REJECTED" ? "danger" : t.approval_status === "APPROVED" ? "success" : "info"}
                        className={t.id === selectedId ? "on" : undefined}
                        onClick={() => select(t.id)}
                      >
                        <td className="nx-mono nx-dim nx-nowrap">{t.reference}</td>
                        <td>
                          <button type="button" className="nx-linkbtn" onClick={() => select(t.id)}>
                            <b>{t.purpose || "Trip"}</b>
                          </button>
                          <div className="nx-dim">
                            {t.travellers_count} traveller{t.travellers_count === 1 ? "" : "s"}
                            {t.requested_by_name && ` · ${t.requested_by_name}`}
                          </div>
                        </td>
                        <td>
                          {t.origin} → {t.destination}
                        </td>
                        <td className="nx-mono nx-nowrap">{formatDays(t.starts_on, t.ends_on)}</td>
                        <td>
                          <Sev severity={t.risk_level} />
                        </td>
                        <td className={APPROVAL[t.approval_status]?.[1]}>
                          {APPROVAL[t.approval_status]?.[0] ?? t.approval_status}
                        </td>
                        <td className={statusClass}>{status}</td>
                      </FlashRow>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        <div className="nx-col">
          {planning ? (
            <TripPlanner
              key={planning === "new" ? "new" : planning.id}
              editing={planning === "new" ? null : planning}
              onClose={() => setPlanning(null)}
              onSaved={(trip) => {
                setPlanning(null);
                select(trip.id);
              }}
            />
          ) : (
            selected && (
              <>
                <TripDetail trip={selected} onEdit={setPlanning} />
                <RiskCard trip={selected} />
              </>
            )
          )}
        </div>
      </div>
    </div>
  );
}
