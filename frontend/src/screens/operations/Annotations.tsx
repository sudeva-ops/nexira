import {
  Button,
  ButtonGroup,
  Dialog,
  DialogBody,
  DialogFooter,
  FormGroup,
  HTMLSelect,
  InputGroup,
  TextArea,
} from "@blueprintjs/core";
import { useState } from "react";

import {
  type Annotation,
  type AnnotationKind,
  type AnnotationSymbol,
  annotationWhat,
  SYMBOL_LABEL,
  useAddAnnotation,
  useEditAnnotation,
  useWithdrawAnnotation,
} from "../../api/annotations";
import { ApiError } from "../../api/client";
import type { Incident } from "../../api/intel";
import { canFinish, type Draft, DRAW_MIN_ZOOM, draftShape, drawHint } from "../../map/annotations";
import { formatStamp } from "../../app/time";

// Map annotations on Global Operations (ANN-01..04; D-52; plan-pilot-map §2): the toolbar, the
// form for a finished drawing, and the card of a picked annotation with Edit and Withdraw where
// the API allows (can_edit). The author is shown by role only (ANN-04).

const KIND_LABEL: Record<AnnotationKind, string> = { MARK: "Mark", LINE: "Line", AREA: "Area" };
const SYMBOLS = Object.keys(SYMBOL_LABEL) as AnnotationSymbol[];

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "Not saved";
}

/** "2026-11-11T14:02" for a datetime-local input, and back to ISO. */
function localValue(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}
function isoValue(local: string): string | null {
  return local ? new Date(local).toISOString() : null;
}

/** The toolbar (ANN-01): Mark, Line, Area from city zoom; the hint and Finish while drawing. */
export function AnnotationTools({
  zoom,
  draft,
  onStart,
  onFinish,
  onCancel,
}: {
  zoom: number;
  draft: Draft | null;
  onStart: (kind: AnnotationKind) => void;
  onFinish: () => void;
  onCancel: () => void;
}) {
  const close = zoom >= DRAW_MIN_ZOOM;
  return (
    <div className="nx-ann-tools" role="toolbar" aria-label="Annotate">
      {draft ? (
        <>
          <span className="nx-ann-hint">{drawHint(draft)}</span>
          {draft.kind !== "MARK" && (
            <Button small intent="primary" text="Finish" disabled={!canFinish(draft)} onClick={onFinish} />
          )}
          <Button small text="Cancel" onClick={onCancel} />
        </>
      ) : (
        <>
          <ButtonGroup>
            {(["MARK", "LINE", "AREA"] as const).map((kind) => (
              <Button
                key={kind}
                small
                icon={kind === "MARK" ? "map-marker" : kind === "LINE" ? "route" : "polygon-filter"}
                text={KIND_LABEL[kind]}
                disabled={!close}
                onClick={() => onStart(kind)}
              />
            ))}
          </ButtonGroup>
          {!close && <span className="nx-ann-hint">Zoom in to draw</span>}
        </>
      )}
    </div>
  );
}

/** The form for a finished drawing (ANN-01); saved through the API, which decides who may. */
export function AnnotationForm({
  draft,
  incidents,
  incidentId,
  onClose,
}: {
  draft: Draft;
  incidents: Incident[];
  incidentId: string | null;
  onClose: () => void;
}) {
  const add = useAddAnnotation();
  const [symbol, setSymbol] = useState<AnnotationSymbol>("CHECKPOINT");
  const [label, setLabel] = useState("");
  const [note, setNote] = useState("");
  const [incident, setIncident] = useState(incidentId ?? "");
  const [ends, setEnds] = useState("");
  const shape = draftShape(draft);
  const submit = () => {
    if (!shape || !label.trim()) return;
    add.mutate(
      {
        kind: draft.kind,
        symbol: draft.kind === "MARK" ? symbol : null,
        shape,
        label: label.trim(),
        note: note.trim() || null,
        incident_id: incident || null,
        ends_at: isoValue(ends),
      },
      { onSuccess: onClose },
    );
  };
  return (
    <Dialog isOpen onClose={onClose} title={`New ${KIND_LABEL[draft.kind].toLowerCase()}`} icon="annotation">
      <DialogBody>
        {draft.kind === "MARK" && (
          <FormGroup label="Symbol" labelFor="nx-ann-symbol">
            <HTMLSelect
              id="nx-ann-symbol"
              value={symbol}
              onChange={(e) => setSymbol(e.currentTarget.value as AnnotationSymbol)}
              options={SYMBOLS.map((s) => ({ value: s, label: SYMBOL_LABEL[s] }))}
            />
          </FormGroup>
        )}
        <FormGroup label="Label" labelFor="nx-ann-label" helperText="Shown on the map to every role">
          <InputGroup
            id="nx-ann-label"
            maxLength={80}
            value={label}
            autoFocus
            onChange={(e) => setLabel(e.currentTarget.value)}
          />
        </FormGroup>
        <FormGroup label="Note" labelFor="nx-ann-note">
          <TextArea id="nx-ann-note" fill maxLength={280} value={note} onChange={(e) => setNote(e.currentTarget.value)} />
        </FormGroup>
        <FormGroup label="Incident" labelFor="nx-ann-incident" helperText="On its timeline and in its replay">
          <HTMLSelect
            id="nx-ann-incident"
            value={incident}
            onChange={(e) => setIncident(e.currentTarget.value)}
            options={[
              { value: "", label: "None" },
              ...incidents.map((i) => ({ value: i.id, label: `${i.reference} · ${i.title}` })),
            ]}
          />
        </FormGroup>
        <FormGroup label="Ends" labelFor="nx-ann-ends" helperText="Optional: it leaves the map by itself then">
          <input
            id="nx-ann-ends"
            className="bp6-input"
            type="datetime-local"
            value={ends}
            onChange={(e) => setEnds(e.currentTarget.value)}
          />
        </FormGroup>
        {add.isError && <div className="nx-error">{errorText(add.error)}</div>}
      </DialogBody>
      <DialogFooter
        actions={
          <>
            <Button text="Cancel" onClick={onClose} />
            <Button
              intent="primary"
              icon="tick"
              text="Add"
              disabled={!shape || !label.trim()}
              loading={add.isPending}
              onClick={submit}
            />
          </>
        }
      />
    </Dialog>
  );
}

