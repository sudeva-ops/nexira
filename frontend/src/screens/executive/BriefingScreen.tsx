import { Button, NonIdealState } from "@blueprintjs/core";
import { Link } from "react-router-dom";

import { duration, useBriefing } from "../../api/executive";
import { formatStamp } from "../../app/time";

/** EXE-03: a one-page, print-ready board briefing. The browser saves it as PDF; nothing is
 * stored on the server. Opening it is an audited export. No person's name (EXE-04). */
export function BriefingScreen() {
  const briefing = useBriefing();
  const o = briefing.data;
  if (briefing.isError)
    return (
      <NonIdealState icon="error" title="The briefing could not be produced" />
    );
  if (!o)
    return <NonIdealState icon="document" title="Preparing the briefing…" />;
  const p = o.posture;
  const figures: [string, string, string][] = [
    [
      "Global posture",
      p.level,
      `${p.critical_missions} critical · ${p.elevated_missions} elevated missions`,
    ],
    [
      "Active incidents",
      String(o.active_incidents),
      o.latest_incident
        ? `Latest: ${o.latest_incident.reference}`
        : "None active",
    ],
    [
      "Detection → notification",
      duration(o.detection.current_s ?? o.detection.median_s),
      o.detection.current_reference ??
        `Median of ${o.detection.incidents} · 30 days`,
    ],
    [
      "Personnel accounted",
      o.accounted.pct === null ? "—" : `${o.accounted.pct}%`,
      o.accounted.pct === null
        ? "No active check-in"
        : `${o.accounted.answered} of ${o.accounted.asked}`,
    ],
    [
      "Mission readiness",
      o.readiness.mean === null ? "—" : `${o.readiness.mean}/100`,
      "Mean embassy score",
    ],
  ];
  return (
    <div className="nx-brief" data-testid="briefing">
      <div className="nx-brief-actions">
        <Link to="/executive">← Executive Overview</Link>
        <Button
          icon="print"
          intent="primary"
          text="Print / save as PDF"
          onClick={() => window.print()}
        />
      </div>
      <article className="nx-brief-page">
        <header>
          <h1>Leadership briefing</h1>
          <div>
            NEXIRA · produced {formatStamp(o.generated_at)} ·{" "}
            <b>Simulated data</b>
          </div>
        </header>
        <section className="nx-brief-figures" aria-label="Headline figures">
          {figures.map(([label, value, detail]) => (
            <div key={label}>
              <div className="nx-brief-label">{label}</div>
              <div className="nx-brief-value">{value}</div>
              <div className="nx-brief-detail">{detail}</div>
            </div>
          ))}
        </section>
        <section>
          <h2>Risk exposure by region</h2>
          <p>
            {o.regions.map((r) => `${r.region} ${r.exposure}`).join(" · ")}
            <span className="nx-brief-detail">
              {" "}
              (mean of mission risk points: LOW 20 … CRITICAL 95)
            </span>
          </p>
        </section>
        <section>
          <h2>Missions requiring attention</h2>
          <table aria-label="Briefing missions">
            <thead>
              <tr>
                <th>Mission</th>
                <th>Risk</th>
                <th>Drivers</th>
              </tr>
            </thead>
            <tbody>
              {o.attention.slice(0, 5).map((a) => (
                <tr key={a.mission_id}>
                  <td>{a.city}</td>
                  <td>{a.risk}</td>
                  <td>
                    {a.drivers
                      .map((d) =>
                        d.kind === "INCIDENT" && d.reference
                          ? `${d.reference} · ${d.label}`
                          : d.label,
                      )
                      .join("; ") || "Elevated mission risk"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        {o.timeline.incident && (
          <section>
            <h2>{o.timeline.incident.reference} · response timeline</h2>
            <ul>
              {o.timeline.events.slice(-6).map((e, i) => (
                <li key={`${e.occurred_at}-${i}`}>
                  {formatStamp(e.occurred_at)} · {e.summary}
                </li>
              ))}
            </ul>
          </section>
        )}
        <footer>
          All data is simulated (D-19). Aggregates only; no personal data. This
          export is recorded in the audit log.
        </footer>
      </article>
    </div>
  );
}
