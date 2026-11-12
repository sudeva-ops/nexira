import { Button, HTMLSelect, Icon, InputGroup } from "@blueprintjs/core";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { ApiError } from "../../api/client";
import {
  type Asset,
  defaultFleetMission,
  dueText,
  type FleetPermissions,
  type MaintenanceItem,
  type MissionFleet,
  shownStates,
  STATE_LABEL,
  STATE_SEV,
  STORED_STATUSES,
  type StoredStatus,
  useCompleteMaintenance,
  useFleetAssets,
  useFleetPermissions,
  useFleetSummary,
  useMaintenance,
  useMissionFleet,
  useSetStatus,
} from "../../api/fleet";
import { useMissions } from "../../api/people";
import { useRealtimeEvents } from "../../api/realtimeContext";
import { formatStamp } from "../../app/time";
import { FlashRow } from "../../ui/motion";
import { Card, Kpi } from "../../ui/primitives";
import { SkeletonRows } from "../../ui/Skeleton";
import { TileRow } from "../../ui/TileRow";
import { Empty } from "../../ui/Empty";

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "Not done";
}

function Tags({ asset }: { asset: Asset }) {
  return (
    <span className="nx-row nx-flt-tags">
      {shownStates(asset).map((s) => (
        <span key={s.code} className={`nx-sev ${STATE_SEV[s.code]}`} title={s.reference ?? undefined}>
          {STATE_LABEL[s.code]}
        </span>
      ))}
    </span>
  );
}

/** FLT-05: vehicles that cannot be used because of an incident, and the latest crossing. */
function ZoneAlert({ assets, crossed }: { assets: Asset[]; crossed: string | null }) {
  const hit = assets.filter((a) => a.tags.some((t) => t.code === "IN_ZONE" || t.code === "BLOCKED"));
  if (!hit.length) return null;
  return (
    <div className="nx-banner nx-mb red" role="alert" data-testid="fleet-alert">
      <Icon icon="warning-sign" />
      <div className="nx-grow">
        {hit.map((a) => {
          const blocked = a.tags.find((t) => t.code === "BLOCKED");
          const zone = a.tags.find((t) => t.code === "IN_ZONE");
          return (
            <div key={a.id}>
              <b>{a.code}</b> · {a.location_label}
              {blocked && ` · driver needs help (${blocked.reference})`}
              {zone && ` · in the impact zone of ${zone.reference}`}
            </div>
          );
        })}
        {crossed && <div className="nx-dim">Latest zone crossing: {crossed} (simulated telematics)</div>}
      </div>
    </div>
  );
}

function Fuel({ pct }: { pct: number }) {
  return (
    <span className="nx-row nx-flt-fuel">
      <span className="nx-bar" aria-hidden>
        <i className={pct < 50 ? "warn" : undefined} style={{ width: `${pct}%` }} />
      </span>
      <span className="nx-mono">{pct}%</span>
    </span>
  );
}

