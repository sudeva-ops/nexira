import { Icon, NonIdealState } from "@blueprintjs/core";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { type Flight, type FlightDetail, type FlightStatus, IN_AIR, useFlight, useFlights } from "../../api/flights";
import { formatStamp } from "../../app/time";
import { AirMap } from "../../map/AirMap";
import { flightColour } from "../../map/geo";
import { MapSearch } from "../../map/MapSearch";
import type { Result } from "../../map/search";
import { FlashRow, type FlashTone } from "../../ui/motion";
import { Card, Kpi } from "../../ui/primitives";
import { SkeletonRows } from "../../ui/Skeleton";
import { PendingProposals } from "../queue/PendingProposals";

const NO_FLIGHTS: never[] = [];
const STATUS_LABEL: Record<string, string> = {
  SCHEDULED: "Scheduled",
  DELAYED: "Delayed",
  AIRBORNE: "Airborne",
  HOLDING: "Holding",
  DIVERTED: "Diverted",
  LANDED: "Landed",
  CANCELLED: "Cancelled",
};
const EVENT_LABEL: Record<string, string> = {
  DEPARTED: "Departed",
  DELAYED: "Delayed",
  HOLDING: "Holding",
  DIVERTED: "Diverted",
  LANDED: "Landed",
  CANCELLED: "Cancelled",
};

const FLIGHT_TONE: Partial<Record<FlightStatus, FlashTone>> = {
  DELAYED: "warning",
  HOLDING: "warning",
  DIVERTED: "danger",
  CANCELLED: "danger",
  LANDED: "success",
};

function hhmm(iso: string): string {
  return formatStamp(iso).replace(/:\d\d (?=\S+$)/, " ");
}

function statusText(f: Flight): string {
  if (f.status === "DIVERTED" || (f.status === "LANDED" && f.diverted_to)) {
    return `${STATUS_LABEL[f.status]} · ${f.diverted_city ?? f.diverted_to}`;
  }
  if (f.delay_min >= 30 && f.status !== "LANDED") return `${STATUS_LABEL[f.status]} · +${f.delay_min} min`;
  return STATUS_LABEL[f.status] ?? f.status;
}

function altitude(f: Flight): string {
  if (!IN_AIR.includes(f.status)) return f.status === "LANDED" ? "On ground" : "—";
  return f.altitude_ft ? `${f.altitude_ft.toLocaleString("en-GB")} ft · ${f.speed_kt ?? 0} kt` : "—";
}

function eventText(e: FlightDetail["events"][number]): string {
  const d = e.details;
  if (e.event_type === "DIVERTED") return `Diverted to ${String(d.to)}${d.reason ? ` · ${String(d.reason)}` : ""}`;
  if (e.event_type === "HOLDING" && d.reason) return `Holding · ${String(d.reason)}`;
  if (e.event_type === "DELAYED") return `Delayed ${String(d.minutes)} min`;
  if (e.event_type === "LANDED") return `Landed · ${String(d.airport)}`;
  if (e.event_type === "CANCELLED" && d.reason) return `Cancelled · ${String(d.reason)}`;
  return EVENT_LABEL[e.event_type] ?? e.event_type;
}

function Banner({ flight }: { flight: Flight }) {
  const who = `${flight.travellers.length} traveller${flight.travellers.length === 1 ? "" : "s"} on board`;
  if (flight.status === "HOLDING") {
    return (
      <div className="nx-banner amber nx-mb" role="alert">
        <Icon icon="warning-sign" />
        <div>
          <b>
            {flight.flight_number} holding near {flight.to_city}
          </b>{" "}
          with {who} ({flight.trip_reference}). Proposals to divert or rebook come with the Travel &amp; Air
          agent.
        </div>
      </div>
    );
  }
  return (
    <div className="nx-banner red nx-mb" role="alert">
      <Icon icon="route" />
      <div>
        <b>
          {flight.flight_number} diverted to {flight.diverted_city ?? flight.diverted_to}
        </b>{" "}
        with {who} ({flight.trip_reference}). Their location updates when it lands.
      </div>
    </div>
  );
}

