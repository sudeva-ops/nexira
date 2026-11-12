import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { type IncidentStatus, useIncidents } from "../../api/intel";
import { ago } from "../../app/time";
import { FlashRow } from "../../ui/motion";
import { Card, ExerciseTag, Sev } from "../../ui/primitives";
import { SkeletonRows } from "../../ui/Skeleton";
import { IncidentDetail } from "./IncidentDetail";
import { Empty } from "../../ui/Empty";
import { plural } from "../../ui/format";

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
        chip={incidents && { text: plural(incidents.length, "incident") }}
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
          <SkeletonRows />
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
                <FlashRow
                  key={i.id}
                  watch={`${i.severity} ${i.status} ${i.signal_count}`}
                  tone={i.severity === "CRITICAL" ? "danger" : i.severity === "HIGH" ? "warning" : "info"}
                  className={`click${i.id === selectedId ? " sel" : ""}`}
                  onClick={() => setParams({ id: i.id })}
                >
                  <td className="nx-dim nx-mono">{i.reference}</td>
                  <td>
                    <b>{i.title}</b> <ExerciseTag on={i.exercise} />
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
                </FlashRow>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>No incidents.</Empty>
        )}
      </Card>
      {selectedId ? <IncidentDetail key={selectedId} incidentId={selectedId} /> : <div />}
    </div>
  );
}
