import { Button, Dialog, DialogBody, HTMLSelect, Icon, NonIdealState, Switch } from "@blueprintjs/core";
import { type KeyboardEvent, type MouseEvent, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { ApiError } from "../../api/client";
import { formatTime, HOME_TZ } from "../../app/time";
import {
  drillAgo,
  OCCUPANT_COLOUR,
  OCCUPANT_LABEL,
  type OccupantKind,
  SENSOR_SEV,
  type Sensor,
  type Movement,
  type Twin,
  useMovements,
  useTickReadiness,
  useTwin,
  useTwinPermissions,
  useTwinSites,
} from "../../api/twin";
import { Card, Kpi } from "../../ui/primitives";
import { SkeletonRows } from "../../ui/Skeleton";
import { CctvWall } from "./CctvWall";
import { furniture } from "./furniture";
import { drift, shareFill, spots } from "./motion";
import { cone, type Coverage, coverage, placed, target } from "./coverage";

const KINDS: OccupantKind[] = ["STAFF", "GUARD", "VISITOR"];
const ACCESS = new Set(["GATE", "BADGE_READER"]);
const LEGEND: Record<OccupantKind, string> = { STAFF: "Staff", GUARD: "Guard", VISITOR: "Visitor" };

const COVERAGE_KEY = "nexira.twin.coverage"; // TWN-09: remembered for the tab

function remembered(): boolean {
  try {
    return sessionStorage.getItem(COVERAGE_KEY) === "on";
  } catch {
    return false; // storage blocked: off, as on a first visit
  }
}

function remember(on: boolean): void {
  try {
    sessionStorage.setItem(COVERAGE_KEY, on ? "on" : "off");
  } catch {
    // storage blocked: the toggle still works for this view
  }
}

/** "Gate 2, Lobby & reception" */
function zoneList(zones: { name: string }[]): string {
  return zones.map((z) => z.name).join(", ");
}

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

function Kpis({ twin, cover }: { twin: Twin; cover: Coverage }) {
  const c = twin.counts;
  const ago = drillAgo(twin.readiness.last_drill_on);
  const down = twin.sensors.filter((s) => s.kind === "CCTV" && !s.online).length;
  return (
    <div className="nx-g5 nx-mb">
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
        icon="eye-open"
        label="Camera coverage"
        value={cover.pct === null ? "—" : `${cover.pct}%`}
        detail={
          cover.notCovered.length
            ? `Not covered: ${zoneList(cover.notCovered)}`
            : down
              ? `${plural(down, "camera")} down`
              : "All cameras online"
        }
        alert={down > 0}
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

/** TWN-09: each camera's cone from its mount, clipped to its zone; what no online camera sees
 * is hatched. */
function CoverageLayer({ twin, cover }: { twin: Twin; cover: Coverage }) {
  return (
    <g className="nx-twn-coverage" data-testid="twin-coverage">
      {placed(twin).map((c) => (
        <g key={c.sensor.code} data-camera={c.sensor.code} data-state={c.sensor.online ? "online" : "down"}>
          <path
            d={cone(c)}
            fill={c.sensor.online ? "rgba(76,144,240,.16)" : "rgba(205,66,70,.08)"}
            stroke={c.sensor.online ? "rgba(76,144,240,.7)" : "#E76A6E"}
            strokeWidth="1.2"
            strokeDasharray={c.sensor.online ? undefined : "5 4"}
          />
          <circle cx={c.mount.x} cy={c.mount.y} r="3" fill={c.sensor.online ? "#4C90F0" : "#E76A6E"} />
        </g>
      ))}
      <g data-testid="twin-gaps">
        {cover.zones.flatMap((z) =>
          z.gaps.map((g) => (
            <rect key={`${z.zone.code}-${g.x}-${g.y}`} x={g.x} y={g.y} width={g.w} height={g.h} fill="url(#nx-twn-gap)" />
          )),
        )}
      </g>
    </g>
  );
}

/** TWN-01, TWN-02, TWN-04, TWN-09: the plan with rooms, counts, people as dots and the overlays.
 * With coverage on, a zone opens the camera that watches it (TWN-10). */
function Plan({
  twin,
  cover,
  onZone,
}: {
  twin: Twin;
  cover: Coverage | null;
  onZone: (code: string) => void;
}) {
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
        <pattern id="nx-twn-gap" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <path d="M0 0V5" stroke="rgba(231,106,110,.6)" strokeWidth="1.5" />
        </pattern>
      </defs>
      <rect width="790" height="455" fill="url(#nx-twn-grid)" />
      <rect x="10" y="15" width="770" height="380" fill="none" stroke="#5F6B7C" strokeWidth="2" />
      {twin.zones.map((z) => {
        const safe = z.kind === "SAFE_ROOM";
        const fault = down.has(z.code);
        const fill = safe && sheltering ? "rgba(50,164,103,.12)" : shareFill(z.count, twin.counts.on_site);
        const pick = cover
          ? {
              role: "button",
              tabIndex: 0,
              "aria-label": `Open the camera on ${z.name}`,
              className: "nx-twn-pick",
              // The zone lets go of focus so the camera's dialog takes it (and Escape closes it).
              onClick: (e: MouseEvent<SVGGElement>) => {
                e.currentTarget.blur();
                onZone(z.code);
              },
              onKeyDown: (e: KeyboardEvent<SVGGElement>) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  e.currentTarget.blur();
                  onZone(z.code);
                }
              },
            }
          : {};
        return (
          <g key={z.id} data-zone={z.code} {...pick}>
            <rect
              x={z.x}
              y={z.y}
              width={z.w}
              height={z.h}
              fill={fill}
              stroke={safe ? "#32A467" : fault ? "#CD4246" : "#404854"}
              strokeWidth={safe || fault ? 1.8 : 1}
            />
            {/* TWN-16: faint furniture, under the people and the cones. */}
            <g className="nx-twn-furniture" aria-hidden="true">
              {furniture(z).map((f, i) =>
                f.shape === "rect" ? (
                  <rect key={i} x={f.x} y={f.y} width={f.w} height={f.h} rx={f.r} />
                ) : f.shape === "circle" ? (
                  <circle key={i} cx={f.cx} cy={f.cy} r={f.r} />
                ) : (
                  <line key={i} x1={f.x1} y1={f.y1} x2={f.x2} y2={f.y2} />
                ),
              )}
            </g>
            <text x={z.x + 8} y={z.y + 16} fill="#ABB3BF" fontSize="10.5" fontWeight="600">
              {z.name}
            </text>
            <text x={z.x + z.w - 8} y={z.y + 16} fill="#F6F7F9" fontSize="10.5" textAnchor="end" className="nx-mono">
              {z.count}
            </text>
          </g>
        );
      })}
      {cover && <CoverageLayer twin={twin} cover={cover} />}
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
      {/* TWN-12: each person at a stable spot in the zone, drifting; a move walks there (CSS). */}
      {twin.zones.flatMap((z) => {
        const here = byZone.get(z.code) ?? [];
        const at = spots(z, here.map((o) => o.id));
        return here.map((o) => {
          const p = at.get(o.id);
          if (!p) return null;
          const d = drift(o.id);
          return (
            <g
              key={o.id}
              className="nx-twn-person"
              style={{ transform: `translate(${p.x}px, ${p.y}px)` }}
              data-kind={o.kind}
              data-zone={z.code}
            >
              <circle
                r="5"
                fill={OCCUPANT_COLOUR[o.kind]}
                stroke="#111418"
                style={{ animationDelay: d.delay, animationDuration: d.period }}
              >
                <title>{`${o.name ?? o.label ?? OCCUPANT_LABEL[o.kind]} · ${OCCUPANT_LABEL[o.kind]} · ${z.name}`}</title>
              </circle>
            </g>
          );
        });
      })}
    </svg>
  );
}

