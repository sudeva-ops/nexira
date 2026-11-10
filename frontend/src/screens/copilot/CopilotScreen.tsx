import { Button, Icon, type IconName, InputGroup, NonIdealState } from "@blueprintjs/core";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../../api/client";
import { type Answer, type Sentence, type Source, SUGGESTIONS, useAsk, useReport } from "../../api/copilot";
import { useCampaigns } from "../../api/checkin";
import { useIncidents } from "../../api/intel";
import { useMissions } from "../../api/people";
import { useRuns } from "../../api/playbooks";
import { formatStamp } from "../../app/time";
import { Card } from "../../ui/primitives";
import { SkeletonRows } from "../../ui/Skeleton";

// COP-07 (plan-pilot-cop §6): the conversation, as the design, with the grounding context and
// the guardrails beside it. The conversation is this tab's state only (COP-06).

interface Turn {
  id: number;
  question: string;
  answer?: Answer;
  error?: string;
}

const SOURCE_ICON: Record<string, IconName> = {
  INCIDENT: "warning-sign",
  CHECKIN: "tick-circle",
  PLAYBOOK_RUN: "flash",
  PROPOSAL: "inbox",
  TRIP: "airplane",
  MISSION: "office",
  EXERCISE: "target",
  CAMPAIGN: "send-message",
  ADVISORY: "heart",
  SUPPLIER: "box",
  ASSET: "truck",
};

function SourceChip({ s }: { s: Source }) {
  return (
    <Link to={s.href} className="nx-cop-src" title={`${s.kind.toLowerCase().replace("_", " ")} ${s.reference}`}>
      <Icon icon={SOURCE_ICON[s.kind] ?? "document"} size={10} />
      {s.reference}
    </Link>
  );
}

