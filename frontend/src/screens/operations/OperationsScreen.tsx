import { Spinner } from "@blueprintjs/core";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { useAnnotations } from "../../api/annotations";
import { DEFAULT_RADIUS_KM, type Near, nearParams, parseNear } from "../../api/nearby";
import { type Incident, useIncident, useIncidents, useOperationsSummary, useSignals } from "../../api/intel";
import { useMissions, useSites } from "../../api/people";
import { useWeather } from "../../api/weather";
import { addPoint, canFinish, type Draft } from "../../map/annotations";
import { MapSearch } from "../../map/MapSearch";
import { RECORD_ZOOM, type Result } from "../../map/search";
import { TileRow } from "../../ui/TileRow";
import { Card, Kpi } from "../../ui/primitives";
import { buckets } from "../../ui/spark";
import { useNow } from "../../ui/useNow";
import { AnnotationCard, AnnotationForm, AnnotationTools } from "./Annotations";
import { ImpactPanel } from "./ImpactPanel";
import { LiveFeed } from "./LiveFeed";
import { NearbyPanel } from "./NearbyPanel";
import { WeatherPanel } from "./WeatherPanel";

const NO_EXPOSURE: never[] = [];
const NO_WEATHER: never[] = [];
const NO_ANNOTATIONS: never[] = [];
const NO_MISSIONS: never[] = [];
const NO_INCIDENTS: never[] = [];
const MARK_MS = 10_000; // a search result's point stays marked this long (SRC-04)

// MapLibre is most of the bundle; load it only with this screen.
const OperationsMap = lazy(() =>
  import("../../map/OperationsMap").then((m) => ({ default: m.OperationsMap })),
);

/** Global Operations (OPS-01..04). Every figure comes from the API (D-27). */
const DAY_MS = 24 * 3_600_000;

