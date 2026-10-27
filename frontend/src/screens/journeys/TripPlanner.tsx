import { Button, Classes, HTMLSelect, Icon, InputGroup } from "@blueprintjs/core";
import { useState } from "react";

import { ApiError } from "../../api/client";
import { usePeople } from "../../api/people";
import { type SegmentKind, type TripDetail, type TripPlan, useSaveTrip } from "../../api/trips";
import { HOME_TZ_LABEL, homeInputToIso, isoToHomeInput } from "../../app/time";
import { Card } from "../../ui/primitives";

const KINDS: [SegmentKind, string][] = [
  ["FLIGHT", "Flight"],
  ["STAY", "Stay"],
  ["MEETING", "Meeting"],
  ["GROUND", "Ground transport"],
];

interface SegmentRow {
  kind: SegmentKind;
  title: string;
  place_label: string;
  starts_at: string; // datetime-local, home zone (plan G-8)
  ends_at: string;
}

interface Draft {
  purpose: string;
  origin: string;
  destination: string;
  destination_country: string;
  starts_on: string;
  ends_on: string;
  travellers: { id: string; full_name: string }[];
  segments: SegmentRow[];
}

function fromTrip(trip: TripDetail | null): Draft {
  if (!trip) {
    return {
      purpose: "",
      origin: "HQ",
      destination: "",
      destination_country: "",
      starts_on: "",
      ends_on: "",
      travellers: [],
      segments: [],
    };
  }
  return {
    purpose: trip.purpose ?? "",
    origin: trip.origin,
    destination: trip.destination,
    destination_country: trip.destination_country ?? "",
    starts_on: trip.starts_on,
    ends_on: trip.ends_on,
    travellers: trip.travellers.map((p) => ({ id: p.id, full_name: p.full_name })),
    segments: trip.segments.map((s) => ({
      kind: s.kind,
      title: s.title,
      place_label: s.place_label ?? "",
      starts_at: s.starts_at ? isoToHomeInput(s.starts_at) : "",
      ends_at: s.ends_at ? isoToHomeInput(s.ends_at) : "",
    })),
  };
}

function toPlan(d: Draft): TripPlan {
  return {
    purpose: d.purpose.trim() || null,
    origin: d.origin,
    destination: d.destination,
    destination_country: d.destination_country.toUpperCase(),
    starts_on: d.starts_on,
    ends_on: d.ends_on,
    travellers: d.travellers.map((p) => p.id),
    segments: d.segments.map((s) => ({
      kind: s.kind,
      title: s.title,
      place_label: s.place_label.trim() || null,
      starts_at: homeInputToIso(s.starts_at),
      ends_at: homeInputToIso(s.ends_at),
    })),
  };
}

