import { NonIdealState, Spinner } from "@blueprintjs/core";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { type IncidentStatus, useIncidents } from "../../api/intel";
import { ago } from "../../app/time";
import { Card, Sev } from "../../ui/primitives";
import { IncidentDetail } from "./IncidentDetail";

const TABS: { label: string; status?: IncidentStatus }[] = [
  { label: "All" },
  { label: "Active", status: "ACTIVE" },
  { label: "Monitoring", status: "MONITORING" },
  { label: "Closed", status: "CLOSED" },
];

const STATUS_DOT: Record<IncidentStatus, string> = {
  ACTIVE: "#E76A6E",
  MONITORING: "#EC9A3C",
  CLOSED: "#738091",
};

/** Incidents (INC-06, INC-07): register and detail. */
export function IncidentsScreen() {
  const [tab, setTab] = useState(0);
  const [params, setParams] = useSearchParams();
  const { data: incidents, isPending } = useIncidents(TABS[tab]?.status);
  const selectedId = params.get("id") ?? incidents?.[0]?.id ?? null;

  return (
    <div className="nx-split">
      <Card
        icon="warning-sign"
        title="Incidents"
        sub={incidents && `${incidents.length} incidents`}
        actions={
          <div className="nx-tabs" role="tablist">
            {TABS.map((t, i) => (
              <button
                key={t.label}
                type="button"
                role="tab"
                aria-selected={i === tab}
                className={i === tab ? "on" : undefined}
                onClick={() => setTab(i)}
              >
                {t.label}
              </button>
            ))}
          </div>
        }
      >
        {isPending ? (
          <Spinner />
        ) : incidents?.length ? (
          <table className="nx-table-plain" aria-label="Incident register">
            <thead>
              <tr>
                <th>ID</th>
                <th>Title</th>
                <th>Severity</th>
                <th>Sources</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {incidents.map((i) => (
                <tr
                  key={i.id}
                  className={`click${i.id === selectedId ? " sel" : ""}`}
                  onClick={() => setParams({ id: i.id })}
                >
                  <td className="nx-dim nx-mono">{i.reference}</td>
                  <td>
                    <b>{i.title}</b>
                    <div className="nx-dim">
                      {i.place_label} · {ago(i.opened_at)}
                    </div>
                  </td>
                  <td>
                    <Sev severity={i.severity} />
                  </td>
                  <td>{i.signal_count}</td>
                  <td>
                    <span className="nx-chip">
                      <i style={{ background: STATUS_DOT[i.status] }} />
                      {i.status[0] + i.status.slice(1).toLowerCase()}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <NonIdealState icon="tick-circle" title="No incidents" />
        )}
      </Card>
      {selectedId ? <IncidentDetail key={selectedId} incidentId={selectedId} /> : <div />}
    </div>
  );
}
