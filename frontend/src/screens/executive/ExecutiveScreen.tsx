import { Button, NonIdealState } from "@blueprintjs/core";
import { useNavigate } from "react-router-dom";

import {
  type Attention,
  duration,
  type Overview,
  POSTURE_COLOUR,
  readinessDetail,
  RISK_SEV,
  useOverview,
} from "../../api/executive";
import { formatStamp } from "../../app/time";
import { Card, Kpi } from "../../ui/primitives";
import { SkeletonRows } from "../../ui/Skeleton";

const REGION_COLOUR = (exposure: number) =>
  exposure >= 60 ? "#E76A6E" : exposure >= 35 ? "#EC9A3C" : "#4C90F0";

/** The headline figures (EXE-01), shared with the briefing. */
export function Figures({ o }: { o: Overview }) {
  const p = o.posture;
  return (
    <div className="nx-g5 nx-mb">
      <Kpi
        icon="shield"
        label="Global posture"
        value={
          <span style={{ color: POSTURE_COLOUR[p.level] }}>{p.level}</span>
        }
        detail={`${p.critical_missions} critical · ${p.elevated_missions} elevated missions`}
        alert={p.level === "SEVERE"}
      />
      <Kpi
        icon="warning-sign"
        label="Active incidents"
        value={o.active_incidents}
        detail={
          o.latest_incident
            ? `Latest: ${o.latest_incident.reference}`
            : "None active"
        }
      />
      <Kpi
        icon="time"
        label="Detection → notification"
        value={duration(o.detection.current_s ?? o.detection.median_s)}
        detail={
          o.detection.current_reference && o.detection.current_s !== null
            ? `${o.detection.current_reference} · median ${duration(o.detection.median_s)} (${o.detection.incidents})`
            : o.detection.incidents
              ? `Median of ${o.detection.incidents} incident${o.detection.incidents === 1 ? "" : "s"} · 30 days`
              : "No notification in 30 days"
        }
      />
      <Kpi
        icon="people"
        label="Personnel accounted"
        value={o.accounted.pct === null ? "—" : `${o.accounted.pct}%`}
        detail={
          o.accounted.pct === null
            ? "No active check-in"
            : `${o.accounted.answered} of ${o.accounted.asked} · ${o.accounted.incident_references.join(", ")}`
        }
      />
      <Kpi
        icon="tick-circle"
        label="Mission readiness"
        value={o.readiness.mean === null ? "—" : `${o.readiness.mean}/100`}
        detail={readinessDetail(o.readiness)}
      />
    </div>
  );
}

/** EXE-02: incidents as an area over a faint bar per day of raw signals. */


