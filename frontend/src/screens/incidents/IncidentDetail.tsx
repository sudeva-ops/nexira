import { Button, Callout, HTMLSelect, Icon, NonIdealState, TextArea } from "@blueprintjs/core";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useReviews, useStartReview } from "../../api/aar";
import { ApiError } from "../../api/client";
import {
  type IncidentDetail as Detail,
  type IncidentStatus,
  useAddNote,
  useChangeStatus,
  useIncident,
} from "../../api/intel";
import { useMe } from "../../api/me";
import { type Mission, useMissions } from "../../api/people";
import { canAddIncidentNote, canChangeIncidentStatus } from "../../api/permissions";
import { formatStamp } from "../../app/time";
import { SEVERITY_COLOUR } from "../../map/geo";
import { MiniMap } from "../../map/MiniMap";
import { categoryLabel } from "../../ui/format";
import { Card, ExerciseTag, Sev, SourceChip } from "../../ui/primitives";
import { SkeletonRows } from "../../ui/Skeleton";

const NO_MISSIONS: Mission[] = [];
const STATUSES: IncidentStatus[] = ["ACTIVE", "MONITORING", "CLOSED"];

const TIMELINE_COLOUR: Record<string, string> = {
  SIGNAL: "#E76A6E",
  FUSED: "#4C90F0",
  EXPOSURE: "#4C90F0",
  ESCALATED: "#CD4246",
  STATUS: "#32A467",
  NOTE: "#9D7FDB",
  FLEET: "#EC9A3C", // a vehicle crossing the impact zone (D-41, plan-pilot-flt G-10)
};

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong";
}

function StatusControl({ incident }: { incident: Detail }) {
  const [status, setStatus] = useState<IncidentStatus>(incident.status);
  const change = useChangeStatus(incident.id);
  return (
    <div className="nx-row">
      <HTMLSelect
        aria-label="Incident status"
        value={status}
        onChange={(e) => setStatus(e.currentTarget.value as IncidentStatus)}
        options={STATUSES}
      />
      <Button
        text="Set status"
        intent="primary"
        size="small"
        disabled={status === incident.status}
        loading={change.isPending}
        onClick={() => change.mutate(status)}
      />
      {change.isError && <span className="nx-error">{errorText(change.error)}</span>}
    </div>
  );
}

/** AAR-08: once an incident is at MONITORING or CLOSED, its after-action review. */
function ReviewLink({ incident }: { incident: Detail }) {
  const reviews = useReviews().data;
  const start = useStartReview();
  const navigate = useNavigate();
  if (incident.status === "ACTIVE" || !reviews) return null;
  const existing = reviews.reviews.find((r) => r.incident_reference === incident.reference);
  if (existing)
    return (
      <Button
        size="small"
        icon="endorsed"
        text="Open AAR"
        title={existing.reference}
        onClick={() => void navigate(`/aar?review=${existing.id}`)}
      />
    );
  if (!reviews.ready.find((r) => r.incident_id === incident.id)?.can_start) return null;
  return (
    <span className="nx-row">
      <Button
        size="small"
        icon="endorsed"
        intent="primary"
        text="Start after-action review"
        loading={start.isPending}
        onClick={() =>
          start.mutate(incident.id, {
            onSuccess: (created) => void navigate(`/aar?review=${created.id}`),
          })
        }
      />
      {start.isError && <span className="nx-error">{errorText(start.error)}</span>}
    </span>
  );
}

function NoteForm({ incidentId }: { incidentId: string }) {
  const [text, setText] = useState("");
  const add = useAddNote(incidentId);
  return (
    <form
      className="nx-note-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (text.trim()) add.mutate(text.trim(), { onSuccess: () => setText("") });
      }}
    >
      <TextArea
        aria-label="Note"
        placeholder="Add a note to the timeline…"
        value={text}
        onChange={(e) => setText(e.currentTarget.value)}
        fill
        maxLength={4000}
      />
      <div className="nx-row">
        <Button type="submit" text="Add note" size="small" disabled={!text.trim()} loading={add.isPending} />
        {add.isError && <span className="nx-error">{errorText(add.error)}</span>}
      </div>
    </form>
  );
}

/** TWN-10: a SITE entry (a sensor fault or recovery) opens the camera watching that place. */
function CameraLink({ data }: { data: Record<string, unknown> }) {
  const { site_id: site, sensor } = data;
  if (typeof site !== "string" || typeof sensor !== "string") return null;
  return (
    <>
      {" · "}
      <Link to={`/twin?${new URLSearchParams({ site, camera: sensor }).toString()}`}>View camera</Link>
    </>
  );
}

