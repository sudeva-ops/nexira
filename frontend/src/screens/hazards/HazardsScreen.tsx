import { Button, Icon } from "@blueprintjs/core";
import { useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../../api/client";
import {
  ARMED_PLAYBOOK,
  armable,
  type ClimateRisk,
  exposedMissions,
  exposureText,
  HAZARD_CATEGORIES,
  HAZARD_ICON,
  HAZARD_LABEL,
  type HazardCategory,
  type HazardEvent,
  hoursUntil,
  landfallText,
  LANDFALL_LEAD_H,
  measureText,
  useArm,
  useArmingPermissions,
  useClimate,
  useDisarm,
  useHazards,
  useStartArmedNow,
} from "../../api/hazards";
import type { Severity } from "../../api/intel";
import { ago, formatStamp } from "../../app/time";
import { FlashRow } from "../../ui/motion";
import { Card, Kpi, Sev } from "../../ui/primitives";
import { SkeletonRows } from "../../ui/Skeleton";
import { useNow } from "../../ui/useNow";
import { TileRow } from "../../ui/TileRow";
import { Empty } from "../../ui/Empty";

const ALL = "ALL";
const LEVELS: Severity[] = ["CRITICAL", "HIGH", "MODERATE", "LOW"];
const LEVEL_WORD: Record<Severity, string> = { CRITICAL: "Critical", HIGH: "High", MODERATE: "Moderate", LOW: "Low" };

/** The hours left until `iso` on the hazard clock, re-read as time passes (HZ-04). */
type Until = (iso: string | null) => number | null;

function useUntil(clockNow: string | undefined, readAt: number): Until {
  const now = useNow(!!clockNow, 30_000);
  return (iso) => (iso && clockNow ? hoursUntil(iso, clockNow, Math.max(0, now - readAt)) : null);
}

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "Not done";
}

/** HZ-05, HZ-09, HZ-10: arm, start now or disarm, each shown only when the backend allows it. */
function ArmingBanner({ e, until }: { e: HazardEvent; until: Until }) {
  const allowed = useArmingPermissions(e.incident_id).data;
  const arm = useArm();
  const startNow = useStartArmedNow();
  const disarm = useDisarm();
  const landfall = until(e.landfall_at);
  const city = e.nearest_mission_city ?? e.place_label ?? "the mission";
  const armed = e.armed?.status === "SCHEDULED" ? e.armed : null;
  const startsIn = armed ? until(armed.scheduled_for) : null;
  const failed = [arm, startNow, disarm].find((m) => m.isError);

  return (
    <div className="nx-bd">
      <div className={`nx-banner ${armed ? "green" : "amber"}`} role="status" data-testid={`arming-${e.reference}`}>
        <Icon icon={armed ? "time" : "warning-sign"} />
        <div className="nx-grow">
          {armed ? (
            <>
              <b>
                {armed.playbook_code} armed for {city}
                {startsIn !== null && ` · starts in ${Math.max(0, Math.round(startsIn))} h`}.
              </b>{" "}
              It starts by itself {LANDFALL_LEAD_H} h before landfall
              {armed.scheduled_for && ` (${formatStamp(armed.scheduled_for)})`}.
              {armed.forecast_changed && (
                <span className="nx-hz-changed"> The forecast has changed since it was armed.</span>
              )}
            </>
          ) : (
            <>
              <b>
                Cyclone forecast for {city}
                {landfall !== null && `: ${landfallText(landfall)}`}.
              </b>{" "}
              Recommended: arm {ARMED_PLAYBOOK} Severe weather, to start {LANDFALL_LEAD_H} h before landfall.
            </>
          )}
          {failed && <div className="nx-error">{errorText(failed.error)}</div>}
        </div>
        {!armed && allowed?.arm_playbook && (
          <Button size="small" text="Arm playbook" loading={arm.isPending} onClick={() => arm.mutate(e.incident_id)} />
        )}
        {armed && allowed?.start_armed && (
          <Button
            size="small"
            intent="primary"
            text="Start now"
            loading={startNow.isPending}
            onClick={() => startNow.mutate(armed.run_id)}
          />
        )}
        {armed && allowed?.disarm && (
          <Button
            size="small"
            minimal
            text="Disarm"
            loading={disarm.isPending}
            onClick={() => disarm.mutate(armed.run_id)}
          />
        )}
      </div>
    </div>
  );
}

function ArmedNote({ e }: { e: HazardEvent }) {
  if (!e.armed || e.armed.status === "SCHEDULED" || e.armed.status === "DISARMED") return null;
  return (
    <div className="nx-dim">
      {e.armed.playbook_code} {e.armed.status.toLowerCase().replace("_", " ")} ·{" "}
      <Link to="/playbooks">Response Playbooks</Link>
    </div>
  );
}

function EventRow({ e, until }: { e: HazardEvent; until: Until }) {
  const measure = measureText(e);
  const landfall = until(e.landfall_at);
  return (
    <FlashRow data-incident={e.incident_id} watch={`${e.severity} ${e.updated_at} ${e.armed?.status ?? ""}`}>
      <td className="nx-nowrap">
        <Icon icon={HAZARD_ICON[e.category]} size={12} className="nx-hz-icon" /> {HAZARD_LABEL[e.category]}
      </td>
      <td>
        <b>{e.title}</b>
        <div className="nx-dim">
          {e.reference}
          {measure && ` · ${measure}`}
        </div>
        <ArmedNote e={e} />
      </td>
      <td>{e.place_label ?? "—"}</td>
      <td className={e.within_range ? undefined : "nx-dim"}>
        {exposureText(e, landfall)}
        {e.landfall_at && <div className="nx-dim">Landfall {formatStamp(e.landfall_at)}</div>}
      </td>
      <td>
        <Sev severity={e.severity} />
      </td>
      <td className="nx-mono nx-dim nx-hz-updated">{ago(e.updated_at)}</td>
    </FlashRow>
  );
}