function Trend({ trend }: { trend: Overview["trend"] }) {
  const w = 300;
  const h = 80;
  const maxSignals = Math.max(1, ...trend.map((d) => d.signals));
  const maxIncidents = Math.max(1, ...trend.map((d) => d.incidents));
  const step = trend.length > 1 ? w / (trend.length - 1) : w;
  const bar = w / Math.max(1, trend.length);
  const points = trend.map(
    (d, i) =>
      `${(i * step).toFixed(1)},${(h - (h - 6) * (d.incidents / maxIncidents)).toFixed(1)}`,
  );
  const signals = trend.reduce((n, d) => n + d.signals, 0);
  const incidents = trend.reduce((n, d) => n + d.incidents, 0);
  return (
    <div className="nx-exe-trend">
      <svg
        viewBox={`0 0 ${w} ${h}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`Last 30 days: ${incidents} incidents from ${signals} signals`}
      >
        {trend.map((d, i) => (
          <rect
            key={d.day}
            x={i * bar + bar * 0.2}
            width={bar * 0.6}
            y={h - (h * 0.9 * d.signals) / maxSignals}
            height={(h * 0.9 * d.signals) / maxSignals}
            fill="#404854"
          />
        ))}
        <polygon
          points={`0,${h} ${points.join(" ")} ${w},${h}`}
          fill="rgba(76,144,240,0.25)"
        />
        <polyline
          points={points.join(" ")}
          fill="none"
          stroke="#4C90F0"
          strokeWidth="1.5"
        />
      </svg>
      <div className="nx-row nx-dim nx-exe-axis">
        <span>30 days ago</span>
        <span className="nx-grow" />
        <span>
          {incidents} incidents · {signals} signals (simulated feeds)
        </span>
        <span className="nx-grow" />
        <span>Today</span>
      </div>
    </div>
  );
}

function Regions({ regions }: { regions: Overview["regions"] }) {
  return (
    <div className="nx-bd nx-exe-regions" aria-label="Risk exposure by region">
      {regions.map((r) => (
        <div
          key={r.region}
          title="The mean of its missions' risk points: LOW 20, MODERATE 50, HIGH 75, CRITICAL 95"
        >
          <div className="nx-row">
            <b>{r.region}</b>
            <span className="nx-grow" />
            <span
              className="nx-mono"
              style={{ color: REGION_COLOUR(r.exposure) }}
            >
              {r.exposure}
            </span>
          </div>
          <span className="nx-bar">
            <i
              style={{
                width: `${r.exposure}%`,
                background: REGION_COLOUR(r.exposure),
              }}
            />
          </span>
        </div>
      ))}
    </div>
  );
}

/** EXE-02: the missions and why, from the other modules (shared with the briefing). */
export function AttentionTable({ rows }: { rows: Attention[] }) {
  if (!rows.length)
    return <div className="nx-bd nx-dim">No mission requires attention.</div>;
  return (
    <table
      className="nx-table-plain nx-exe-table"
      aria-label="Missions requiring attention"
    >
      <thead>
        <tr>
          <th>Mission</th>
          <th>Risk</th>
          <th>Drivers</th>
          <th>Personnel</th>
          <th>Readiness</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((a) => (
          <tr key={a.mission_id} data-mission={a.mission_code}>
            <td>
              <b>{a.city}</b>
            </td>
            <td>
              <span className={`nx-sev ${RISK_SEV[a.risk] ?? "low"}`}>
                {a.risk}
              </span>
            </td>
            <td>
              {a.drivers.length ? (
                a.drivers.map((d) => (
                  <div key={`${d.kind}-${d.reference ?? d.label}`}>
                    {d.reference && d.kind === "INCIDENT"
                      ? `${d.reference} · `
                      : ""}
                    {d.label}
                  </div>
                ))
              ) : (
                <span className="nx-dim">Elevated mission risk</span>
              )}
            </td>
            <td className="nx-mono">{a.personnel}</td>
            <td className="nx-mono">{a.readiness ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** EXE-02: the most severe ACTIVE incident's key events, else the last 7 days. */
export function Timeline({ t }: { t: Overview["timeline"] }) {
  if (t.incident) {
    return (
      <ul className="nx-bd nx-exe-timeline" aria-label="Response timeline">
        {t.events.map((e, i) => (
          <li key={`${e.occurred_at}-${i}`}>
            <span className="nx-mono nx-dim">{formatStamp(e.occurred_at)}</span>
            <span>{e.summary}</span>
          </li>
        ))}
      </ul>
    );
  }
  if (!t.recent.length)
    return (
      <div className="nx-bd nx-dim">
        No incident opened or closed in the last 7 days.
      </div>
    );
  return (
    <ul className="nx-bd nx-exe-timeline" aria-label="Recent activity">
      {t.recent.map((r) => (
        <li key={`${r.reference}-${r.change}`}>
          <span className="nx-mono nx-dim">{formatStamp(r.at)}</span>
          <span>
            <b>{r.reference}</b> {r.change === "OPENED" ? "opened" : "closed"} ·{" "}
            {r.title}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Executive Overview (EXE-01..05; D-45): a leadership view built from the other modules. */
export function ExecutiveScreen() {
  const overview = useOverview();
  const navigate = useNavigate();
  const o = overview.data;
  if (overview.isError) {
    return (
      <NonIdealState icon="error" title="The overview could not be loaded" />
    );
  }
  return (
    <div className="nx-pad">
      <div className="nx-row nx-mb">
        <span className="nx-dim">
          Worked out from live data
          {o ? ` · ${formatStamp(o.generated_at)}` : ""} · simulated (D-19)
        </span>
        <span className="nx-grow" />
        <Button
          icon="document-share"
          text="Export briefing"
          onClick={() => navigate("/executive/briefing")}
        />
      </div>
      {!o ? (
        <SkeletonRows rows={8} />
      ) : (
        <>
          <Figures o={o} />
          <div className="nx-ev-grid nx-exe-grid nx-mb">
            <Card
              icon="timeline-area-chart"
              title="Alerts · last 30 days"
              sub="Fused incidents over raw signals"
            >
              <div className="nx-bd">
                <Trend trend={o.trend} />
              </div>
            </Card>
            <Card icon="globe" title="Risk exposure by region">
              <Regions regions={o.regions} />
            </Card>
          </div>
          <div className="nx-ev-grid nx-exe-grid">
            <Card icon="office" title="Missions requiring attention">
              <AttentionTable rows={o.attention} />
            </Card>
            <Card
              icon="time"
              title={
                o.timeline.incident
                  ? `${o.timeline.incident.reference} · response timeline`
                  : "Recent activity"
              }
            >
              <Timeline t={o.timeline} />
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
