import { HTMLSelect, Icon, NonIdealState } from "@blueprintjs/core";
import { useSearchParams } from "react-router-dom";

import {
  type CalendarEvent,
  defaultMission,
  type Driver,
  type MissionRisk,
  type Rising,
  shortDay,
  useMissionRisk,
  usePredictiveOverview,
} from "../../api/predictive";
import { Card } from "../../ui/primitives";
import { SkeletonRows } from "../../ui/Skeleton";
import { Empty } from "../../ui/Empty";

const RISING_ROWS = 8;

function signed(n: number | null): string {
  if (n === null) return "—";
  return n > 0 ? `+${n}` : String(n);
}

/** PRD-07: history in blue, the dashed forecast in violet with its band, Today, the threshold. */
function RiskChart({ m }: { m: MissionRisk }) {
  const w = 720;
  const h = 230;
  const today = m.history.length - 1;
  const n = m.history.length + m.forecast.length;
  const x = (i: number) => 30 + (i * (w - 40)) / Math.max(1, n - 1);
  const y = (v: number) => 10 + ((100 - v) / 100) * (h - 30);
  const pt = (i: number, v: number) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`;
  const last = m.history[today]?.value ?? m.now;
  const history = m.history.map((p, i) => pt(i, p.value)).join(" ");
  const ahead = [pt(today, last), ...m.forecast.map((f, i) => pt(today + 1 + i, f.value))].join(" ");
  const band = [
    pt(today, last),
    ...m.forecast.map((f, i) => pt(today + 1 + i, f.high)),
    ...[...m.forecast].reverse().map((f, i) => pt(n - 1 - i, f.low)),
  ].join(" ");
  const peak = Math.max(m.now, ...m.forecast.map((f) => f.value));
  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      className="nx-prd-chart"
      role="img"
      aria-label={`${m.city} risk index: ${m.now} today, a forecast peak of ${peak} within 14 days, threshold ${m.threshold}`}
    >
      {[0, 25, 50, 75, 100].map((v) => (
        <g key={v}>
          <line x1="30" x2={w - 10} y1={y(v)} y2={y(v)} stroke="#2F343C" />
          <text x="4" y={y(v) + 4} fill="#738091" fontSize="10">
            {v}
          </text>
        </g>
      ))}
      <rect x="30" y={y(100)} width={w - 40} height={y(m.threshold) - y(100)} fill="rgba(205,66,70,.06)" />
      <line
        x1="30"
        x2={w - 10}
        y1={y(m.threshold)}
        y2={y(m.threshold)}
        stroke="#CD4246"
        strokeDasharray="4 3"
        data-testid="prd-threshold"
      />
      <text x={w - 14} y={y(m.threshold) - 4} fill="#FA999C" fontSize="10" textAnchor="end">
        Elevated threshold · {m.threshold}
      </text>
      {m.forecast.length > 0 && <polygon points={band} fill="rgba(157,127,219,.18)" data-testid="prd-band" />}
      <polyline points={history} fill="none" stroke="#4C90F0" strokeWidth="2" data-testid="prd-history" />
      {m.forecast.length > 0 && (
        <polyline
          points={ahead}
          fill="none"
          stroke="#9D7FDB"
          strokeWidth="2"
          strokeDasharray="5 4"
          data-testid="prd-forecast"
        />
      )}
      <line x1={x(today)} x2={x(today)} y1="5" y2={h - 20} stroke="#ABB3BF" strokeDasharray="2 3" />
      <text x={x(today) + 4} y="14" fill="#ABB3BF" fontSize="10">
        Today · {m.now}
      </text>
      <text x="30" y={h - 4} fill="#738091" fontSize="10">
        {m.history.length > 1 ? `${m.history.length - 1} days ago` : "Today"}
      </text>
      <text x={w - 10} y={h - 4} fill="#738091" fontSize="10" textAnchor="end">
        +{m.forecast.length} days
      </text>
    </svg>
  );
}

function Drivers({ drivers }: { drivers: Driver[] }) {
  return (
    <table className="nx-table-plain" aria-label="Key drivers">
      <thead>
        <tr>
          <th>Driver</th>
          <th>Points</th>
          <th>Change · 7 d</th>
        </tr>
      </thead>
      <tbody>
        {drivers.map((d) => (
          <tr key={`${d.key}-${d.label}`}>
            <td>
              <b>{d.label}</b>
            </td>
            <td className="nx-mono">{d.points}</td>
            <td className="nx-mono">{signed(d.change)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function RisingTable({
  rows,
  threshold,
  selected,
  onSelect,
}: {
  rows: Rising[];
  threshold: number;
  selected: string | undefined;
  onSelect: (id: string) => void;
}) {
  return (
    <table className="nx-table-plain" aria-label="Rising risk">
      <thead>
        <tr>
          <th>Mission</th>
          <th>Now</th>
          <th>Peak</th>
          <th>On</th>
          <th>Trend</th>
        </tr>
      </thead>
      <tbody>
        {rows.slice(0, RISING_ROWS).map((r) => (
          <tr
            key={r.mission_id}
            className={`click${r.mission_id === selected ? " sel" : ""}`}
            data-mission={r.mission_code}
            onClick={() => onSelect(r.mission_id)}
          >
            <td>
              <b>{r.city}</b> <span className="nx-dim">{r.mission_code}</span>
            </td>
            <td className="nx-mono">{r.now}</td>
            <td className="nx-mono" style={{ color: r.peak >= threshold ? "#FA999C" : undefined }}>
              {r.peak}
            </td>
            <td className="nx-mono">{shortDay(r.peak_day)}</td>
            <td style={{ color: r.change > 0 ? "#FA999C" : r.change < 0 ? "#72CA9B" : undefined }}>
              {r.change > 0 ? "▲" : r.change < 0 ? "▼" : "■"} {Math.abs(r.change)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Calendar({ events }: { events: CalendarEvent[] }) {
  if (!events.length) return <Empty>No scheduled event in the next 14 days.</Empty>;
  return (
    <ul className="nx-bd nx-prd-events" aria-label="Events calendar">
      {events.map((e) => (
        <li key={e.id}>
          <span className="nx-mono nx-dim">
            {shortDay(e.starts_on)}
            {e.ends_on !== e.starts_on ? `–${shortDay(e.ends_on)}` : ""}
          </span>
          <span>
            <b>{e.title}</b>
            <span className="nx-dim">
              {" "}
              · {e.kind.toLowerCase()}
              {e.place_label ? ` · ${e.place_label}` : ""}
              {e.attendance ? ` · about ${e.attendance.toLocaleString("en-GB")} people` : ""} · weight {e.weight}
            </span>
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Predictive Risk (PRD-07; D-46): advisory, an illustrative model on simulated data. */
export function PredictiveScreen() {
  const overview = usePredictiveOverview();
  const [params, setParams] = useSearchParams();
  const o = overview.data;
  const missionId = params.get("mission") ?? (o ? defaultMission(o.rising) : undefined);
  const mission = useMissionRisk(missionId);
  const m = mission.data;
  const select = (id: string) => setParams({ mission: id });

  if (overview.isError) return <NonIdealState icon="error" title="The forecast could not be loaded" />;
  return (
    <div className="nx-pad">
      <div className="nx-banner nx-mb" role="note">
        <Icon icon="trending-up" />
        <div>
          <b>Model output is advisory.</b> {o?.model ?? "Illustrative model · a projection, not a prediction"}. It
          combines incidents, intelligence signals, health, hazards, weather and the events calendar. Nothing changes
          because of a forecast. Simulated data for demonstration.
        </div>
      </div>
      {!o ? (
        <SkeletonRows rows={8} />
      ) : (
        <div className="nx-prd-grid">
          <div className="nx-col">
            <Card
              icon="timeline-line-chart"
              title={m ? `Risk index · ${m.city}` : "Risk index"}
              sub="30-day history · 14-day forecast with its band"
              actions={
                <HTMLSelect
                  minimal
                  aria-label="Mission"
                  value={missionId ?? ""}
                  onChange={(e) => select(e.currentTarget.value)}
                  options={[...o.rising]
                    .sort((a, b) => a.mission_code.localeCompare(b.mission_code))
                    .map((r) => ({ value: r.mission_id, label: `${r.mission_code} · ${r.city}` }))}
                />
              }
            >
              <div className="nx-bd">
                {mission.isError ? (
                  <div className="nx-dim">This mission's forecast could not be loaded.</div>
                ) : m ? (
                  <RiskChart m={m} />
                ) : (
                  <SkeletonRows rows={5} />
                )}
              </div>
            </Card>
            <Card icon="flash" title="Key drivers" sub={m ? `${m.city} · today` : undefined}>
              {m ? <Drivers drivers={m.drivers} /> : <SkeletonRows rows={3} />}
            </Card>
            <Card icon="calendar" title="Events calendar" sub={m ? `${m.city} · next 14 days` : undefined}>
              {m ? <Calendar events={m.events} /> : <SkeletonRows rows={2} />}
            </Card>
          </div>
          <div className="nx-col">
            <Card icon="warning-sign" title="Rising risk · next 14 days">
              <RisingTable rows={o.rising} threshold={o.threshold} selected={missionId} onSelect={select} />
            </Card>
            <Card icon="lightbulb" title="Recommended actions" sub="Advisory · people decide">
              {o.actions.length ? (
                <ul className="nx-bd nx-prd-actions" aria-label="Recommended actions">
                  {o.actions.map((a) => (
                    <li key={`${a.mission_code}-${a.text}`}>{a.text}</li>
                  ))}
                </ul>
              ) : (
                <Empty>No action recommended: every forecast stays below {o.threshold}.</Empty>
              )}
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