function AssetsCard({
  assets,
  loading,
  selected,
  onSelect,
}: {
  assets: Asset[];
  loading: boolean;
  selected: string | undefined;
  onSelect: (id: string) => void;
}) {
  return (
    <Card icon="truck" title="Vehicles & critical assets" sub="GPS + telematics (simulated)">
      {loading ? (
        <SkeletonRows rows={6} />
      ) : !assets.length ? (
        <Empty>No assets. No vehicles or equipment for this mission.</Empty>
      ) : (
        <table className="nx-table-plain nx-flt-table" aria-label="Vehicles and critical assets">
          <thead>
            <tr>
              <th>ID</th>
              <th>Asset</th>
              <th>Mission</th>
              <th>Location</th>
              <th>Fuel / charge</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {assets.map((a) => (
              <FlashRow
                key={a.id}
                data-asset={a.code}
                aria-selected={a.id === selected}
                className={a.id === selected ? "nx-flt-selected" : undefined}
                watch={`${shownStates(a).map((s) => s.code).join(",")} ${a.location_label}`}
                tone={a.available || a.kind === "EQUIPMENT" ? "info" : "danger"}
                onClick={() => onSelect(a.id)}
              >
                <td className="nx-mono nx-dim">{a.code}</td>
                <td>
                  <b>{a.type_label}</b>
                  {a.armoured && <span className="nx-dim"> · armoured</span>}
                </td>
                <td>{a.city}</td>
                <td>{a.location_label}</td>
                <td>
                  <Fuel pct={a.fuel_pct} />
                </td>
                <td>
                  <Tags asset={a} />
                </td>
              </FlashRow>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

/** FLT-03: seats in available vehicles against the people to move. */
function CapacityCard({ fleet }: { fleet: MissionFleet | undefined }) {
  if (!fleet) {
    return (
      <Card icon="route" title="Evacuation capacity">
        <div className="nx-bd nx-dim">Pick a mission to see its road capacity.</div>
      </Card>
    );
  }
  const c = fleet.capacity;
  const max = Math.max(c.seats_available, c.seats_needed, 1);
  return (
    <Card icon="route" title={`Evacuation capacity · ${fleet.city}`}>
      <div className="nx-bd" aria-label="Evacuation capacity">
        <div className="nx-funnel nx-flt-funnel">
          <span>Seats available</span>
          <div className="nx-stack">
            <i style={{ width: `${(100 * c.seats_available) / max}%`, background: "#2D72D2" }} />
          </div>
          <span className="nx-mono">{c.seats_available}</span>
        </div>
        <div className="nx-funnel nx-flt-funnel">
          <span>Seats needed</span>
          <div className="nx-stack">
            <i style={{ width: `${(100 * c.seats_needed) / max}%`, background: "#EC9A3C" }} />
          </div>
          <span className="nx-mono">{c.seats_needed}</span>
        </div>
        <div className="nx-dim nx-flt-note">
          {c.needed_from === "EVACUATION"
            ? `Mission staff, delegates and dependants on ${c.evacuation_reference}. `
            : "Mission staff, delegates and dependants. "}
          {c.shortfall === 0
            ? "Capacity sufficient."
            : c.suggestion
              ? `Shortfall of ${c.shortfall} seat${c.shortfall === 1 ? "" : "s"}: ${c.suggestion.partner_name} could add vehicles (a suggestion; nothing is requested).`
              : `Shortfall of ${c.shortfall} seat${c.shortfall === 1 ? "" : "s"}: no secure-transport partner covers ${fleet.country_code}.`}{" "}
          {c.shortfall > 0 && <Link to="/partners">Assistance Partners</Link>}
        </div>
      </div>
    </Card>
  );
}

function MaintenanceCard({
  items,
  allowed,
}: {
  items: MaintenanceItem[];
  allowed: FleetPermissions | undefined;
}) {
  const complete = useCompleteMaintenance();
  const alerts = items.filter((m) => m.alert);
  return (
    <Card icon="wrench" title="Maintenance alerts" sub="Overdue or due within 14 days">
      {!alerts.length ? (
        <Empty>No maintenance due.</Empty>
      ) : (
        <table className="nx-table-plain nx-flt-table" aria-label="Maintenance alerts">
          <tbody>
            {alerts.map((m) => (
              <tr key={m.id} data-item={m.asset_code}>
                <td className="nx-mono">{m.asset_code}</td>
                <td>{m.task}</td>
                <td className={m.overdue ? "nx-error" : "nx-dim"}>{dueText(m.due_on)}</td>
                <td className="nx-ev-right">
                  {allowed?.complete_maintenance && (
                    <Button
                      minimal
                      size="small"
                      text="Mark done"
                      loading={complete.isPending && complete.variables === m.id}
                      onClick={() => complete.mutate(m.id)}
                    />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {complete.isError && <div className="nx-bd nx-error">{errorText(complete.error)}</div>}
    </Card>
  );
}

/** The selected asset: its details, and the status change when allowed (FLT-04, FLT-07). */
function AssetCard({ asset }: { asset: Asset }) {
  const allowed = useFleetPermissions(asset.mission_id).data;
  const setStatus = useSetStatus();
  const [status, setChoice] = useState<StoredStatus>(asset.status);
  const [reason, setReason] = useState("");
  const statuses = STORED_STATUSES.filter((s) => asset.kind === "VEHICLE" || s !== "IN_USE");
  const needsReason = status === "MAINTENANCE";
  return (
    <Card icon="truck" title={`${asset.code} · ${asset.type_label}`} sub={asset.source}>
      <div className="nx-bd">
        <table className="nx-table-plain nx-flt-table" aria-label="Asset details">
          <tbody>
            <tr>
              <td className="nx-dim">Status</td>
              <td>
                <Tags asset={asset} />
                {asset.status_reason && <div className="nx-dim">{asset.status_reason}</div>}
              </td>
            </tr>
            {asset.kind === "VEHICLE" && (
              <tr>
                <td className="nx-dim">Driver</td>
                <td>
                  {asset.driver_name ?? (asset.driver_assigned ? "Driver assigned" : "No driver assigned")}
                </td>
              </tr>
            )}
            {asset.seats !== null && (
              <tr>
                <td className="nx-dim">Passenger seats</td>
                <td>{asset.seats}</td>
              </tr>
            )}
            <tr>
              <td className="nx-dim">Last position</td>
              <td>
                {asset.location_label} · {formatStamp(asset.position_at)}
                {asset.at_site && <span className="nx-dim"> · at a mission site</span>}
              </td>
            </tr>
          </tbody>
        </table>
        {allowed?.set_asset_status && (
          <div className="nx-row nx-flt-status">
            <HTMLSelect
              minimal
              aria-label="New status"
              value={status}
              onChange={(e) => setChoice(e.currentTarget.value as StoredStatus)}
              options={statuses.map((s) => ({ value: s, label: s.replace("_", " ") }))}
            />
            {needsReason && (
              <InputGroup
                small
                aria-label="Reason"
                placeholder="Reason (audited)"
                value={reason}
                onChange={(e) => setReason(e.currentTarget.value)}
              />
            )}
            <Button
              size="small"
              text="Set status"
              disabled={(needsReason && !reason.trim()) || (status === asset.status && !needsReason)}
              loading={setStatus.isPending}
              onClick={() =>
                setStatus.mutate(
                  { id: asset.id, status, reason: needsReason ? reason.trim() : null },
                  { onSuccess: () => setReason("") },
                )
              }
            />
          </div>
        )}
        {setStatus.isError && <div className="nx-error">{errorText(setStatus.error)}</div>}
      </div>
    </Card>
  );
}

/** Fleet & Assets (FLT-01..07; D-41). Assets, telematics and the workshop are simulated (D-19). */
export function FleetScreen() {
  const [params, setParams] = useSearchParams();
  const missions = [...(useMissions().data ?? [])].sort((a, b) => a.code.localeCompare(b.code));
  const missionId = params.get("mission") ?? (missions.length ? defaultFleetMission(missions) : "");
  const assets = useFleetAssets(missionId);
  const summary = useFleetSummary().data;
  const fleet = useMissionFleet(missionId).data;
  const items = useMaintenance(missionId).data ?? [];
  const allowed = useFleetPermissions(missionId || undefined).data;
  const [selected, setSelected] = useState<string>();
  const [crossed, setCrossed] = useState<string | null>(null);
  useRealtimeEvents((event) => {
    const ids = event.data.incident_ids;
    if (event.event === "FLEET_UPDATED" && Array.isArray(ids) && ids.length && typeof event.data.code === "string") {
      setCrossed(`${event.data.code} · ${formatStamp(event.occurred_at)}`);
    }
  });
  const rows = assets.data ?? [];
  const shown = rows.find((a) => a.id === selected);

  return (
    <div className="nx-pad">
      <div className="nx-row nx-mb nx-ev-picker">
        <span className="nx-dim">Mission</span>
        <HTMLSelect
          minimal
          aria-label="Mission"
          value={missionId}
          onChange={(e) => {
            setSelected(undefined);
            setParams({ mission: e.currentTarget.value });
          }}
          options={[
            { value: "", label: "All missions" },
            ...missions.map((m) => ({ value: m.id, label: `${m.code} · ${m.city}` })),
          ]}
        />
        <span className="nx-grow" />
        <span className="nx-dim">Illustrative asset register (simulated)</span>
      </div>
      <ZoneAlert assets={rows} crossed={crossed} />
      <TileRow>
        <Kpi
          icon="truck"
          label="Vehicles"
          value={summary?.vehicles ?? "—"}
          detail={summary ? `${summary.armoured} armoured` : undefined}
        />
        <Kpi
          icon="tick"
          label={fleet ? `Available now · ${fleet.city}` : "Available now"}
          value={fleet ? fleet.available : "—"}
          detail={fleet ? `Of ${fleet.vehicles} vehicles` : "Pick a mission"}
          alert={!!fleet && fleet.available < fleet.vehicles - 1}
        />
        <Kpi
          icon="dashboard"
          label="Avg. fuel level"
          value={summary?.average_fuel_pct != null ? `${summary.average_fuel_pct}%` : "—"}
          detail={fleet?.generator_fuel_pct != null ? `Generator: ${fleet.generator_fuel_pct}%` : "All assets"}
        />
        <Kpi
          icon="time"
          label="Due for service"
          value={summary?.maintenance_due ?? "—"}
          detail="Within 14 days"
          alert={!!summary?.maintenance_due}
        />
      </TileRow>
      <div className="nx-ev-grid nx-flt-grid">
        <AssetsCard assets={rows} loading={assets.isLoading} selected={selected} onSelect={setSelected} />
        <div className="nx-col">
          {shown && <AssetCard key={shown.id} asset={shown} />}
          <CapacityCard fleet={missionId ? fleet : undefined} />
          <MaintenanceCard items={items} allowed={missionId ? allowed : undefined} />
        </div>
      </div>
    </div>
  );
}