export function OperationsScreen() {
  const [params, setParams] = useSearchParams();
  const selectedId = params.get("incident");
  // NBY-06: the point and radius live in the address (replaced, not pushed, as they change).
  const near = parseNear(params.get("near"), params.get("r"));
  const [fly, setFly] = useState<{ lon: number; lat: number; zoom?: number } | null>(null);
  const [mark, setMark] = useState<{ lon: number; lat: number } | null>(null);
  useEffect(() => {
    if (!mark) return;
    const timer = window.setTimeout(() => setMark(null), MARK_MS);
    return () => window.clearTimeout(timer);
  }, [mark]);
  const showNear = (n: Near) => setParams(nearParams(n), { replace: true });
  const summary = useOperationsSummary().data;
  const missions = useMissions().data ?? NO_MISSIONS;
  const incidentsQuery = useIncidents("ACTIVE");
  const incidents = incidentsQuery.data ?? NO_INCIDENTS;
  const signals = useSignals(50).data ?? [];
  // GFX-07: signals per hour over the last day, from the same list at its largest page.
  const daySignals = useSignals(500).data ?? [];
  const now = useNow(true, 60_000);
  const selected = useIncident(selectedId ?? undefined).data;
  const weatherQuery = useWeather();
  const weather = weatherQuery.data ?? NO_WEATHER;
  const [showWeather, setShowWeather] = useState(true);
  // Map annotations (ANN-01..04, D-52).
  const annotationsQuery = useAnnotations();
  const annotations = annotationsQuery.data?.annotations ?? NO_ANNOTATIONS;
  const [showAnnotations, setShowAnnotations] = useState(true);
  const [zoom, setZoom] = useState(0);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [finished, setFinished] = useState<Draft | null>(null);
  const [pickedId, setPickedId] = useState<string | null>(null);
  const picked = annotations.find((a) => a.id === pickedId);
  const finish = () => {
    if (draft && canFinish(draft)) {
      setFinished(draft);
      setDraft(null);
    }
  };
  // Enter finishes a line or an area, Escape cancels (plan G-3).
  useEffect(() => {
    if (!draft) return;
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDraft(null);
      if (e.key === "Enter" && canFinish(draft)) {
        setFinished(draft);
        setDraft(null);
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [draft]);

  const select = (incident: Incident) => setParams({ incident: incident.id });
  // SRC-02: the platform's own records, matched in the browser from what is already loaded.
  const sites = useSites("").data?.items;
  const records = useMemo<Result[]>(
    () => [
      ...missions.map((m) => ({
        kind: "MISSION" as const,
        id: m.id,
        label: m.city,
        detail: `${m.code} · ${m.country_code}`,
        lon: m.lon,
        lat: m.lat,
        zoom: RECORD_ZOOM,
      })),
      ...(sites ?? []).map((s) => ({
        kind: "SITE" as const,
        id: s.id,
        label: s.name,
        detail: `${s.mission_code} · ${s.city}`,
        lon: s.lon,
        lat: s.lat,
        zoom: RECORD_ZOOM,
      })),
      ...incidents.map((i) => ({
        kind: "INCIDENT" as const,
        id: i.id,
        label: i.reference,
        detail: i.title,
        lon: i.lon,
        lat: i.lat,
        zoom: RECORD_ZOOM,
      })),
    ],
    [missions, sites, incidents],
  );
  const found = (r: Result) => {
    if (r.kind === "INCIDENT") {
      setParams({ incident: r.id });
      return;
    }
    setFly({ lon: r.lon, lat: r.lat, zoom: r.zoom });
    setMark({ lon: r.lon, lat: r.lat });
  };
  const worst = incidents.find((i) => i.severity === summary?.highest_active_severity);
  const posture = summary?.highest_active_severity ?? null;

  return (
    <div className="nx-ops">
      <TileRow columns={5}>
        <Kpi
          icon="office"
          label="Missions monitored"
          value={summary?.missions ?? "—"}
          detail={
            summary && (
              <>
                <span className={summary.missions_critical ? "down" : "up"}>
                  {summary.missions_critical
                    ? `${summary.missions_critical} critical`
                    : "None critical"}
                </span>{" "}
                · {summary.missions_elevated} elevated
              </>
            )
          }
        />
        <Kpi
          icon="people"
          label="Personnel tracked"
          value={summary?.personnel ?? "—"}
          detail={
            summary?.avg_location_confidence != null &&
            `${summary.avg_location_confidence}% avg. location confidence`
          }
        />
        <Kpi
          icon="airplane"
          label="Travellers in transit"
          value={summary?.travellers_active ?? "—"}
          detail={summary && `${summary.trips_active} active trips`}
        />
        <Kpi
          icon="feed"
          label="Signals · 24h"
          value={summary?.signals_24h ?? "—"}
          trend={{
            values: buckets(daySignals.map((x) => x.received_at), now, DAY_MS, 24),
            label: "Signals per hour, last 24 hours",
          }}
          alert={!!summary?.incidents_active}
          detail={
            summary &&
            (summary.incidents_active
              ? `${summary.incidents_active} active incident${summary.incidents_active === 1 ? "" : "s"}`
              : "No active incidents")
          }
        />
        <Kpi
          icon="shield"
          label="Highest active severity"
          value={<span className={posture ? `nx-posture ${posture}` : "nx-posture"}>{posture ?? "NONE"}</span>}
          alert={posture === "CRITICAL"}
          detail={worst ? `Driven by ${worst.reference}` : "No active incidents"}
        />
      </TileRow>
      <div className="nx-card nx-mapwrap">
        <Suspense fallback={<Spinner className="nx-map-loading" />}>
          <OperationsMap
            missions={missions}
            incidents={incidents}
            incidentsLoaded={incidentsQuery.isSuccess}
            exposure={selected?.exposure ?? NO_EXPOSURE}
            selectedId={selectedId}
            onSelect={select}
            weather={showWeather ? weather : NO_WEATHER}
            weatherAt={weatherQuery.dataUpdatedAt}
            annotations={showAnnotations ? annotations : NO_ANNOTATIONS}
            draft={draft}
            onDrawPoint={(p) => {
              const next = draft ? addPoint(draft, p) : null;
              // A mark is done with its one click; a line or an area waits for Finish.
              if (next?.kind === "MARK") {
                setFinished(next);
                setDraft(null);
              } else {
                setDraft(next);
              }
            }}
            onDrawFinish={finish}
            onPickAnnotation={setPickedId}
            onZoom={setZoom}
            near={near}
            onNearby={([lon, lat]) => showNear({ lon, lat, km: near?.km ?? DEFAULT_RADIUS_KM })}
            fly={fly}
            mark={mark}
          />
        </Suspense>
        <div className="nx-legend">
          <span className="nx-chip"><i style={{ background: "#4C90F0" }} />Mission</span>
          <span className="nx-chip"><i style={{ background: "#EC9A3C" }} />Elevated</span>
          <span className="nx-chip"><i style={{ background: "#CD4246" }} />Critical</span>
          <span className="nx-chip"><i style={{ background: "#8ABBFF" }} />Staff</span>
          <span className="nx-chip"><i style={{ background: "#BDADFF" }} />Delegate</span>
          <span className="nx-chip"><i style={{ background: "#FBB360" }} />Citizen</span>
          <button
            type="button"
            className="nx-chip nx-chip-toggle"
            aria-pressed={showWeather}
            onClick={() => setShowWeather((on) => !on)}
          >
            <i style={{ background: showWeather ? "#8ABBFF" : "transparent" }} />
            Weather
          </button>
          <button
            type="button"
            className="nx-chip nx-chip-toggle"
            aria-pressed={showAnnotations}
            onClick={() => setShowAnnotations((on) => !on)}
          >
            <i style={{ background: showAnnotations ? "#BD6BBD" : "transparent" }} />
            Annotations
          </button>
        </div>
        <MapSearch
          records={records}
          onPick={found}
          onNearby={(r) => showNear({ lon: r.lon, lat: r.lat, km: near?.km ?? DEFAULT_RADIUS_KM })}
        />
        {annotationsQuery.data?.can_add && (
          <AnnotationTools
            zoom={zoom}
            draft={draft}
            onStart={(kind) => {
              setPickedId(null);
              setDraft({ kind, points: [] });
            }}
            onFinish={finish}
            onCancel={() => setDraft(null)}
          />
        )}
        {picked && showAnnotations && <AnnotationCard annotation={picked} onClose={() => setPickedId(null)} />}
        {finished && (
          <AnnotationForm
            draft={finished}
            incidents={incidents}
            incidentId={selectedId}
            onClose={() => setFinished(null)}
          />
        )}
        <div className="nx-maptitle">
          {selected ? (
            <>
              <div className="a">
                FOCUS · {selected.place_label?.toUpperCase()} ·{" "}
                {Math.round(selected.impact_radius_m / 1000)} KM IMPACT ZONE
              </div>
              <div className="b">
                {selected.reference} · {selected.title}
              </div>
            </>
          ) : (
            <>
              <div className="a">GLOBAL VIEW · {missions.length} MISSIONS</div>
              <div className="b">
                {incidents.length
                  ? `${incidents.length} active incident${incidents.length === 1 ? "" : "s"}`
                  : "No active incidents"}
              </div>
            </>
          )}
        </div>
      </div>
      <div className="nx-sidecol">
        {near ? (
          <NearbyPanel
            near={near}
            onRadius={(km) => showNear({ ...near, km })}
            onClose={() => setParams({})}
            onFly={(lon, lat) => setFly({ lon, lat })}
            onIncident={(id) => setParams({ incident: id })}
          />
        ) : selectedId ? (
          <ImpactPanel
            incidentId={selectedId}
            onClose={() => setParams({})}
            onNearby={(lon, lat) => showNear({ lon, lat, km: DEFAULT_RADIUS_KM })}
          />
        ) : (
          <Card icon="feed" title="Live intelligence feed" className="nx-side">
            <LiveFeed incidents={incidents} signals={signals} onSelect={select} />
          </Card>
        )}
        <WeatherPanel />
      </div>
    </div>
  );
}