function Sentences({ items }: { items: Sentence[] }) {
  return (
    <ul className="nx-cop-sentences">
      {items.map((s, i) => (
        <li key={i}>
          {s.text}
          {s.sources.length > 0 && (
            <span className="nx-cop-cites">
              {s.sources.map((src) => (
                <SourceChip key={`${src.kind}-${src.reference}`} s={src} />
              ))}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

function ReportDraft({ incidentId }: { incidentId: string }) {
  const report = useReport(incidentId);
  if (report.isError) return <div className="nx-error">The report could not be drafted.</div>;
  const r = report.data;
  if (!r) return <SkeletonRows rows={4} />;
  return (
    <div className="nx-cop-report" aria-label="Situation report">
      <h4>{r.title}</h4>
      <div className="nx-dim">
        As of {formatStamp(r.as_of)} · draft · {r.label}
      </div>
      {r.sections.map((s) => (
        <section key={s.heading}>
          <h5>
            {s.heading}
            {s.note && <span className="nx-dim"> · {s.note}</span>}
          </h5>
          <Sentences items={s.sentences} />
        </section>
      ))}
      <div className="nx-row nx-cop-report-actions">
        <Link to={`/copilot/report/${r.incident_id}/print`} className="bp6-button bp6-intent-primary">
          <Icon icon="document" size={14} />
          <span>Export as PDF</span>
        </Link>
        <span className="nx-dim">A draft: nothing is sent.</span>
      </div>
    </div>
  );
}

function Bubble({ turn }: { turn: Turn }) {
  return (
    <div className="nx-cop-turn" data-turn={turn.id}>
      <div className="nx-cop-q">{turn.question}</div>
      <div className="nx-cop-a" aria-label="Answer" aria-busy={!turn.answer && !turn.error}>
        <Icon icon="chat" className="nx-cop-avatar" />
        <div className="nx-grow">
          {turn.error ? (
            <div className="nx-error">{turn.error}</div>
          ) : turn.answer ? (
            <>
              <Sentences items={turn.answer.sentences} />
              {turn.answer.kind === "REPORT" && turn.answer.incident_id && (
                <ReportDraft incidentId={turn.answer.incident_id} />
              )}
              <div className="nx-cop-label">{turn.answer.label}</div>
            </>
          ) : (
            <span className="nx-cop-typing" aria-label="Answering">
              <i />
              <i />
              <i />
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function Grounding() {
  const active = useIncidents("ACTIVE").data?.length ?? 0;
  const checkins = (useCampaigns().data ?? []).filter((c) => c.campaign_type === "CHECKIN").length;
  const runs = useRuns().data?.length ?? 0;
  const missions = useMissions().data?.length ?? 0;
  const rows: [IconName, string, number][] = [
    ["warning-sign", "Active incidents", active],
    ["tick-circle", "Safety check-ins", checkins],
    ["flash", "Playbook runs", runs],
    ["office", "Mission profiles", missions],
  ];
  return (
    <Card icon="database" title="Grounding context">
      <ul className="nx-bd nx-cop-ground" aria-label="Grounding context">
        {rows.map(([icon, label, n]) => (
          <li key={label} className={n ? "on" : undefined}>
            <Icon icon={icon} size={12} />
            <span className="nx-grow">{label}</span>
            <span className="nx-mono">{n}</span>
            <span className="nx-cop-dot" aria-hidden="true" />
          </li>
        ))}
      </ul>
    </Card>
  );
}

const GUARDRAILS: [IconName, string][] = [
  ["lock", "Runs on sovereign infrastructure; no external AI service"],
  ["document", "Every answer cites its sources"],
  ["people", "Role-based data access enforced"],
  ["endorsed", "Human approval before distribution; nothing is sent from here"],
];

export function CopilotScreen() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const ask = useAsk();
  const nextId = useRef(1);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [turns]);

  const send = (question: string) => {
    const q = question.trim();
    if (!q || ask.isPending) return;
    const id = nextId.current++;
    setTurns((t) => [...t, { id, question: q }]);
    setDraft("");
    ask.mutate(q, {
      onSuccess: (answer) => setTurns((t) => t.map((x) => (x.id === id ? { ...x, answer } : x))),
      onError: (e) =>
        setTurns((t) =>
          t.map((x) =>
            x.id === id ? { ...x, error: e instanceof ApiError ? e.message : "Something went wrong" } : x,
          ),
        ),
    });
  };

  return (
    <div className="nx-pad nx-cop">
      <Card icon="chat" title="AI Risk Copilot" sub="Grounded on live incidents, people, playbooks and intelligence" className="nx-cop-chat">
        <div className="nx-cop-msgs" aria-label="Conversation" aria-live="polite">
          {turns.length === 0 ? (
            <NonIdealState
              icon="chat"
              title="How can I help the operations centre?"
              description="Ask about incidents, people, missions or request a briefing."
            />
          ) : (
            turns.map((t) => <Bubble key={t.id} turn={t} />)
          )}
          <div ref={end} />
        </div>
        <div className="nx-cop-sugs" aria-label="Suggestions">
          {SUGGESTIONS.map((s) => (
            <button key={s} type="button" className="nx-cop-sug" disabled={ask.isPending} onClick={() => send(s)}>
              {s}
            </button>
          ))}
        </div>
        <form
          className="nx-cop-composer"
          onSubmit={(e) => {
            e.preventDefault();
            send(draft);
          }}
        >
          <InputGroup
            aria-label="Question"
            placeholder="Ask NEXIRA anything…"
            maxLength={500}
            value={draft}
            onChange={(e) => setDraft(e.currentTarget.value)}
          />
          <Button type="submit" intent="primary" icon="send-message" aria-label="Ask" disabled={!draft.trim() || ask.isPending} />
        </form>
      </Card>
      <div className="nx-col">
        <Grounding />
        <Card icon="shield" title="Guardrails">
          <ul className="nx-bd nx-cop-guard" aria-label="Guardrails">
            {GUARDRAILS.map(([icon, text]) => (
              <li key={text}>
                <Icon icon={icon} size={12} />
                {text}
              </li>
            ))}
          </ul>
        </Card>
        <div className="nx-cop-sim">Simulated copilot · rule-based wording · a local model replaces only the wording later</div>
      </div>
    </div>
  );
}
