import { Button, NonIdealState } from "@blueprintjs/core";
import { Link, useParams } from "react-router-dom";

import { acceptedOf, teamLabel, useReviewExport } from "../../api/aar";
import { formatStamp } from "../../app/time";
import { metricTarget, metricValue } from "./format";

/** AAR-07: a print-ready review. The browser saves it as PDF; nothing is stored on the server.
 * Opening it is an audited export. Roles, references and counts; no person's name. */
export function AarPrint() {
  const { id = "" } = useParams();
  const exported = useReviewExport(id);
  const r = exported.data;
  if (exported.isError)
    return (
      <NonIdealState icon="error" title="The review could not be exported" />
    );
  if (!r)
    return <NonIdealState icon="document" title="Preparing the review…" />;
  const [accepted, total] = acceptedOf(r.items);
  const decided = r.items.filter((i) => i.status !== "DRAFT");
  return (
    <div className="nx-brief" data-testid="aar-print">
      <div className="nx-brief-actions">
        <Link to={`/aar?review=${r.id}`}>← After-Action Review</Link>
        <Button
          icon="print"
          intent="primary"
          text="Print / save as PDF"
          onClick={() => window.print()}
        />
      </div>
      <article className="nx-brief-page">
        <header>
          <h1>After-action review {r.reference}</h1>
          <div>
            {r.incident_reference} · {r.incident_title} ·{" "}
            {r.status === "FINAL" ? "final" : "draft"} · produced{" "}
            {formatStamp(new Date().toISOString())} · <b>Simulated data</b>
          </div>
        </header>
        <section>
          <h2>Response metrics</h2>
          <table aria-label="Review metrics">
            <tbody>
              {r.metrics.map((m) => (
                <tr key={m.key}>
                  <td>{m.label}</td>
                  <td>{metricValue(m)}</td>
                  <td>
                    {metricTarget(m)}
                    {m.met === false ? " · missed" : m.met ? " · met" : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        <section>
          <h2>
            Lessons and actions · {accepted} of {total} accepted
          </h2>
          <table aria-label="Review actions">
            <thead>
              <tr>
                <th>Finding</th>
                <th>Action</th>
                <th>Team</th>
                <th>Due</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {!decided.length && (
                <tr>
                  <td colSpan={5}>No lesson decided yet.</td>
                </tr>
              )}
              {decided.map((i) => (
                <tr key={i.id}>
                  <td>{i.finding}</td>
                  <td>{i.action}</td>
                  <td>{teamLabel(i.owner_team)}</td>
                  <td>{i.due_on ?? "—"}</td>
                  <td>
                    {i.status === "REJECTED"
                      ? `Rejected: ${i.reason ?? ""}`
                      : i.status.toLowerCase()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        <section>
          <h2>Timeline</h2>
          <ul>
            {r.timeline.map((t, n) => (
              <li key={`${t.at}-${n}`}>
                {formatStamp(t.at)} · {t.text}
              </li>
            ))}
          </ul>
        </section>
        <footer>
          {r.label}. All data is simulated (D-19). Roles, references and counts;
          no personal data. This export is recorded in the audit log.
        </footer>
      </article>
    </div>
  );
}
