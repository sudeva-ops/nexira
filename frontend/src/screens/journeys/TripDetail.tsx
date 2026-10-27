import { Button, Checkbox, InputGroup } from "@blueprintjs/core";
import { useState } from "react";

import { ApiError } from "../../api/client";
import {
  CHECK_ITEMS,
  type TripDetail as Detail,
  useCheckTrip,
  useRejectTrip,
  useTripAction,
  useTripPermissions,
} from "../../api/trips";
import { formatStamp } from "../../app/time";
import { Card, Sev } from "../../ui/primitives";

const STATUS_LABEL: Record<string, string> = {
  DRAFT: "Draft",
  PENDING: "Awaiting approval",
  APPROVED: "Approved",
  REJECTED: "Rejected",
  CANCELLED: "Cancelled",
};
const KIND_LABEL: Record<string, string> = {
  FLIGHT: "Flight",
  STAY: "Stay",
  MEETING: "Meeting",
  GROUND: "Ground transport",
};
const PARTS = [
  ["security", "Security"],
  ["unrest", "Civil unrest"],
  ["health", "Health"],
  ["transport", "Transport"],
] as const;

function scoreColour(v: number): string {
  return v >= 70 ? "#E76A6E" : v >= 45 ? "#EC9A3C" : "#4C90F0";
}