function Detail({ flight }: { flight: FlightDetail }) {
  return (
    <Card
      icon="airplane"
      title={flight.flight_number}
      sub={`${flight.from_city} → ${flight.diverted_city ?? flight.to_city}`}
    >
      <div className="nx-bd nx-flight-detail">
        <div style={{ color: flightColour(flight.status) }}>
          <b>{statusText(flight)}</b>
        </div>
        <table className="nx-kv">
          <tbody>
            <tr>
              <td className="nx-dim">Travellers</td>
              <td>{flight.travellers.join(", ") || "—"}</td>
            </tr>
            <tr>
              <td className="nx-dim">Trip</td>
              <td>
                <Link to={`/journeys?trip=${flight.trip_id}`}>{flight.trip_reference}</Link>
              </td>
            </tr>
            <tr>
              <td className="nx-dim">Altitude / speed</td>
              <td className="nx-mono">{altitude(flight)}</td>
            </tr>
            <tr>
              <td className="nx-dim">Scheduled</td>
              <td className="nx-mono">
                {hhmm(flight.scheduled_dep)} → {hhmm(flight.scheduled_arr)}
              </td>
            </tr>
            <tr>
              <td className="nx-dim">ETA</td>
              <td className="nx-mono">{flight.status === "LANDED" ? "Arrived" : hhmm(flight.estimated_arr)}</td>
            </tr>
          </tbody>
        </table>
        <PendingProposals tripId={flight.trip_id} />
        <div className="nx-lbl">Flight events</div>
        {flight.events.length === 0 ? (
          <div className="nx-dim">Nothing yet</div>
        ) : (
          <div className="nx-tl" aria-label="Flight events">
            {flight.events.map((e, n) => (
              <div key={n} style={{ ["--c" as string]: flightColour(e.event_type === "DEPARTED" ? "AIRBORNE" : e.event_type) }}>
                <span>{formatStamp(e.occurred_at)}</span>
                <br />
                <b>{eventText(e)}</b>
              </div>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}

/** Air Travel Tracking (AT-01..08; D-30, D-33): our travellers in the air. */
export function AirScreen() {
  const [params, setParams] = useSearchParams();
  const flights = useFlights();
  const list = flights.data ?? NO_FLIGHTS;
  // SRC-02: only our travellers' flights, as the Air map has them (AT-01, D-33), then places.
  const records = useMemo<Result[]>(
    () =>
      list.flatMap((f) =>
        f.lon === null || f.lat === null
          ? []
          : [
              {
                kind: "FLIGHT" as const,
                id: f.id,
                label: f.flight_number,
                detail: `${f.from_airport} → ${f.to_airport}`,
                lon: f.lon,
                lat: f.lat,
                zoom: 5,
              },
            ],
      ),
    [list],
  );
  const [fly, setFly] = useState<{ lon: number; lat: number; zoom: number } | null>(null);
  const selectedId = params.get("flight") ?? undefined;
  const selected = useFlight(selectedId).data;
  const select = (id: string) => setParams({ flight: id });
  const airborne = list.filter((f) => IN_AIR.includes(f.status));
  const disrupted = list.filter((f) => f.disrupted && f.status !== "LANDED" && f.status !== "CANCELLED");

  return (
    <div className="nx-pad">
      {list
        .filter((f) => f.status === "HOLDING" || f.status === "DIVERTED")
        .map((f) => (
          <Banner key={f.id} flight={f} />
        ))}
      <div className="nx-g4">
        <Kpi
          icon="people"
          label="Officials airborne"
          value={airborne.reduce((n, f) => n + f.travellers.length, 0)}
          detail={`${airborne.length} flight${airborne.length === 1 ? "" : "s"} · from approved trips`}
        />
        <Kpi
          icon="warning-sign"
          label="Disrupted flights"
          value={disrupted.length}
          detail={disrupted.length ? disrupted.map((f) => `${f.flight_number} ${STATUS_LABEL[f.status]?.toLowerCase()}`).join(" · ") : "All on schedule"}
          alert={disrupted.length > 0}
        />
        <Kpi icon="airplane" label="Tracked flights" value={list.length} detail="Next 24 hours and in the air" />
        <Kpi icon="satellite" label="Position source" value="Simulated" detail="Flight-data provider not connected (D-19)" />
      </div>

      <div className="nx-air-grid">
        <div className="nx-col">
          <Card icon="globe" title="Live air picture" sub="Only flights carrying our travellers · positions simulated">
            <div className="nx-air-mapwrap">
              <AirMap flights={list} selectedId={selectedId ?? null} onSelect={select} fly={fly} />
              <MapSearch
                records={records}
                placeholder="Search flights, places or coordinates"
                onPick={(r) => (r.kind === "FLIGHT" ? select(r.id) : setFly({ lon: r.lon, lat: r.lat, zoom: Math.min(r.zoom, 6) }))}
              />
            </div>
          </Card>
          <Card icon="airplane" title="Tracked flights" sub={`${list.length} shown`}>
            {flights.isLoading ? (
              <SkeletonRows />
            ) : list.length === 0 ? (
              <NonIdealState icon="airplane" title="No tracked flights" description="Approved trips' flights appear 24 hours before departure." />
            ) : (
              <table className="nx-table-plain" aria-label="Tracked flights">
                <thead>
                  <tr>
                    <th>Flight</th>
                    <th>Travellers</th>
                    <th>Route</th>
                    <th>Progress</th>
                    <th>Altitude</th>
                    <th>ETA</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {list.map((f) => (
                    <FlashRow
                      key={f.id}
                      watch={`${f.status} ${f.diverted_to} ${f.estimated_arr}`}
                      tone={FLIGHT_TONE[f.status] ?? "info"}
                      className={f.id === selectedId ? "on" : undefined}
                      onClick={() => select(f.id)}
                    >
                      <td className="nx-mono">
                        <button type="button" className="nx-linkbtn" onClick={() => select(f.id)}>
                          <b>{f.flight_number}</b>
                        </button>
                      </td>
                      <td>
                        {f.travellers.length} · {f.trip_reference}
                      </td>
                      <td className="nx-nowrap">
                        {f.from_airport} → {f.diverted_to ?? f.to_airport}
                      </td>
                      <td>
                        <div className="nx-bar" style={{ width: 70 }}>
                          <i style={{ width: `${Math.round(f.progress * 100)}%`, background: flightColour(f.status) }} />
                        </div>
                      </td>
                      <td className="nx-mono nx-nowrap">{altitude(f)}</td>
                      <td className="nx-mono nx-nowrap">{f.status === "LANDED" ? "Arrived" : hhmm(f.estimated_arr)}</td>
                      <td style={{ color: flightColour(f.status) }}>{statusText(f)}</td>
                    </FlashRow>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </div>
        <div className="nx-col">
          {selected && <Detail flight={selected} />}
          <Card icon="shield" title="Safeguards">
            <ul className="nx-bd nx-safeguards" aria-label="Safeguards">
              <li>Only flights carrying our travellers, from approved trips, are tracked (AT-01).</li>
              <li>VIP and ministerial (restricted) trips are never tracked or shown (AT-05).</li>
              <li>Positions and statuses are simulated; no flight-data provider is called (D-33).</li>
            </ul>
          </Card>
        </div>
      </div>
    </div>
  );
}
