import { Button, Dialog, DialogBody, DialogFooter, FormGroup, HTMLSelect, Spinner, TextArea } from "@blueprintjs/core";
import { useState } from "react";

import { ApiError } from "../../api/client";
import { useMe } from "../../api/me";
import {
  type Partner,
  SERVICE_LABEL,
  SERVICES,
  type Service,
  slaText,
  useRequestPartner,
  useSuggestion,
} from "../../api/partners";
import { useMissions } from "../../api/people";
import { canRequestPartner } from "../../api/permissions";

export type RequestFor =
  // AS-06: someone needs help; the platform suggests, a person decides.
  | { kind: "sos"; personId: string; personName: string; incidentId: string | null }
  // AS-02: ask a chosen partner for one of its services, for a mission.
  | { kind: "partner"; partner: Partner };

const DEFAULT_SOS: Service = "SECURE_TRANSPORT"; // §33 Q6

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "Not requested";
}

/** The suggestion is a GET: its 409 is the restricted-traveller rule (AS-08, plan G-5). */
function suggestionError(error: unknown): string {
  if (error instanceof ApiError && error.status === 409) {
    return "A restricted traveller cannot be named to a partner (AS-08)";
  }
  return errorText(error);
}

/** Request partner support (AS-02, AS-06). Nothing is sent until "Request" is pressed. */
export function RequestDialog({ target, onClose }: { target: RequestFor; onClose: () => void }) {
  const me = useMe().data;
  const request = useRequestPartner();
  const [note, setNote] = useState("");
  const [service, setService] = useState<Service>(
    target.kind === "sos" ? DEFAULT_SOS : (target.partner.services[0] ?? "MEDICAL"),
  );
  const suggestion = useSuggestion(target.kind === "sos" ? target.personId : undefined, service);
  const [chosen, setChosen] = useState<string | null>(null);
  const missions = (useMissions().data ?? []).filter(
    (m) => target.kind === "partner" && target.partner.coverage.includes(m.country_code) && canRequestPartner(me, m.id),
  );
  const [missionId, setMissionId] = useState<string | null>(null);

  const candidates = target.kind === "sos" ? (suggestion.data?.partners ?? []) : [target.partner];
  const partnerId = chosen && candidates.some((p) => p.id === chosen) ? chosen : candidates[0]?.id;
  const mission = target.kind === "partner" ? (missionId ?? missions[0]?.id) : undefined;
  const services = target.kind === "sos" ? SERVICES : target.partner.services;
  const ready = !!partnerId && (target.kind === "sos" || !!mission);

  const submit = () => {
    if (!partnerId) return;
    request.mutate(
      target.kind === "sos"
        ? {
            partner_id: partnerId,
            service,
            person_id: target.personId,
            ...(target.incidentId ? { incident_id: target.incidentId } : {}),
            ...(note.trim() ? { note: note.trim() } : {}),
          }
        : { partner_id: partnerId, service, mission_id: mission, ...(note.trim() ? { note: note.trim() } : {}) },
      { onSuccess: onClose },
    );
  };

  return (
    <Dialog
      isOpen
      onClose={onClose}
      title={target.kind === "sos" ? `Request help for ${target.personName}` : `Request ${target.partner.name}`}
      icon="heart"
    >
      <DialogBody>
        <FormGroup label="Service" labelFor="nx-req-service">
          <HTMLSelect
            id="nx-req-service"
            value={service}
            onChange={(e) => setService(e.currentTarget.value as Service)}
            options={services.map((s) => ({ value: s, label: SERVICE_LABEL[s] }))}
          />
        </FormGroup>
        {target.kind === "sos" ? (
          <FormGroup
            label="Partner"
            labelFor="nx-req-partner"
            helperText="Nearest capable partner first (shortest SLA)"
          >
            {suggestion.isLoading ? (
              <Spinner size={16} />
            ) : suggestion.isError ? (
              <div className="nx-error">{suggestionError(suggestion.error)}</div>
            ) : candidates.length === 0 ? (
              <div className="nx-error">
                No partner covers {suggestion.data?.country_code} for {SERVICE_LABEL[service]}
              </div>
            ) : (
              <>
                <div className="nx-suggested">
                  Suggested: <b>{candidates[0]?.name}</b> · {slaText(candidates[0]?.sla_minutes ?? 0)} ·{" "}
                  {suggestion.data?.mission_code} mission
                </div>
                <HTMLSelect
                  id="nx-req-partner"
                  value={partnerId}
                  onChange={(e) => setChosen(e.currentTarget.value)}
                  options={candidates.map((p) => ({ value: p.id, label: `${p.name} · ${slaText(p.sla_minutes)}` }))}
                />
              </>
            )}
          </FormGroup>
        ) : (
          <FormGroup
            label="Mission"
            labelFor="nx-req-mission"
            helperText="Missions this partner covers and you may request for"
          >
            {missions.length === 0 ? (
              <div className="nx-error">No mission you may request for is covered by this partner</div>
            ) : (
              <HTMLSelect
                id="nx-req-mission"
                value={mission}
                onChange={(e) => setMissionId(e.currentTarget.value)}
                options={missions.map((m) => ({ value: m.id, label: `${m.city} (${m.code})` }))}
              />
            )}
          </FormGroup>
        )}
        <FormGroup
          label="Note for the partner"
          labelFor="nx-req-note"
          helperText="What they need to help. No health details (AS-08)."
        >
          <TextArea
            id="nx-req-note"
            fill
            maxLength={500}
            value={note}
            onChange={(e) => setNote(e.currentTarget.value)}
          />
        </FormGroup>
        <div className="nx-dim">Partners are simulated (D-19): nothing leaves the platform.</div>
        {request.isError && <div className="nx-error">{errorText(request.error)}</div>}
      </DialogBody>
      <DialogFooter
        actions={
          <>
            <Button text="Cancel" onClick={onClose} />
            <Button
              intent="primary"
              icon="send-message"
              text="Request"
              disabled={!ready}
              loading={request.isPending}
              onClick={submit}
            />
          </>
        }
      />
    </Dialog>
  );
}