function EventsCard({ events, until, advance }: { events: HazardEvent[]; until: Until; advance: number }) {
  const [tab, setTab] = useState<HazardCategory | typeof ALL>(ALL);
  const rows = events.filter((e) => tab === ALL || e.category === tab);
  const banners = events.filter((e) => armable(e, until(e.landfall_at)) || e.armed?.status === "SCHEDULED");
  return (
    <Card
      icon="globe"
      title="Live hazard events"
      sub={advance ? `Simulated · demo clock +${advance} h` : "Simulated"}
      actions={
        <div className="nx-tabs" role="tablist">
          {[ALL, ...HAZARD_CATEGORIES].map((k) => (
            <button
              key={k}
              type="button"
              role="tab"
              aria-selected={tab === k}
              className={tab === k ? "on" : undefined}
              onClick={() => setTab(k as HazardCategory | typeof ALL)}
            >
              {k === ALL ? "All" : HAZARD_LABEL[k as HazardCategory]}
            </button>
          ))}
        </div>
      }
    >
      {rows.length === 0 ? (
        <Empty>No hazard events. Nothing active of this type.</Empty>
      ) : (
        <table className="nx-table-plain nx-hz-table" aria-label="Live hazard events">
          <thead>
            <tr>
              <th>Type</th>
              <th>Event</th>
              <th>Area</th>
              <th>Mission exposure</th>
              <th>Level</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((e) => (
              <EventRow key={e.incident_id} e={e} until={until} />
            ))}
          </tbody>
        </table>
      )}
      {banners.map((e) => (
        <ArmingBanner key={e.incident_id} e={e} until={until} />
      ))}
    </Card>
  );
}

function ClimateCard({ rows, loading }: { rows: ClimateRisk[]; loading: boolean }) {
  return (
    <Card icon="trending-up" title="Long-term climate exposure" sub="Site risk score · today vs 2050">
      {loading ? (
        <SkeletonRows />
      ) : (
        <table className="nx-table-plain nx-hz-table" aria-label="Long-term climate exposure">
          <thead>
            <tr>
              <th>Mission</th>
              <th>Main hazards</th>
              <th>Today</th>
              <th>2050</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.mission_id}>
                <td>
                  <b>{c.city}</b>
                </td>
                <td>{c.hazards.join(" · ")}</td>
                <td>
                  <span className="nx-row nx-hz-score">
                    <span className="nx-bar" style={{ width: 40 }}>
                      <i style={{ width: `${c.score_today}%` }} className={c.score_today > 70 ? "warn" : undefined} />
                    </span>
                    <span className="nx-mono">{c.score_today}</span>
                  </span>
                </td>
                <td className={`nx-mono${c.score_2050 > 80 ? " nx-hz-high" : ""}`}>{c.score_2050}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="nx-bd nx-dim">
        Illustrative climate model (simulated){rows[0] && ` · ${rows[0].scenario}`}. For site selection, lease
        renewals and continuity planning; shown, not acted on.
      </div>
    </Card>
  );
}

/** Natural Hazards & Climate (HZ-03, HZ-04, HZ-09, HZ-10; D-38). Feeds and scores are simulated (D-19). */
export function HazardsScreen() {
  const hazards = useHazards();
  const climate = useClimate();
  const data = hazards.data;
  const until = useUntil(data?.clock_now, hazards.dataUpdatedAt);
  const events = data?.events ?? [];
  const exposed = exposedMissions(events);
  const byLevel = LEVELS.map((l) => [l, [...exposed.values()].filter((s) => s === l).length] as const).filter(
    ([, n]) => n > 0,
  );
  const top = climate.data?.[0];

  return (
    <div className="nx-pad">
      <TileRow>
        <Kpi
          icon="warning-sign"
          label="Active hazard events"
          value={data ? events.length : "—"}
          detail={data && `${events.filter((e) => e.within_range).length} within 300 km of a mission`}
        />
        <Kpi
          icon="office"
          label="Missions exposed now"
          value={data ? exposed.size : "—"}
          detail={data && (byLevel.map(([l, n]) => `${n} ${LEVEL_WORD[l]}`).join(" · ") || "None exposed")}
          alert={byLevel.some(([l]) => l === "CRITICAL" || l === "HIGH")}
        />
        <Kpi
          icon="trending-up"
          label="Highest 2050 climate risk"
          value={top ? top.city.toUpperCase() : "—"}
          detail={top && `${top.hazards.join(" · ")} · ${top.score_2050} / 100`}
        />
        <Kpi
          icon="feed"
          label="Sources"
          value={data ? data.sources : "—"}
          detail="xWeather · seismic · air quality · climate model (simulated)"
        />
      </TileRow>
      <div className="nx-hz-grid">
        {hazards.isLoading ? (
          <Card icon="globe" title="Live hazard events">
            <SkeletonRows />
          </Card>
        ) : (
          <EventsCard events={events} until={until} advance={data?.demo_advance_h ?? 0} />
        )}
        <ClimateCard rows={climate.data ?? []} loading={climate.isLoading} />
      </div>
    </div>
  );
}
