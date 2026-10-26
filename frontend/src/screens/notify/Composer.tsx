import { Button, HTMLSelect, Icon, Radio, RadioGroup, TextArea } from "@blueprintjs/core";
import { useState } from "react";

import { ApiError } from "../../api/client";
import { useIncidents } from "../../api/intel";
import {
  type CampaignKind,
  type Draft,
  type NtfCampaign,
  type Preview,
  type Rendered,
  type Template,
  useCampaignAction,
  usePreview,
  useSaveDraft,
  useTemplates,
  useTestSend,
} from "../../api/notifications";
import { useMissions } from "../../api/people";
import { Card } from "../../ui/primitives";
import { draftOf, EMPTY } from "./drafts";
import { TestPhone } from "./TestPhone";

const KINDS: [CampaignKind, string][] = [
  ["ALERT", "Alert"],
  ["ADVISORY", "Advisory"],
  ["CHECKIN", "Safety check-in"],
];
const CHANNELS: [string, string][] = [
  ["APP", "App push"],
  ["SMS", "SMS"],
  ["WHATSAPP", "WhatsApp"],
  ["VOICE", "Voice call"],
  ["EMAIL", "Email"],
];
const PERSON_TYPES: [string, string][] = [
  ["DIPLOMAT", "Diplomats"],
  ["LOCAL_STAFF", "Local staff"],
  ["DELEGATE", "Delegates"],
  ["DEPENDANT", "Dependants"],
  ["CONTRACTOR", "Contractors"],
  ["CITIZEN", "Citizens"],
];
const LANGUAGES: [string, string][] = [
  ["ar", "Arabic"],
  ["fr", "French"],
  ["sw", "Swahili"],
];
const CONFIRM_ABOVE = 500; // plan G-10: ask before a large send
const NO_MISSION_CITY = "the affected area"; // as templates.resolve on the server

/** MN-03, like templates.resolve(): the mission's own template, else the generic one. */
function resolveTemplate(templates: Template[], code: string, missionId: string | null) {
  const active = templates.filter((t) => t.code === code && t.is_active);
  return active.find((t) => t.mission_id === missionId) ?? active.find((t) => t.mission_id === null);
}

function toggle(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong";
}

/** MN-01, MN-02, MN-03, MN-08: write a draft, see who it reaches, test it, submit it.
 *  The screen gives it a key per campaign being edited, so it starts afresh each time. */