/** A picked annotation (ANN-03, ANN-04): what it is, its role and time, Edit and Withdraw. */
export function AnnotationCard({ annotation, onClose }: { annotation: Annotation; onClose: () => void }) {
  const [editing, setEditing] = useState(false);
  const [withdrawing, setWithdrawing] = useState(false);
  const a = annotation;
  return (
    <div className="nx-ann-card" role="dialog" aria-label={`Annotation: ${a.label}`}>
      <div className="nx-ann-card-head">
        <b>{annotationWhat(a)}</b>
        <Button minimal small icon="cross" aria-label="Close" onClick={onClose} />
      </div>
      <div className="nx-ann-label">{a.label}</div>
      {a.note && <div className="nx-ann-note">{a.note}</div>}
      <div className="nx-dim">
        {a.role} · {formatStamp(a.created_at)}
        {a.updated_at && " · edited"}
        {a.incident_reference && ` · ${a.incident_reference}`}
        {a.ends_at && ` · ends ${formatStamp(a.ends_at)}`}
      </div>
      {a.can_edit && !withdrawing && (
        <div className="nx-row nx-ann-actions">
          <Button small icon="edit" text="Edit" onClick={() => setEditing(true)} />
          <Button small icon="remove" text="Withdraw" onClick={() => setWithdrawing(true)} />
        </div>
      )}
      {withdrawing && <WithdrawForm annotation={a} onDone={onClose} onCancel={() => setWithdrawing(false)} />}
      {editing && <EditDialog annotation={a} onClose={() => setEditing(false)} />}
    </div>
  );
}

function WithdrawForm({
  annotation,
  onDone,
  onCancel,
}: {
  annotation: Annotation;
  onDone: () => void;
  onCancel: () => void;
}) {
  const withdraw = useWithdrawAnnotation();
  const [reason, setReason] = useState("");
  return (
    <div className="nx-ann-withdraw">
      <InputGroup
        small
        aria-label="Reason"
        placeholder="Why it is withdrawn"
        maxLength={280}
        value={reason}
        autoFocus
        onChange={(e) => setReason(e.currentTarget.value)}
      />
      <Button
        small
        intent="danger"
        text="Withdraw"
        disabled={!reason.trim()}
        loading={withdraw.isPending}
        onClick={() => withdraw.mutate({ id: annotation.id, reason: reason.trim() }, { onSuccess: onDone })}
      />
      <Button small text="Cancel" onClick={onCancel} />
      {withdraw.isError && <div className="nx-error">{errorText(withdraw.error)}</div>}
    </div>
  );
}

function EditDialog({ annotation, onClose }: { annotation: Annotation; onClose: () => void }) {
  const edit = useEditAnnotation();
  const [label, setLabel] = useState(annotation.label);
  const [note, setNote] = useState(annotation.note ?? "");
  const [ends, setEnds] = useState(localValue(annotation.ends_at));
  const submit = () =>
    edit.mutate(
      { id: annotation.id, body: { label: label.trim(), note: note.trim() || null, ends_at: isoValue(ends) } },
      { onSuccess: onClose },
    );
  return (
    <Dialog isOpen onClose={onClose} title={`Edit ${annotationWhat(annotation).toLowerCase()}`} icon="edit">
      <DialogBody>
        <FormGroup label="Label" labelFor="nx-ann-edit-label">
          <InputGroup id="nx-ann-edit-label" maxLength={80} value={label} onChange={(e) => setLabel(e.currentTarget.value)} />
        </FormGroup>
        <FormGroup label="Note" labelFor="nx-ann-edit-note">
          <TextArea id="nx-ann-edit-note" fill maxLength={280} value={note} onChange={(e) => setNote(e.currentTarget.value)} />
        </FormGroup>
        <FormGroup label="Ends" labelFor="nx-ann-edit-ends">
          <input
            id="nx-ann-edit-ends"
            className="bp6-input"
            type="datetime-local"
            value={ends}
            onChange={(e) => setEnds(e.currentTarget.value)}
          />
        </FormGroup>
        <div className="nx-dim">To change the shape, withdraw it and draw it again.</div>
        {edit.isError && <div className="nx-error">{errorText(edit.error)}</div>}
      </DialogBody>
      <DialogFooter
        actions={
          <>
            <Button text="Cancel" onClick={onClose} />
            <Button intent="primary" text="Save" disabled={!label.trim()} loading={edit.isPending} onClick={submit} />
          </>
        }
      />
    </Dialog>
  );
}