export function IncidentDetail({ incidentId }: { incidentId: string }) {
  const { data: incident, isPending, error } = useIncident(incidentId);
  const me = useMe().data;
  const missions = useMissions().data ?? NO_MISSIONS;
  const navigate = useNavigate();
  if (isPending) return <SkeletonRows rows={8} />;
  if (error || !incident) return <NonIdealState icon="search" title="Incident not found" />;

  const s = incident.exposure_summary;
  const mayChangeStatus = canChangeIncidentStatus(me, incident.mission_id);
  const mayAddNote = canAddIncidentNote(me, incident.mission_id);
  return (
    <div className="nx-col">
      <Card
        title={
          <span className="nx-row">
            <Sev severity={incident.severity} />
            {incident.title}
          </span>
        }
        actions={
          <span className="nx-row">
            {/* RPL-06 (D-51): play the incident back from its record. */}
            <Button
              size="small"
              icon="play"
              text="Replay"
              onClick={() => void navigate(`/incidents/replay?id=${incident.id}`)}
            />
            {incident.status === "ACTIVE" ? (
              <Button
                size="small"
                icon="globe"
                text="Open in map"
                onClick={() => void navigate(`/operations?incident=${incident.id}`)}
              />
            ) : (
              <ReviewLink incident={incident} />
            )}
          </span>
        }
      >
        <div className="nx-bd">
          <div className="nx-row nx-dim nx-mono nx-meta">
            <span>{incident.reference}</span>
            <ExerciseTag on={incident.exercise} />
            <span>{incident.place_label}</span>
            <span>Mission: {incident.mission_code ?? "not yet assigned"}</span>
            <span>Status: {incident.status}</span>
            <span>Opened {formatStamp(incident.opened_at)}</span>
          </div>
          {incident.severity !== incident.signal_severity && (
            <Callout intent="danger" compact icon="warning-sign" className="nx-mb">
              Severity raised from {incident.signal_severity} to {incident.severity}: a protected
              mission site is in the impact zone (D-11).
            </Callout>
          )}
          <div className="nx-lbl">Source normalisation</div>
          <table className="nx-table-plain" aria-label="Source normalisation">
            <thead>
              <tr>
                <th>Source</th>
                <th>Original signal</th>
                <th>Orig. severity</th>
                <th>Normalised (signal)</th>
              </tr>
            </thead>
            <tbody>
              {incident.signals.map((sig) => (
                <tr key={sig.id}>
                  <td>
                    <SourceChip source={{ name: sig.source_name, simulated: sig.source_simulated }} />
                  </td>
                  <td>{sig.title}</td>
                  <td>{sig.provider_severity}</td>
                  <td>{sig.norm_severity && <Sev severity={sig.norm_severity} />}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="nx-row nx-chips">
            <span className="nx-chip">
              <Icon icon="git-merge" size={10} />
              {incident.signal_count} signals → 1 incident
            </span>
            <span className="nx-chip">Category · {categoryLabel(incident.category)}</span>
            {incident.confidence !== null && (
              <span className="nx-chip">Confidence {incident.confidence}%</span>
            )}
          </div>
        </div>
      </Card>
      <Card icon="locate" title="Exposure" sub={`within ${incident.impact_radius_m / 1000} km`}>
        <MiniMap incident={incident} missions={missions} />
        <div className="nx-istat">
          <div>
            <b>{s.people}</b>
            <span>People</span>
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
          <div>
            <b>{s.mission_sites}</b>
            <span>Sites</span>
          </div>
          <div>
            <b>{s.trips}</b>
            <span>Trips</span>
          </div>
        </div>
      </Card>
      <Card icon="time" title="Timeline">
        <div className="nx-bd">
          <div className="nx-tl" aria-label="Timeline">
            {incident.timeline.map((e) => (
              <div key={e.id} style={{ ["--c" as string]: TIMELINE_COLOUR[e.event_type] ?? SEVERITY_COLOUR.LOW }}>
                <span>{formatStamp(e.occurred_at)}</span>
                <b>{e.event_type}</b> · {e.summary}
                {e.actor_type === "USER" && <span className="nx-dim"> · by a user</span>}
                <CameraLink data={e.data} />
              </div>
            ))}
          </div>
          {(mayChangeStatus || mayAddNote) && (
            <div className="nx-actions">
              {mayChangeStatus && <StatusControl key={incident.status} incident={incident} />}
              {mayAddNote && <NoteForm incidentId={incident.id} />}
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