/** TWN-14: the last movements under the plan, newest first, and today's figures; never who. */
function MovementStrip({ siteId }: { siteId: string }) {
  const data = useMovements(siteId).data;
  if (!data) return null;
  const where = (m: Movement) =>
    m.from_zone === null ? `Arrived · ${m.to_zone ?? "?"}` : m.to_zone === null ? `Left · ${m.from_zone}` : `${m.from_zone} → ${m.to_zone}`;
  return (
    <div className="nx-twn-moves" aria-label="Recent movements">
      <span className="nx-twn-moves-today">
        Today <b>{data.arrivals_today}</b> in · <b>{data.departures_today}</b> out ·{" "}
        <b>{data.visitors_waiting}</b> visitor{data.visitors_waiting === 1 ? "" : "s"} waiting
      </span>
      <ol>
        {data.movements.slice(0, 6).map((m) => (
          <li key={`${m.at}-${m.kind}`}>
            <span className="nx-mono nx-dim">{formatTime(new Date(m.at), HOME_TZ).slice(0, 5)}</span> {where(m)} ·{" "}
            <span className="nx-dim">{OCCUPANT_LABEL[m.kind]}</span>
          </li>
        ))}
        {data.movements.length === 0 && <li className="nx-dim">No movement recorded yet</li>}
      </ol>
    </div>
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

/** TWN-10: a camera in the list opens it enlarged. Those down are always listed. */
function CameraRows({ twin, onCamera }: { twin: Twin; onCamera: (code: string) => void }) {
  const [all, setAll] = useState(false);
  const cameras = twin.sensors.filter((s) => s.kind === "CCTV");
  const zones = new Map(twin.zones.map((z) => [z.code, z.name]));
  const shown = all ? cameras : cameras.filter((s) => !s.online);
  return (
    <>
      {shown.map((s) => (
        <li key={s.code} className="nx-row nx-twn-cam" data-sensor={s.code}>
          <button type="button" className="nx-twn-camlink nx-grow" onClick={() => onCamera(s.code)}>
            <Icon icon="mobile-video" size={11} /> {s.code}
            {s.zone_code && <span className="nx-dim"> · {zones.get(s.zone_code) ?? s.zone_code}</span>}
          </button>
          {s.detail && <span className="nx-dim nx-twn-detail">{s.detail}</span>}
          <span className={`nx-sev ${SENSOR_SEV[s.status]}`}>{s.status}</span>
        </li>
      ))}
      {cameras.length > 0 && (
        <li className="nx-row nx-twn-cam nx-twn-cam-more">
          <button type="button" className="nx-twn-camlink nx-dim" onClick={() => setAll((a) => !a)}>
            {all ? "Cameras down only" : `All ${cameras.length} cameras`}
          </button>
        </li>
      )}
    </>
  );
}

/** TWN-03: the gates, cameras, safe room, doors and alarms; the generator and comms from Fleet. */
function SensorsCard({ twin, onCamera }: { twin: Twin; onCamera: (code: string) => void }) {
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
        <CameraRows twin={twin} onCamera={onCamera} />
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
  const [covering, setCovering] = useState(remembered);
  const cover = useMemo(() => (twin.data ? coverage(twin.data) : null), [twin.data]);
  // TWN-10: ?camera= (a camera, or any sensor: the camera watching its zone) or ?zone=.
  const ask = { camera: params.get("camera"), zone: params.get("zone") };
  const look = (next: { camera?: string; zone?: string } | null) =>
    setParams(
      (now) => {
        const out = new URLSearchParams(now);
        out.delete("camera");
        out.delete("zone");
        if (next?.camera) out.set("camera", next.camera);
        if (next?.zone) out.set("zone", next.zone);
        return out;
      },
      { replace: true },
    );

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
  const asked = shown && (ask.camera || ask.zone) ? target(shown, ask) : null;
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
          {cover && <Kpis twin={shown} cover={cover} />}
          <div className="nx-twn-grid">
            <div className="nx-col">
              <Card
                icon="grid-view"
                title={`${shown.site.name} · ground floor`}
                sub="Live occupancy from access control + Wi-Fi presence (simulated)"
                actions={
                  <Switch
                    className="nx-twn-switch"
                    label="Camera coverage"
                    checked={covering}
                    onChange={(e) => {
                      const on = e.currentTarget.checked;
                      setCovering(on);
                      remember(on);
                    }}
                  />
                }
              >
                <div className="nx-bd nx-twn-canvas">
                  <Plan twin={shown} cover={covering ? cover : null} onZone={(zone) => look({ zone })} />
                  <MovementStrip siteId={shown.site.id} />
                  {covering && cover && (
                    <div className="nx-twn-cover" aria-label="What the cameras see">
                      {cover.notCovered.length ? (
                        <span className="nx-twn-uncovered">
                          <Icon icon="eye-off" size={12} /> Not covered now: {zoneList(cover.notCovered)}
                        </span>
                      ) : (
                        <span>Every zone has a working camera</span>
                      )}
                      {cover.blind.length > 0 && (
                        <span className="nx-dim">
                          Blind spots: {cover.blind.map((b) => `${b.zone.name} (${b.pct}%)`).join(", ")}
                        </span>
                      )}
                      <span className="nx-grow" />
                      <span className="nx-twn-key">
                        <i className="on" /> Online <i className="down" /> Down <i className="gap" /> Not seen
                      </span>
                    </div>
                  )}
                </div>
              </Card>
              <CctvWall
                twin={shown}
                open={asked?.camera?.code ?? null}
                onOpen={(camera) => look(camera ? { camera } : null)}
              />
              <Dialog
                isOpen={!!asked && !asked.camera}
                onClose={() => look(null)}
                title={asked?.zone?.name ?? "Camera"}
                icon="mobile-video"
                className="bp6-dark"
              >
                <DialogBody>
                  <NonIdealState icon="eye-off" title="No camera covers this zone" />
                </DialogBody>
              </Dialog>
            </div>
            <div className="nx-col">
              <SensorsCard twin={shown} onCamera={(camera) => look({ camera })} />
              <OccupancyCard twin={shown} />
              <ReadinessCard twin={shown} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
