import { Button, HTMLSelect, Icon, NonIdealState } from "@blueprintjs/core";
import { Link, useSearchParams } from "react-router-dom";

import { ApiError } from "../../api/client";
import {
  dotsIn,
  drillAgo,
  OCCUPANT_COLOUR,
  OCCUPANT_LABEL,
  type OccupantKind,
  SENSOR_SEV,
  type Sensor,
  type Twin,
  useTickReadiness,
  useTwin,
  useTwinPermissions,
  useTwinSites,
} from "../../api/twin";
import { Card, Kpi } from "../../ui/primitives";
import { SkeletonRows } from "../../ui/Skeleton";

const KINDS: OccupantKind[] = ["STAFF", "GUARD", "VISITOR"];
const ACCESS = new Set(["GATE", "BADGE_READER"]);
const LEGEND: Record<OccupantKind, string> = { STAFF: "Staff", GUARD: "Guard", VISITOR: "Visitor" };

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "Not done";
}

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** TWN-04: shelter-in-place from the playbook's shelter alert; the route while evacuating. */
function Banner({ twin }: { twin: Twin }) {
  if (!twin.shelter) return null;
  const by = (zone: string, kind: OccupantKind) =>
    twin.occupants.filter((o) => o.zone_code === zone && o.kind === kind).length;
  const zoneOf = (kind: string) => twin.zones.find((z) => z.kind === kind)?.code ?? "";
  const safe = zoneOf("SAFE_ROOM");
  const comms = zoneOf("COMMS");
  const conf = zoneOf("CONFERENCE");
  const parts = [
    `${plural(by(safe, "STAFF"), "staff", "staff")} in the safe room`,
    by(comms, "STAFF") ? `${plural(by(comms, "STAFF"), "staff", "staff")} in the IT room` : null,
    by(conf, "VISITOR") ? `${plural(by(conf, "VISITOR"), "visitor")} held in the conference room` : null,
  ].filter(Boolean);
  return (
    <div className="nx-banner amber nx-mb" role="alert" data-testid="twin-shelter">
      <Icon icon="lock" />
      <div className="nx-grow">
        <b>Shelter-in-place active</b> ({twin.shelter.incident_reference}): {parts.join(", ")}.
        {twin.route &&
          ` Route ${twin.route.code} approved via ${twin.zones.find((z) => z.code === twin.route?.exit_zone_code)?.name ?? "the gate"}.`}{" "}
        <Link to={`/incidents?id=${twin.shelter.incident_id}`}>Open incident →</Link>
      </div>
    </div>
  );
}

function Kpis({ twin }: { twin: Twin }) {
  const c = twin.counts;
  const ago = drillAgo(twin.readiness.last_drill_on);
  return (
    <div className="nx-g4 nx-mb">
      <Kpi
        icon="people"
        label="On site now"
        value={c.on_site}
        detail={`${c.staff} staff · ${plural(c.guards, "guard")} · ${plural(c.visitors, "visitor")}`}
      />
      <Kpi
        icon="shield"
        label="Safe room occupancy"
        value={`${c.safe_room} / ${c.safe_room_capacity ?? "—"}`}
        detail={twin.shelter ? "Sealed" : "Ready"}
      />
      <Kpi
        icon="feed"
        label="Sensors online"
        value={`${c.sensors_online} / ${c.sensors}`}
        detail={c.faults ? `${plural(c.faults, "fault")}` : "All healthy"}
        alert={c.faults > 0}
      />
      <Kpi
        icon="tick-circle"
        label="Site readiness"
        value={twin.readiness.score ?? "—"}
        detail={ago ? `Last drill ${ago}` : "No drill recorded"}
      />
    </div>
  );
}

