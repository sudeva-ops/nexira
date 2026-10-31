import { Button, Checkbox, HTMLSelect, InputGroup, NonIdealState, Tag } from "@blueprintjs/core";
import { useState } from "react";

import { ApiError } from "../../api/client";
import {
  daysText,
  DOC_LABEL,
  DOC_TYPES,
  type DocumentFilters,
  nextSteps,
  type RenewalStep,
  type TravelDocument,
  type Urgency,
  URGENCIES,
  useDocumentPermissions,
  useDocuments,
  useDocumentSummary,
  useRenew,
  useSendReminders,
} from "../../api/documents";
import { useMe } from "../../api/me";
import { useMissions } from "../../api/people";
import { formatStamp } from "../../app/time";
import { FlashRow } from "../../ui/motion";
import { Card, Kpi } from "../../ui/primitives";
import { SkeletonRows } from "../../ui/Skeleton";

const URGENCY_SEV: Record<Urgency, string> = {
  EXPIRED: "crit",
  CRITICAL: "crit",
  HIGH: "high",
  MODERATE: "med",
  OK: "ok",
};
const STEP_LABEL: Record<RenewalStep, string> = {
  REQUESTED: "Request renewal",
  IN_PROGRESS: "Start renewal",
  RENEWED: "Mark renewed",
};
const EXPIRING = ""; // the default urgency filter: everything but OK
const EVERY = "ANY";

/** Who took a renewal step, without showing a user id. */
function byWhom(who: string | null, meId: string | undefined): string {
  if (!who) return "";
  if (who === meId) return " by you";
  if (who.startsWith("agent:")) return " by agent proposal";
  if (who.startsWith("system:")) return "";
  return " by a colleague";
}

function Renewal({ d, meId }: { d: TravelDocument; meId: string | undefined }) {
  if (d.renewal_status === "RENEWED")
    return (
      <span className="nx-docs-renewed">
        Renewed{byWhom(d.renewed_by, meId)}
        {d.renewed_at && <div className="nx-dim">{formatStamp(d.renewed_at)}</div>}
      </span>
    );
  if (d.renewal_status === "IN_PROGRESS")
    return (
      <span>
        Renewal in progress{byWhom(d.renewal_started_by, meId)}
        {d.renewal_started_at && <div className="nx-dim">{formatStamp(d.renewal_started_at)}</div>}
      </span>
    );
  if (d.renewal_status === "REQUESTED")
    return (
      <span>
        Renewal requested{byWhom(d.renewal_requested_by, meId)}
        {d.renewal_requested_at && <div className="nx-dim">{formatStamp(d.renewal_requested_at)}</div>}
      </span>
    );
  return <span className="nx-dim">Not started</span>;
}