/** JR-02, JR-05, JR-04: itinerary, checklist and the decisions this user may take. */
export function TripDetail({ trip, onEdit }: { trip: Detail; onEdit: (trip: Detail) => void }) {
  const allowed = useTripPermissions(trip.id).data;
  const action = useTripAction();
  const reject = useRejectTrip();
  const check = useCheckTrip();
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const run = (verb: "submit" | "approve" | "cancel") => action.mutate({ id: trip.id, action: verb });
  const error = action.error ?? reject.error ?? check.error;
  const risky = trip.risk_level === "HIGH" || trip.risk_level === "CRITICAL" || trip.live_risk === "HIGH" || trip.live_risk === "CRITICAL";
  const openItems = CHECK_ITEMS.filter(([item]) => !trip.checklist[item]).length;

  return (
    <Card
      icon="route"
      title={`${trip.reference} · ${STATUS_LABEL[trip.approval_status] ?? trip.approval_status}`}
      sub={trip.purpose ?? undefined}
    >
      <div className="nx-bd">
        <div className="nx-dim">
          {trip.origin} → {trip.destination} ({trip.destination_country ?? "—"}) ·{" "}
          {trip.requested_by_name ? `requested by ${trip.requested_by_name}` : "seeded trip"}
          {trip.approved_at &&
            ` · approved ${trip.approved_by_name ? `by ${trip.approved_by_name}` : "on submission (LOW)"} at ${trip.approved_risk_level} · ${formatStamp(trip.approved_at)}`}
        </div>
        {trip.impacted_by.length > 0 && (
          <div className="nx-impacted">Impacted by {trip.impacted_by.join(", ")}</div>
        )}
        {trip.risk_changed && (
          <div className="nx-pending">
            Risk now {trip.live_risk} (approved at {trip.approved_risk_level}): flagged, not revoked (D-32)
          </div>
        )}
        {trip.rejection_reason && trip.approval_status === "DRAFT" && (
          <div className="nx-pending">Returned: {trip.rejection_reason}</div>
        )}

        <div className="nx-trip-cols">
          <div>
            <div className="nx-lbl">Itinerary</div>
            {trip.segments.length === 0 ? (
              <div className="nx-dim">No itinerary yet</div>
            ) : (
              <div className="nx-tl" aria-label="Itinerary">
                {trip.segments.map((s) => (
                  <div key={s.seq}>
                    <b>
                      {KIND_LABEL[s.kind] ?? s.kind} · {s.title}
                    </b>
                    <br />
                    <span>
                      {s.place_label ? `${s.place_label} · ` : ""}
                      {formatStamp(s.starts_at)}
                    </span>
                  </div>
                ))}
              </div>
            )}
            <div className="nx-lbl">Travellers</div>
            <ul className="nx-travellers" aria-label="Travellers">
              {trip.travellers.map((p) => (
                <li key={p.id}>
                  {p.full_name} <span className="nx-dim">· {p.person_type.toLowerCase().replace("_", " ")}</span>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <div className="nx-lbl">Pre-travel checklist</div>
            <div role="group" aria-label="Pre-travel checklist">
              {CHECK_ITEMS.map(([item, label]) => (
                <Checkbox
                  key={item}
                  label={label}
                  checked={trip.checklist[item]}
                  disabled={!allowed?.check_trip || check.isPending}
                  onChange={(e) => check.mutate({ id: trip.id, item, done: e.currentTarget.checked })}
                />
              ))}
              <Checkbox label="Security approval" checked={trip.checklist.security_approval} disabled />
            </div>
            {risky && openItems > 0 && trip.approval_status === "PENDING" && (
              <div className="nx-dim">HIGH and CRITICAL trips need all four ticked before approval (JR-05)</div>
            )}
          </div>
        </div>

        {allowed && (
          <div className="nx-row nx-detail-actions">
            {allowed.edit_trip && <Button text="Edit" onClick={() => onEdit(trip)} />}
            {allowed.submit_trip && (
              <Button intent="primary" text="Submit for approval" loading={action.isPending} onClick={() => run("submit")} />
            )}
            {allowed.approve_trip && !rejecting && (
              <Button intent="primary" icon="tick" text="Approve trip" loading={action.isPending} onClick={() => run("approve")} />
            )}
            {allowed.reject_trip && !rejecting && <Button text="Reject" onClick={() => setRejecting(true)} />}
            {rejecting && (
              <>
                <InputGroup
                  aria-label="Reason for rejecting"
                  placeholder="Reason (sent back to the requester)"
                  value={reason}
                  maxLength={500}
                  onChange={(e) => setReason(e.currentTarget.value)}
                />
                <Button
                  intent="danger"
                  text="Send back"
                  disabled={!reason.trim()}
                  loading={reject.isPending}
                  onClick={() =>
                    reject.mutate({ id: trip.id, reason }, { onSuccess: () => (setRejecting(false), setReason("")) })
                  }
                />
                <Button minimal text="Keep" onClick={() => setRejecting(false)} />
              </>
            )}
            <span className="nx-grow" />
            {allowed.cancel_trip && <Button minimal intent="danger" text="Cancel trip" onClick={() => run("cancel")} />}
          </div>
        )}
        {error && <div className="nx-error">{error instanceof ApiError ? error.message : "Not done"}</div>}
      </div>
    </Card>
  );
}

/** JR-03: the destination's level and four-part breakdown (simulated, D-19). */
export function RiskCard({ trip }: { trip: Detail }) {
  const risk = trip.country_risk;
  if (!risk) return null;
  return (
    <Card
      icon="shield"
      title={`Destination risk · ${risk.country_code}`}
      sub={risk.rated ? (risk.source ?? "Simulated") : "Not rated · counted as MODERATE (simulated)"}
      actions={<Sev severity={risk.level} />}
    >
      <div className="nx-bd nx-risk-parts" aria-label="Destination risk">
        {PARTS.map(([key, label]) => {
          const value = risk[key];
          return (
            <div key={key}>
              <div className="nx-row">
                <b>{label}</b>
                <span className="nx-grow" />
                <span className="nx-mono" style={{ color: value === null ? undefined : scoreColour(value) }}>
                  {value ?? "—"}
                </span>
              </div>
              <div className="nx-bar nx-risk-bar">
                <i style={{ width: `${value ?? 0}%`, background: value === null ? undefined : scoreColour(value) }} />
              </div>
            </div>
          );
        })}
        <div className="nx-dim">
          Base {risk.base_level}
          {risk.incident_level
            ? ` · raised to ${risk.level} by ${risk.incidents.join(", ")} (active incidents at a mission in ${risk.country_code})`
            : " · no active incident in the country"}
        </div>
      </div>
    </Card>
  );
}