/** TWN-01, TWN-02, TWN-04: the plan with rooms, counts, people as dots and the overlays. */
function Plan({ twin }: { twin: Twin }) {
  const down = new Set(
    twin.sensors.filter((s) => ACCESS.has(s.kind) && !s.online && s.zone_code).map((s) => s.zone_code),
  );
  const byZone = new Map<string, Twin["occupants"]>();
  for (const o of twin.occupants) byZone.set(o.zone_code, [...(byZone.get(o.zone_code) ?? []), o]);
  const sheltering = !!twin.shelter;
  return (
    <svg viewBox="0 0 790 455" width="100%" className="nx-twn-plan" role="img" aria-label={`${twin.site.name} floor plan`}>
      <defs>
        <pattern id="nx-twn-grid" width="20" height="20" patternUnits="userSpaceOnUse">
          <path d="M20 0H0V20" fill="none" stroke="rgba(171,179,191,.05)" />
        </pattern>
      </defs>
      <rect width="790" height="455" fill="url(#nx-twn-grid)" />
      <rect x="10" y="15" width="770" height="380" fill="none" stroke="#5F6B7C" strokeWidth="2" />
      {twin.zones.map((z) => {
        const safe = z.kind === "SAFE_ROOM";
        const fault = down.has(z.code);
        const fill = safe && sheltering ? "rgba(50,164,103,.12)" : z.kind === "MUSTER" ? "rgba(76,144,240,.06)" : "#1C2127";
        return (
          <g key={z.id} data-zone={z.code}>
            <rect
              x={z.x}
              y={z.y}
              width={z.w}
              height={z.h}
              fill={fill}
              stroke={safe ? "#32A467" : fault ? "#CD4246" : "#404854"}
              strokeWidth={safe || fault ? 1.8 : 1}
            />
            <text x={z.x + 8} y={z.y + 16} fill="#ABB3BF" fontSize="10.5" fontWeight="600">
              {z.name}
            </text>
            <text x={z.x + z.w - 8} y={z.y + 16} fill="#F6F7F9" fontSize="10.5" textAnchor="end" className="nx-mono">
              {z.count}
            </text>
          </g>
        );
      })}
      {twin.route && (
        <g data-testid="twin-route">
          <polyline
            points={twin.route.path.map(([x, y]) => `${x},${y}`).join(" ")}
            fill="none"
            stroke="#32A467"
            strokeWidth="3"
            strokeDasharray="7 5"
          />
          <text
            x={twin.route.path[0]?.[0] ?? 0}
            y={Math.min(450, (twin.route.path.at(-1)?.[1] ?? 0) + 60)}
            fill="#72CA9B"
            fontSize="11"
            fontWeight="700"
          >
            {twin.route.label}
          </text>
        </g>
      )}
      {twin.zones.flatMap((z) =>
        dotsIn(z, byZone.get(z.code)?.length ?? 0).map((p, k) => {
          const o = (byZone.get(z.code) ?? [])[k];
          if (!o) return null;
          return (
            <circle key={o.id} cx={p.x} cy={p.y} r="5" fill={OCCUPANT_COLOUR[o.kind]} stroke="#111418" data-kind={o.kind}>
              <title>{`${o.name ?? o.label ?? OCCUPANT_LABEL[o.kind]} · ${OCCUPANT_LABEL[o.kind]} · ${z.name}`}</title>
            </circle>
          );
        }),
      )}
    </svg>
  );
}

function SensorRow({ label, detail, status }: { label: string; detail: string | null; status: Sensor["status"] }) {
  const text = status === "OK" ? "OK" : status;
  return (
    <li className="nx-row" data-sensor={label}>
      <span className="nx-grow">{label}</span>
      {detail && <span className="nx-dim nx-twn-detail">{detail}</span>}
      <span className={`nx-sev ${SENSOR_SEV[status]}`}>{text}</span>
    </li>
  );
}