function DocumentRow({
  d,
  meId,
  selectable,
  selected,
  onSelect,
}: {
  d: TravelDocument;
  meId: string | undefined;
  selectable: boolean;
  selected: boolean;
  onSelect: (on: boolean) => void;
}) {
  const renew = useRenew();
  const [newDate, setNewDate] = useState<string | null>(null);
  const steps = d.can_act ? nextSteps(d.renewal_status) : [];
  const step = (s: RenewalStep, validUntil?: string) =>
    renew.mutate({ id: d.id, step: s, validUntil }, { onSuccess: () => setNewDate(null) });

  return (
    <FlashRow
      data-document={d.id}
      watch={`${d.renewal_status} ${d.valid_until}`}
      tone={d.renewal_status === "RENEWED" ? "success" : "info"}
    >
      <td>
        {selectable && (
          <Checkbox
            aria-label={`Select ${d.holder_name}'s ${DOC_LABEL[d.doc_type].toLowerCase()}`}
            checked={selected}
            onChange={(e) => onSelect(e.currentTarget.checked)}
          />
        )}
      </td>
      <td>
        <b>{d.holder_name}</b>
        <div className="nx-dim">{d.holder_type.toLowerCase().replace("_", " ")}</div>
      </td>
      <td>{d.mission_code ?? "—"}</td>
      <td>
        {DOC_LABEL[d.doc_type]}
        <div className="nx-dim">
          {d.issuing_country} · valid until {d.valid_until}
        </div>
      </td>
      <td className="nx-mono" style={{ color: d.days_left < 30 ? "#FA999C" : undefined }}>
        {d.days_left < 0 ? daysText(d.days_left) : d.days_left}
      </td>
      <td>
        <span className={`nx-sev ${URGENCY_SEV[d.urgency]}`}>{d.urgency}</span>
      </td>
      <td>
        {d.could_block_evacuation ? (
          <span className="nx-docs-block">Could block evacuation</span>
        ) : d.urgency === "OK" ? (
          "—"
        ) : (
          "Renewal due"
        )}
      </td>
      <td>
        <Renewal d={d} meId={meId} />
      </td>
      <td className="nx-nowrap">
        {newDate === null ? (
          steps.map((s) => (
            <Button
              key={s}
              size="small"
              minimal={s === "REQUESTED"}
              text={STEP_LABEL[s]}
              loading={renew.isPending}
              onClick={() => (s === "RENEWED" ? setNewDate("") : step(s))}
            />
          ))
        ) : (
          <div className="nx-row">
            <InputGroup
              size="small"
              type="date"
              aria-label="New valid-until date"
              value={newDate}
              onChange={(e) => setNewDate(e.currentTarget.value)}
            />
            <Button
              size="small"
              intent="success"
              text="Save"
              disabled={!newDate}
              loading={renew.isPending}
              onClick={() => step("RENEWED", newDate)}
            />
            <Button size="small" minimal text="Cancel" onClick={() => setNewDate(null)} />
          </div>
        )}
        {renew.isError && (
          <div className="nx-error">{renew.error instanceof ApiError ? renew.error.message : "Not done"}</div>
        )}
      </td>
    </FlashRow>
  );
}