/** JR-01, JR-02: a draft trip planned on the travellers' behalf. Nothing is submitted here. */
export function TripPlanner({
  editing,
  onClose,
  onSaved,
}: {
  editing: TripDetail | null;
  onClose: () => void;
  onSaved: (trip: TripDetail) => void;
}) {
  const [draft, setDraft] = useState<Draft>(() => fromTrip(editing));
  const [query, setQuery] = useState("");
  const people = usePeople(query, 8).data?.items ?? [];
  const save = useSaveTrip();
  const change = (patch: Partial<Draft>) => setDraft({ ...draft, ...patch });
  const setSegment = (n: number, patch: Partial<SegmentRow>) =>
    change({ segments: draft.segments.map((s, i) => (i === n ? { ...s, ...patch } : s)) });
  const complete =
    draft.origin.trim() &&
    draft.destination.trim() &&
    /^[A-Za-z]{2}$/.test(draft.destination_country) &&
    draft.starts_on &&
    draft.ends_on &&
    draft.travellers.length > 0 &&
    draft.segments.every((s) => s.title.trim() && s.starts_at && s.ends_at);

  return (
    <Card
      icon="airplane"
      title={editing ? `Edit ${editing.reference}` : "Plan a trip"}
      sub="Saved as a draft · submitted from the trip"
      actions={<Button minimal small icon="cross" aria-label="Close planner" onClick={onClose} />}
    >
      <div className="nx-bd nx-composer">
        <label className="nx-lbl" htmlFor="trip-purpose">
          Purpose
        </label>
        <InputGroup
          id="trip-purpose"
          value={draft.purpose}
          maxLength={200}
          onChange={(e) => change({ purpose: e.currentTarget.value })}
        />
        <div className="nx-trip-cols">
          <div>
            <label className="nx-lbl" htmlFor="trip-origin">
              From
            </label>
            <InputGroup
              id="trip-origin"
              value={draft.origin}
              maxLength={120}
              onChange={(e) => change({ origin: e.currentTarget.value })}
            />
          </div>
          <div>
            <label className="nx-lbl" htmlFor="trip-destination">
              To (city)
            </label>
            <InputGroup
              id="trip-destination"
              value={draft.destination}
              maxLength={120}
              onChange={(e) => change({ destination: e.currentTarget.value })}
            />
          </div>
          <div>
            <label className="nx-lbl" htmlFor="trip-country">
              Country (ISO, e.g. FR)
            </label>
            <InputGroup
              id="trip-country"
              value={draft.destination_country}
              maxLength={2}
              onChange={(e) => change({ destination_country: e.currentTarget.value.toUpperCase() })}
            />
          </div>
          <div className="nx-row">
            <div>
              <label className="nx-lbl" htmlFor="trip-starts">
                Starts
              </label>
              <input
                id="trip-starts"
                className={Classes.INPUT}
                type="date"
                value={draft.starts_on}
                onChange={(e) => change({ starts_on: e.currentTarget.value })}
              />
            </div>
            <div>
              <label className="nx-lbl" htmlFor="trip-ends">
                Ends
              </label>
              <input
                id="trip-ends"
                className={Classes.INPUT}
                type="date"
                value={draft.ends_on}
                onChange={(e) => change({ ends_on: e.currentTarget.value })}
              />
            </div>
          </div>
        </div>

        <label className="nx-lbl" htmlFor="trip-people">
          Travellers
        </label>
        <InputGroup
          id="trip-people"
          leftIcon="search"
          placeholder="Search People & Sites"
          value={query}
          onChange={(e) => setQuery(e.currentTarget.value)}
        />
        {query && (
          <div className="nx-chips" aria-label="People found">
            {people
              .filter((p) => !draft.travellers.some((t) => t.id === p.id))
              .map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className="nx-tg"
                  onClick={() => change({ travellers: [...draft.travellers, { id: p.id, full_name: p.full_name }] })}
                >
                  + {p.full_name}
                  {p.mission_code ? ` · ${p.mission_code}` : ""}
                </button>
              ))}
          </div>
        )}
        <div className="nx-chips" aria-label="Chosen travellers">
          {draft.travellers.map((p) => (
            <button
              key={p.id}
              type="button"
              className="nx-tg on"
              aria-label={`Remove ${p.full_name}`}
              onClick={() => change({ travellers: draft.travellers.filter((t) => t.id !== p.id) })}
            >
              {p.full_name} <Icon icon="cross" size={10} />
            </button>
          ))}
          {draft.travellers.length === 0 && <span className="nx-dim">Nobody yet</span>}
        </div>

        <div className="nx-lbl">Itinerary ({HOME_TZ_LABEL})</div>
        {draft.segments.map((s, n) => (
          <div key={n} className="nx-segment" role="group" aria-label={`Segment ${n + 1}`}>
            <HTMLSelect
              aria-label="Kind"
              value={s.kind}
              onChange={(e) => setSegment(n, { kind: e.currentTarget.value as SegmentKind })}
              options={KINDS.map(([value, label]) => ({ value, label }))}
            />
            <InputGroup
              aria-label="Title"
              placeholder="e.g. EK 073 or Hotel"
              value={s.title}
              maxLength={200}
              onChange={(e) => setSegment(n, { title: e.currentTarget.value })}
            />
            <InputGroup
              aria-label="Place"
              placeholder="Place"
              value={s.place_label}
              maxLength={200}
              onChange={(e) => setSegment(n, { place_label: e.currentTarget.value })}
            />
            <input
              aria-label="Starts at"
              className={`${Classes.INPUT} nx-seg-start`}
              type="datetime-local"
              value={s.starts_at}
              onChange={(e) => setSegment(n, { starts_at: e.currentTarget.value })}
            />
            <input
              aria-label="Ends at"
              className={`${Classes.INPUT} nx-seg-end`}
              type="datetime-local"
              value={s.ends_at}
              onChange={(e) => setSegment(n, { ends_at: e.currentTarget.value })}
            />
            <Button
              className="nx-seg-remove"
              minimal
              icon="cross"
              aria-label={`Remove segment ${n + 1}`}
              onClick={() => change({ segments: draft.segments.filter((_, i) => i !== n) })}
            />
          </div>
        ))}
        <div>
          <Button
            small
            icon="add"
            text="Add segment"
            onClick={() =>
              change({
                segments: [
                  ...draft.segments,
                  {
                    kind: "FLIGHT",
                    title: "",
                    place_label: "",
                    starts_at: draft.starts_on ? `${draft.starts_on}T09:00` : "",
                    ends_at: draft.starts_on ? `${draft.starts_on}T12:00` : "",
                  },
                ],
              })
            }
          />
        </div>

        <div className="nx-row nx-composer-actions">
          <Button
            intent="primary"
            text="Save draft"
            disabled={!complete}
            loading={save.isPending}
            onClick={() => save.mutate({ id: editing?.id ?? null, plan: toPlan(draft) }, { onSuccess: onSaved })}
          />
          <Button minimal text="Discard" onClick={onClose} />
        </div>
        {save.error && <div className="nx-error">{save.error instanceof ApiError ? save.error.message : "Not saved"}</div>}
      </div>
    </Card>
  );
}