/** TWN-03: the gates, cameras, safe room, doors and alarms; the generator and comms from Fleet. */
function SensorsCard({ twin }: { twin: Twin }) {
  const named = twin.sensors.filter((s) => s.kind === "GATE" || s.kind === "BADGE_READER" || s.kind === "SAFE_ROOM");
  const group = (kinds: string[], label: string) => {
    const all = twin.sensors.filter((s) => kinds.includes(s.kind));
    if (!all.length) return null;
    const online = all.filter((s) => s.online).length;
    const worst: Sensor["status"] = all.some((s) => s.status === "OFFLINE")
      ? "OFFLINE"
      : all.some((s) => s.status === "FAULT")
        ? "FAULT"
        : all.some((s) => s.status === "DEGRADED")
          ? "DEGRADED"
          : "OK";
    return <SensorRow key={label} label={label} detail={`${online} / ${all.length} online`} status={worst} />;
  };
  return (
    <Card icon="feed" title="Sensors & systems" sub="Access control, CCTV and building systems (simulated)">
      <ul className="nx-bd nx-twn-list" aria-label="Sensors and systems">
        {named.map((s) => (
          <SensorRow key={s.code} label={s.label} detail={s.detail} status={s.status} />
        ))}
        {group(["CCTV"], "CCTV")}
        {group(["ACCESS", "ALARM"], "Doors & alarms")}
        {twin.systems.map((s) => (
          <li key={s.code} className="nx-row" data-sensor={s.label}>
            <span className="nx-grow">
              {s.label} <span className="nx-dim nx-mono">{s.code}</span>
            </span>
            <span className="nx-dim nx-twn-detail">
              {s.state.replace("_", " ").toLowerCase()}
              {s.fuel_pct !== null && ` · ${s.fuel_pct}%`}
            </span>
            <span className={`nx-sev ${s.state === "AVAILABLE" || s.state === "IN_USE" ? "ok" : "high"}`}>
              {s.state === "AVAILABLE" || s.state === "IN_USE" ? "OK" : "CHECK"}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function OccupancyCard({ twin }: { twin: Twin }) {
  const zones = twin.zones.filter((z) => z.count > 0);
  return (
    <Card
      icon="people"
      title="Occupancy by zone"
      actions={
        <span className="nx-row nx-twn-legend">
          {KINDS.map((k) => (
            <span key={k} className="nx-row">
              <i style={{ background: OCCUPANT_COLOUR[k] }} />
              {LEGEND[k]}
            </span>
          ))}
        </span>
      }
    >
      <table className="nx-table-plain nx-twn-table" aria-label="Occupancy by zone">
        <tbody>
          {zones.map((z) => (
            <tr key={z.id} data-zone={z.code}>
              <td>{z.name}</td>
              <td className="nx-mono nx-ev-right">
                <b>{z.count}</b>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

/** TWN-05: readiness items, ticked once by a Security Officer or the mission's Head of Mission. */
function ReadinessCard({ twin }: { twin: Twin }) {
  const allowed = useTwinPermissions(twin.site.id).data;
  const tick = useTickReadiness();
  return (
    <Card icon="tick-circle" title="Emergency readiness">
      <ul className="nx-bd nx-twn-list" aria-label="Emergency readiness">
        {twin.readiness.items.map((i) => (
          <li key={i.id ?? i.label} className="nx-row" data-done={i.done}>
            <Icon icon={i.done ? "tick-circle" : "circle"} intent={i.done ? "success" : undefined} />
            <span className="nx-grow">{i.label}</span>
            {i.detail && <span className="nx-dim nx-twn-detail">{i.detail}</span>}
            {i.done && i.done_by_name && <span className="nx-dim nx-twn-detail">{i.done_by_name}</span>}
            {!i.done && !i.derived && i.id && allowed?.tick_readiness && (
              <Button
                minimal
                size="small"
                text="Mark done"
                aria-label={`Mark done: ${i.label}`}
                loading={tick.isPending && tick.variables === i.id}
                onClick={() => i.id && tick.mutate(i.id)}
              />
            )}
          </li>
        ))}
      </ul>
      {tick.isError && <div className="nx-bd nx-error">{errorText(tick.error)}</div>}
    </Card>
  );
}

/** Site Twin (TWN-01..06; D-43). Plans, presence and sensors are simulated (D-19). */
export function TwinScreen() {
  const [params, setParams] = useSearchParams();
  const sites = useTwinSites();
  const list = sites.data ?? [];
  const siteId = params.get("site") ?? list[0]?.id;
  const twin = useTwin(siteId);

  if (sites.isLoading) {
    return (
      <div className="nx-pad">
        <SkeletonRows rows={6} />
      </div>
    );
  }
  if (!list.length) {
    return (
      <div className="nx-pad">
        <NonIdealState icon="grid-view" title="No floor plan yet" description="No site has a floor plan." />
      </div>
    );
  }
  const shown = twin.data;
  return (
    <div className="nx-pad">
      <div className="nx-row nx-mb nx-ev-picker">
        <span className="nx-dim">Site</span>
        <HTMLSelect
          minimal
          aria-label="Site"
          value={siteId}
          onChange={(e) => setParams({ site: e.currentTarget.value })}
          options={list.map((s) => ({ value: s.id, label: `${s.name} · ${s.mission_code}` }))}
        />
        <span className="nx-grow" />
        <span className="nx-dim">Illustrative floor plan (simulated)</span>
      </div>
      {twin.isError ? (
        <NonIdealState icon="grid-view" title="No floor plan yet" description={errorText(twin.error)} />
      ) : !shown ? (
        <SkeletonRows rows={8} />
      ) : (
        <>
          <Banner twin={shown} />
          <Kpis twin={shown} />
          <div className="nx-twn-grid">
            <Card
              icon="grid-view"
              title={`${shown.site.name} · ground floor`}
              sub="Live occupancy from access control + Wi-Fi presence (simulated)"
            >
              <div className="nx-bd nx-twn-canvas">
                <Plan twin={shown} />
              </div>
            </Card>
            <div className="nx-col">
              <SensorsCard twin={shown} />
              <OccupancyCard twin={shown} />
              <ReadinessCard twin={shown} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