export function Composer({
  editing,
  onDone,
}: {
  editing: NtfCampaign | null;
  onDone: (campaign: NtfCampaign) => void;
}) {
  const [draft, setDraft] = useState<Draft>(() => (editing ? draftOf(editing) : EMPTY));
  const [campaignId, setCampaignId] = useState<string | null>(editing?.id ?? null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [rendered, setRendered] = useState<Rendered | null>(null);
  const [confirming, setConfirming] = useState(false);
  // The chosen template's texts as filled in for this scope: what the server's pilot
  // check compares a translation with (MN-06, plan G-11).
  const [filled, setFilled] = useState<Record<string, string>>({});
  const missions = useMissions().data ?? [];
  const incidents = useIncidents("ACTIVE").data ?? [];
  const templates = useTemplates().data ?? [];
  const save = useSaveDraft();
  const previewMutation = usePreview();
  const testSend = useTestSend();
  const action = useCampaignAction();

  const change = (patch: Partial<Draft>) => {
    setDraft((d) => ({ ...d, ...patch }));
    setPreview(null); // the saved draft no longer matches what is on screen
    setConfirming(false);
  };

  // The scope a template is resolved for (plan G-3): the incident's mission for the
  // exposed audience, a single selected mission, otherwise none.
  const scopeMission = draft.exposed_to_incident
    ? (incidents.find((i) => i.id === draft.incident_id)?.mission_id ?? null)
    : draft.missions.length === 1
      ? (draft.missions[0] ?? null)
      : null;
  const codes = [...new Map(templates.filter((t) => t.kind === draft.kind).map((t) => [t.code, t])).values()];
  const chosen = templates.find((t) => t.id === draft.template_id);

  const applyTemplate = (code: string) => {
    if (!code) return change({ template_id: null });
    const template = resolveTemplate(templates, code, scopeMission);
    if (!template) return;
    const city = missions.find((m) => m.id === scopeMission)?.city ?? NO_MISSION_CITY;
    const fill = (text: string) => text.split("{city}").join(city);
    const texts = Object.fromEntries(Object.entries(template.texts).map(([k, v]) => [k, fill(v)]));
    const { en, ...translations } = texts;
    setFilled(texts);
    change({ template_id: template.id, message: en ?? "", translations });
  };

  const saveAndPreview = () =>
    save.mutate(
      { id: campaignId, draft },
      {
        onSuccess: (c) => {
          setCampaignId(c.id);
          previewMutation.mutate(c.id, { onSuccess: setPreview });
        },
      },
    );

  const citizens = (preview?.by_person_type.CITIZEN ?? 0) > 0;
  const submit = () => {
    if (!campaignId || !preview) return;
    if (!citizens && preview.recipients > CONFIRM_ABOVE && !confirming) return setConfirming(true);
    action.mutate(
      { id: campaignId, action: "submit" },
      {
        onSuccess: (c) => {
          onDone(c);
          setDraft(EMPTY);
          setCampaignId(null);
          setPreview(null);
          setRendered(null);
          setConfirming(false);
        },
      },
    );
  };

  const reviewedText = (lang: string) =>
    !!chosen?.reviewed[lang] && draft.translations[lang] === filled[lang];
  const error = save.error ?? previewMutation.error ?? testSend.error ?? action.error;

  return (
    <Card
      icon="send-message"
      title={campaignId ? "Edit draft" : "Compose message"}
      sub={campaignId ? "Saved as a draft · nothing sent yet" : "Simulated channels (D-19)"}
    >
      <div className="nx-bd nx-composer">
        <label className="nx-lbl" htmlFor="ntf-kind">
          Kind
        </label>
        <HTMLSelect
          id="ntf-kind"
          value={draft.kind}
          onChange={(e) => change({ kind: e.currentTarget.value as CampaignKind, template_id: null })}
          options={KINDS.map(([value, label]) => ({ value, label }))}
        />

        <div className="nx-lbl">Audience</div>
        <RadioGroup
          inline
          selectedValue={draft.exposed_to_incident ? "exposed" : "missions"}
          onChange={(e) =>
            change({
              exposed_to_incident: e.currentTarget.value === "exposed",
              missions: e.currentTarget.value === "exposed" ? [] : draft.missions,
            })
          }
        >
          <Radio label="Missions" value="missions" />
          <Radio label="People exposed to an incident" value="exposed" />
        </RadioGroup>
        {draft.exposed_to_incident ? (
          <HTMLSelect
            aria-label="Incident"
            value={draft.incident_id ?? ""}
            onChange={(e) => change({ incident_id: e.currentTarget.value || null })}
            options={[
              { value: "", label: "Choose an active incident" },
              ...incidents.map((i) => ({ value: i.id, label: `${i.reference} · ${i.title}` })),
            ]}
          />
        ) : (
          <>
            <HTMLSelect
              aria-label="Add mission"
              value=""
              onChange={(e) =>
                e.currentTarget.value &&
                change({ missions: [...new Set([...draft.missions, e.currentTarget.value])] })
              }
              options={[
                { value: "", label: "Add a mission" },
                ...missions
                  .filter((m) => !draft.missions.includes(m.id))
                  .map((m) => ({ value: m.id, label: `${m.code} · ${m.city}` })),
              ]}
            />
            <div className="nx-chips" aria-label="Chosen missions">
              {draft.missions.map((id) => {
                const m = missions.find((x) => x.id === id);
                return (
                  <button
                    key={id}
                    type="button"
                    className="nx-tg on"
                    aria-label={`Remove ${m?.code ?? id}`}
                    onClick={() => change({ missions: draft.missions.filter((x) => x !== id) })}
                  >
                    {m ? `${m.code} · ${m.city}` : id} <Icon icon="cross" size={10} />
                  </button>
                );
              })}
            </div>
          </>
        )}
        <div className="nx-chips" role="group" aria-label="Person types">
          {PERSON_TYPES.map(([value, label]) => {
            const on = draft.person_types?.includes(value) ?? false;
            return (
              <button
                key={value}
                type="button"
                aria-pressed={on}
                className={`nx-tg${on ? " on" : ""}`}
                onClick={() => {
                  const next = toggle(draft.person_types ?? [], value);
                  change({ person_types: next.length ? next : null });
                }}
              >
                {label}
              </button>
            );
          })}
          {!draft.person_types && <span className="nx-dim">All people</span>}
        </div>

        <div className="nx-lbl">Channels</div>
        <div className="nx-chips" role="group" aria-label="Channels">
          {CHANNELS.map(([value, label]) => {
            const on = draft.channels.includes(value);
            return (
              <button
                key={value}
                type="button"
                aria-pressed={on}
                className={`nx-tg${on ? " on" : ""}`}
                onClick={() => change({ channels: toggle(draft.channels, value) })}
              >
                {label}
              </button>
            );
          })}
        </div>

        <label className="nx-lbl" htmlFor="ntf-template">
          Template
        </label>
        <HTMLSelect
          id="ntf-template"
          value={chosen?.code ?? ""}
          onChange={(e) => applyTemplate(e.currentTarget.value)}
          options={[
            { value: "", label: "No template" },
            ...codes.map((t) => ({ value: t.code, label: t.name.replace(/ \(.*\)$/, "") })),
          ]}
        />

        <label className="nx-lbl" htmlFor="ntf-message">
          Message (English)
        </label>
        <TextArea
          id="ntf-message"
          fill
          rows={4}
          value={draft.message}
          maxLength={2000}
          onChange={(e) => change({ message: e.currentTarget.value })}
        />
        <details className="nx-translations">
          <summary>Translations · pre-written only (D-15)</summary>
          {LANGUAGES.map(([lang, label]) => (
            <div key={lang}>
              <label className="nx-lbl" htmlFor={`ntf-${lang}`}>
                {label}{" "}
                {draft.translations[lang] !== undefined &&
                  (reviewedText(lang) ? (
                    <span className="nx-safe">reviewed template text</span>
                  ) : (
                    <span className="nx-pending">not reviewed</span>
                  ))}
              </label>
              <TextArea
                id={`ntf-${lang}`}
                fill
                rows={2}
                dir={lang === "ar" ? "rtl" : undefined}
                value={draft.translations[lang] ?? ""}
                maxLength={2000}
                onChange={(e) => {
                  const rest = Object.fromEntries(
                    Object.entries(draft.translations).filter(([k]) => k !== lang),
                  );
                  const value = e.currentTarget.value;
                  change({ translations: value ? { ...rest, [lang]: value } : rest });
                }}
              />
            </div>
          ))}
        </details>

        {preview && (
          <div className="nx-preview" aria-label="Recipients">
            <b>{preview.recipients.toLocaleString("en-GB")} recipients</b>
            <span className="nx-dim">
              {Object.entries(preview.by_person_type)
                .map(([type, n]) => `${n} ${type.toLowerCase().replace("_", " ")}`)
                .join(" · ")}
            </span>
            {citizens && (
              <span className="nx-pending">Citizens included: a second person must approve (D-31)</span>
            )}
          </div>
        )}
        {error && <div className="nx-error">{errorText(error)}</div>}

        <div className="nx-row nx-composer-actions">
          <Button text={campaignId ? "Save and preview" : "Save draft"} loading={save.isPending} onClick={saveAndPreview} />
          <Button
            text="Send test to me"
            disabled={!campaignId}
            loading={testSend.isPending}
            onClick={() => campaignId && testSend.mutate(campaignId, { onSuccess: setRendered })}
          />
          <span className="nx-grow" />
          <Button
            intent={confirming ? "danger" : "primary"}
            icon="send-message"
            disabled={!preview}
            loading={action.isPending}
            text={
              !preview
                ? "Submit"
                : citizens
                  ? "Submit for approval"
                  : confirming
                    ? `Confirm: send to ${preview.recipients.toLocaleString("en-GB")}`
                    : `Send to ${preview.recipients.toLocaleString("en-GB")} recipients`
            }
            onClick={submit}
          />
        </div>
        {rendered && <TestPhone rendered={rendered} />}
      </div>
    </Card>
  );
}
