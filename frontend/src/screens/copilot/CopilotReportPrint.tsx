import { Button, NonIdealState } from "@blueprintjs/core";
import { Link, useParams } from "react-router-dom";

import { useReportExport } from "../../api/copilot";
import { formatStamp } from "../../app/time";

/** COP-04: the print-ready situation report. The browser saves it as PDF; nothing is stored or
 * sent. Opening it is an audited export (COPILOT.REPORT_EXPORT). */
export function CopilotReportPrint() {
  const { id = "" } = useParams();
  const exported = useReportExport(id);
  const r = exported.data;
  if (exported.isError) return <NonIdealState icon="error" title="The report could not be exported" />;
  if (!r) return <NonIdealState icon="document" title="Preparing the report…" />;
  return (
    <div className="nx-brief" data-testid="copilot-print">
      <div className="nx-brief-actions">
        <Link to="/copilot">← AI Risk Copilot</Link>
        <Button icon="print" intent="primary" text="Print / save as PDF" onClick={() => window.print()} />
      </div>
      <article className="nx-brief-page">
        <header>
          <h1>{r.title}</h1>
          <div>
            As of {formatStamp(r.as_of)} · draft · <b>{r.label}</b>
          </div>
        </header>
        {r.sections.map((s) => (
          <section key={s.heading}>
            <h2>{s.heading}</h2>
            {s.note && <p className="nx-dim">{s.note}</p>}
            <ul>
              {s.sentences.map((x, i) => (
                <li key={i}>
                  {x.text} <span className="nx-dim">[{x.sources.map((src) => src.reference).join(", ")}]</span>
                </li>
              ))}
            </ul>
          </section>
        ))}
        <section>
          <h2>Sources</h2>
          <p>{r.sources.map((s) => s.reference).join(" · ")}</p>
        </section>
      </article>
    </div>
  );
}