function DocumentList({ missionScope }: { missionScope: string[] | null }) {
  const me = useMe().data;
  const missions = (useMissions().data ?? []).filter((m) => missionScope === null || missionScope.includes(m.id));
  const [filters, setFilters] = useState<DocumentFilters>({});
  const [urgency, setUrgency] = useState<string>(EXPIRING);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const send = useSendReminders();
  const query = useDocuments(
    { ...filters, urgency: urgency === EXPIRING || urgency === EVERY ? undefined : urgency },
    true,
  );
  const rows = (query.data ?? []).filter((d) => urgency !== EXPIRING || d.urgency !== "OK");
  const selectable = rows.filter((d) => d.can_act && d.urgency !== "OK");
  const chosen = selectable.filter((d) => selected.has(d.id));
  const allChosen = selectable.length > 0 && chosen.length === selectable.length;
  const toggle = (id: string, on: boolean) =>
    setSelected((s) => {
      const next = new Set(s);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  return (
    <Card
      className="nx-docs"
      icon="document"
      title="Expiring documents"
      sub={`Sorted by urgency · ${rows.length} shown · simulated`}
      actions={
        <div className="nx-row">
          <HTMLSelect
            minimal
            aria-label="Filter by mission"
            value={filters.mission_id ?? ""}
            onChange={(e) => setFilters({ ...filters, mission_id: e.currentTarget.value || undefined })}
            options={[
              { value: "", label: missionScope === null ? "All missions" : "My missions" },
              ...missions.map((m) => ({ value: m.id, label: m.code })),
            ]}
          />
          <HTMLSelect
            minimal
            aria-label="Filter by document type"
            value={filters.doc_type ?? ""}
            onChange={(e) => setFilters({ ...filters, doc_type: e.currentTarget.value || undefined })}
            options={[{ value: "", label: "All types" }, ...DOC_TYPES.map((t) => ({ value: t, label: DOC_LABEL[t] }))]}
          />
          <HTMLSelect
            minimal
            aria-label="Filter by urgency"
            value={urgency}
            onChange={(e) => setUrgency(e.currentTarget.value)}
            options={[
              { value: EXPIRING, label: "Expiring (not OK)" },
              ...URGENCIES.map((u) => ({ value: u, label: u })),
              { value: EVERY, label: "Every document" },
            ]}
          />
          {send.isSuccess ? (
            <Tag intent="success" minimal>
              REMINDERS SENT · {send.data.reference} · {send.data.recipients} recipient
              {send.data.recipients === 1 ? "" : "s"}
            </Tag>
          ) : (
            selectable.length > 0 && (
              <Button
                size="small"
                intent="primary"
                icon="send-message"
                text={`Send renewal reminders${chosen.length ? ` (${chosen.length})` : ""}`}
                disabled={chosen.length === 0}
                loading={send.isPending}
                onClick={() =>
                  send.mutate(
                    chosen.map((d) => d.id),
                    { onSuccess: () => setSelected(new Set()) },
                  )
                }
              />
            )
          )}
        </div>
      }
    >
      {send.isError && (
        <div className="nx-bd nx-error">{send.error instanceof ApiError ? send.error.message : "Not sent"}</div>
      )}
      {query.isLoading ? (
        <SkeletonRows />
      ) : rows.length === 0 ? (
        <NonIdealState icon="document" title="No documents" description="Nothing matches these filters." />
      ) : (
        <div className="nx-ntf-scroll">
          <table className="nx-table-plain" aria-label="Expiring documents">
            <thead>
              <tr>
                <th>
                  {selectable.length > 0 && (
                    <Checkbox
                      aria-label="Select every document you can act on"
                      checked={allChosen}
                      indeterminate={chosen.length > 0 && !allChosen}
                      onChange={() => setSelected(allChosen ? new Set() : new Set(selectable.map((d) => d.id)))}
                    />
                  )}
                </th>
                <th>Person</th>
                <th>Mission</th>
                <th>Document</th>
                <th>Days left</th>
                <th>Urgency</th>
                <th>Impact</th>
                <th>Renewal</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => (
                <DocumentRow
                  key={d.id}
                  d={d}
                  meId={me?.id}
                  selectable={d.can_act && d.urgency !== "OK"}
                  selected={selected.has(d.id)}
                  onSelect={(on) => toggle(d.id, on)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

/** Document Expiry (DX-02, DX-03, DX-08, DX-09; D-37). Documents are simulated (D-19). */
export function DocumentsScreen() {
  const allowed = useDocumentPermissions();
  const summary = useDocumentSummary().data;
  const pct = summary?.ready_pct;

  return (
    <div className="nx-pad">
      <div className="nx-g4">
        <Kpi icon="document" label="Documents tracked" value={summary?.tracked ?? "—"} detail="Staff & dependants" />
        <Kpi
          icon="warning-sign"
          label="Expiring < 30 days"
          value={summary?.expiring_30 ?? "—"}
          detail={
            summary?.could_block ? `${summary.could_block} could block evacuation` : "None could block evacuation"
          }
          alert={!!summary?.could_block}
        />
        <Kpi
          icon="time"
          label="Expiring < 90 days"
          value={summary?.expiring_90 ?? "—"}
          detail={`Renewal in progress: ${summary?.in_renewal_90 ?? "—"}`}
        />
        <Kpi
          icon="tick-circle"
          label="Evacuation-ready"
          value={pct === null || pct === undefined ? "—" : `${pct}%`}
          detail={summary ? `${summary.ready} of ${summary.people} people · passport valid 180+ days` : undefined}
        />
      </div>
      {allowed.isLoading ? (
        <SkeletonRows />
      ) : allowed.data?.read_documents ? (
        <DocumentList missionScope={allowed.data.read_document_missions} />
      ) : (
        <Card className="nx-docs" icon="document" title="Expiring documents">
          <NonIdealState
            icon="lock"
            title="Totals only"
            description="Your role sees the totals, not the people (DX-09)."
          />
        </Card>
      )}
    </div>
  );
}
