import { Button, Icon, InputGroup } from "@blueprintjs/core";
import { useEffect, useState } from "react";

import { useOperationsSummary } from "../../api/intel";
import { usePeople, useSites } from "../../api/people";
import { drillAge, initials, locationSourceLabel, personTypeLabel } from "../../ui/format";
import { Card, ConfidenceBar, Kpi } from "../../ui/primitives";
import { TileRow } from "../../ui/TileRow";
import { Empty } from "../../ui/Empty";
import { SkeletonRows } from "../../ui/Skeleton";

const PAGE = 100;
const COLOURS = ["#8ABBFF", "#72CA9B", "#FBB360", "#BDADFF", "#F5498B", "#68C1EE", "#D1980B", "#E76A6E"];

function useDebounced(value: string, ms = 250): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

function ZoneStatus({ inZone, reference }: { inZone: boolean; reference?: string | null }) {
  return inZone ? (
    <span className="nx-sev crit" title={reference ?? undefined}>
      IN ZONE
    </span>
  ) : (
    <span className="nx-sev ok">NORMAL</span>
  );
}

function PeopleTable({ q }: { q: string }) {
  const [limit, setLimit] = useState(PAGE); // reset by key={q} on a new search
  const { data, isPending, isFetching } = usePeople(q, limit);
  if (isPending) return <SkeletonRows rows={8} />;
  if (!data?.items.length) return <Empty>No people match.</Empty>;
  return (
    <>
      <table className="nx-table-plain" aria-label="People">
        <thead>
          <tr>
            <th>Name</th>
            <th>Role</th>
            <th>Mission</th>
            <th>Current location</th>
            <th>Source</th>
            <th>Confidence</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {data.items.map((p, i) => (
            <tr key={p.id}>
              <td>
                <div className="nx-row">
                  <div
                    className="nx-av"
                    style={{ background: `${COLOURS[i % 8]}33`, color: COLOURS[i % 8] }}
                  >
                    {initials(p.full_name)}
                  </div>
                  <b>{p.full_name}</b>
                </div>
              </td>
              <td>
                {p.role_title ?? personTypeLabel(p.person_type)}
                {p.role_title && <span className="nx-dim"> · {personTypeLabel(p.person_type)}</span>}
              </td>
              <td>{p.mission_code ?? "—"}</td>
              <td>{p.place_label ?? "—"}</td>
              <td>{locationSourceLabel(p.location_source)}</td>
              <td>
                <ConfidenceBar value={p.confidence} />
              </td>
              <td>
                <ZoneStatus inZone={p.in_zone} reference={p.incident_reference} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="nx-row nx-pager">
        <span className="nx-dim">
          {data.items.length} of {data.total.toLocaleString("en-GB")}
        </span>
        {data.items.length < data.total && (
          <Button size="small" text="Show more" loading={isFetching} onClick={() => setLimit(limit + PAGE)} />
        )}
      </div>
    </>
  );
}

function SitesTable({ q }: { q: string }) {
  const { data, isPending } = useSites(q);
  if (isPending) return <SkeletonRows rows={8} />;
  if (!data?.items.length) return <Empty>No sites match.</Empty>;
  return (
    <table className="nx-table-plain" aria-label="Sites">
      <thead>
        <tr>
          <th>Site</th>
          <th>Type</th>
          <th>Mission</th>
          <th>Readiness</th>
          <th>Last drill</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {data.items.map((s) => (
          <tr key={s.id}>
            <td>
              <div className="nx-row">
                <Icon icon={s.site_type === "HOTEL" ? "home" : "office"} size={12} />
                <b>{s.name}</b>
              </div>
            </td>
            <td>{s.site_type[0] + s.site_type.slice(1).toLowerCase()}</td>
            <td>
              {s.mission_code} · {s.city}
            </td>
            <td>
              {s.readiness_score === null ? (
                <span className="nx-dim">—</span>
              ) : (
                <span className="nx-confidence">
                  <span className="nx-bar" style={{ width: 80 }}>
                    <i style={{ width: `${s.readiness_score}%` }} />
                  </span>
                  <span className="nx-mono">{s.readiness_score}</span>
                </span>
              )}
            </td>
            <td>{drillAge(s.last_drill_on)}</td>
            <td>
              <ZoneStatus inZone={s.in_zone} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** People & Sites (PPL-01..04). */
export function PeopleScreen() {
  const [tab, setTab] = useState<"people" | "sites">("people");
  const [query, setQuery] = useState("");
  const q = useDebounced(query.trim());
  const summary = useOperationsSummary().data;

  return (
    <div className="nx-pad">
      <TileRow>
        <Kpi
          icon="people"
          label="Personnel"
          value={summary?.personnel ?? "—"}
          detail="Diplomats, local staff, delegates"
        />
        <Kpi
          icon="locate"
          label="Avg. location confidence"
          value={summary?.avg_location_confidence != null ? `${summary.avg_location_confidence}%` : "—"}
          detail={summary && `${summary.personnel_located.toLocaleString("en-GB")} personnel located`}
        />
        <Kpi
          icon="office"
          label="Sites"
          value={summary?.mission_sites ?? "—"}
          detail="Mission property (embassies, consulates, residences, offices)"
        />
        <Kpi
          icon="people"
          label="Registered citizens abroad"
          value={summary?.citizens ?? "—"}
          detail="Consular registration"
        />
      </TileRow>
      <Card
        title={
          <div className="nx-tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={tab === "people"}
              className={tab === "people" ? "on" : undefined}
              onClick={() => setTab("people")}
            >
              People
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "sites"}
              className={tab === "sites" ? "on" : undefined}
              onClick={() => setTab("sites")}
            >
              Sites
            </button>
          </div>
        }
        actions={
          <InputGroup
            leftIcon="search"
            size="small"
            placeholder={tab === "people" ? "Name, role, mission or place…" : "Site, type or mission…"}
            aria-label="Filter"
            value={query}
            onChange={(e) => setQuery(e.currentTarget.value)}
          />
        }
      >
        {tab === "people" ? <PeopleTable key={q} q={q} /> : <SitesTable q={q} />}
      </Card>
    </div>
  );
}
