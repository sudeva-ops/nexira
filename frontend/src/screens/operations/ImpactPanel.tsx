import { Button } from "@blueprintjs/core";
import { Link } from "react-router-dom";

import { useIncident } from "../../api/intel";
import { initials, locationSourceLabel, personnelFirst, personTypeLabel } from "../../ui/format";
import { Card, ConfidenceBar, Sev } from "../../ui/primitives";
import { SkeletonRows } from "../../ui/Skeleton";

const AVATAR: Record<string, string> = {
  DIPLOMAT: "#8ABBFF",
  LOCAL_STAFF: "#8ABBFF",
  DELEGATE: "#BDADFF",
  CITIZEN: "#FBB360",
};

/** OPS-04: who and what is in the impact zone, with location confidence and source. */
export function ImpactPanel({
  incidentId,
  onClose,
  onNearby,
}: {
  incidentId: string;
  onClose: () => void;
  onNearby?: (lon: number, lat: number) => void; // NBY-01: from the incident
}) {
  const { data: incident, isPending } = useIncident(incidentId);
  if (isPending || !incident) {
    return (
      <Card icon="locate" title="Impact analysis" className="nx-side">
        <SkeletonRows rows={3} />
      </Card>
    );
  }
  const s = incident.exposure_summary;
  const people = personnelFirst(incident.exposure.filter((e) => e.subject_type === "PERSON"));
  return (
    <Card
      icon="locate"
      title="Impact analysis"
      className="nx-side nx-impact"
      actions={
        <>
          <span className="nx-dim nx-mono">{incident.reference}</span>
          {onNearby && (
            <Button size="small" icon="locate" text="What's nearby" onClick={() => onNearby(incident.lon, incident.lat)} />
          )}
          <Button size="small" text="Feed" onClick={onClose} />
        </>
      }
    >
      <div className="nx-impact-head">
        <Sev severity={incident.severity} />
        <b>{incident.title}</b>
        <Link to={`/incidents?id=${incident.id}`}>Open incident →</Link>
      </div>
      <div className="nx-istat" aria-label="Exposure summary">
        <div>
          <b>{s.mission_sites}</b>
          <span>Sites</span>
        </div>
        <div>
          <b style={{ color: "#8ABBFF" }}>{s.staff}</b>
          <span>Staff</span>
        </div>
        <div>
          <b style={{ color: "#BDADFF" }}>{s.delegates}</b>
          <span>Delegates</span>
        </div>
        <div>
          <b style={{ color: "#FBB360" }}>{s.citizens}</b>
          <span>Citizens</span>
        </div>
      </div>
      <div className="nx-lbl nx-row">
        <span>
          People in {Math.round(incident.impact_radius_m / 1000)} km zone · {s.people}
        </span>
        <span className="nx-grow" />
        <span>Confidence</span>
      </div>
      <div className="nx-plist">
        {people.map((p) => (
          <div key={p.subject_id} className="nx-pp">
            <div
              className="nx-av"
              style={{
                background: `${AVATAR[p.kind] ?? "#ABB3BF"}33`,
                color: AVATAR[p.kind] ?? "#ABB3BF",
              }}
            >
              {initials(p.name)}
            </div>
            <div className="nx-grow">
              <div className="n">{p.name}</div>
              <div className="r">
                {personTypeLabel(p.kind)} · {p.place_label ?? "—"} ·{" "}
                {((p.distance_m ?? 0) / 1000).toFixed(1)} km
              </div>
            </div>
            <div className="nx-right">
              <ConfidenceBar value={p.confidence} width={40} />
              <div className="r">{locationSourceLabel(p.location_source)}</div>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
