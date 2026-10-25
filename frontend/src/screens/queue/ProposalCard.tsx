import { Button, Icon, TextArea } from "@blueprintjs/core";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../../api/client";
import { LEVEL_COLOUR, LEVELS, type Proposal, useDecide } from "../../api/proposals";
import { ago, formatTime, HOME_TZ } from "../../app/time";
import { roleLabel } from "../../ui/format";
import { countdown, nextStep, REJECT_REASONS } from "./format";

function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  return now;
}

const STATUS_BADGE: Partial<Record<Proposal["status"], [string, string]>> = {
  AUTO_EXECUTED: ["ok", "AUTO-EXECUTED"],
  APPROVED: ["ok", "APPROVED"],
  EDITED_APPROVED: ["ok", "EDITED & APPROVED"],
  REJECTED: ["nt", "REJECTED"],
  SUPERSEDED: ["nt", "ALTERNATIVE CHOSEN"],
  UNDONE: ["nt", "UNDONE"],
  EXPIRED: ["crit", "EXPIRED · ESCALATED"],
  FAILED: ["crit", "FAILED"],
};

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong";
}

/** The text an edit changes: the message of an outgoing message, else the description. */
function editable(p: Proposal): { label: string; value: string } {
  if (p.action_type === "SEND_EXTERNAL_MESSAGE" && typeof p.action_payload.message === "string") {
    const edited = p.edited_payload?.message;
    return { label: "Message (English)", value: typeof edited === "string" ? edited : p.action_payload.message };
  }
  return { label: "Proposed action", value: p.edited_action ?? p.proposed_action };
}

export function ProposalCard({ p }: { p: Proposal }) {
  const pending = p.status === "PENDING";
  const undoable = p.status === "AUTO_EXECUTED" && p.can_undo;
  const now = useNow(pending || undoable);
  const decide = useDecide(p.id);
  const [mode, setMode] = useState<"idle" | "edit" | "reject">("idle");
  const field = editable(p);
  const [draft, setDraft] = useState(field.value);
  const level = p.effective_level;
  const colour = pending
    ? level >= 3
      ? "#CD4246"
      : "#EC9A3C"
    : ["REJECTED", "SUPERSEDED", "UNDONE"].includes(p.status)
      ? "#404854"
      : ["EXPIRED", "FAILED"].includes(p.status)
        ? "#CD4246"
        : "#32A467";
  const compact = ["AUTO_EXECUTED", "SUPERSEDED", "UNDONE"].includes(p.status) && !undoable;
  const badge = STATUS_BADGE[p.status];
  const step = nextStep(p);
  const canAct = p.can_decide || p.can_dismiss;

  const saveEdit = () =>
    decide.mutate(
      p.action_type === "SEND_EXTERNAL_MESSAGE"
        ? { kind: "edit", edited_payload: { ...p.action_payload, message: draft } }
        : { kind: "edit", edited_action: draft },
      { onSuccess: () => setMode("idle") },
    );

  return (
    <article
      className="nx-card nx-proposal"
      style={{ borderLeft: `3px solid ${colour}` }}
      aria-label={p.title}
      data-testid={`proposal-${p.action_type}`}
      data-proposal-id={p.id}
    >
      <header className="nx-proposal-hd">
        <Icon icon="predictive-analysis" size={12} />
        <span className="nx-chip">{p.agent_name} agent</span>
        {p.is_proactive && <span className="nx-chip nx-proactive">PROACTIVE</span>}
        <span className="nx-chip" style={{ color: LEVEL_COLOUR[level] }}>
          {LEVELS[level]}
        </span>
        <b className="nx-grow">{p.title}</b>
        {pending ? (
          <span className={`nx-deadline${countdown(p.deadline_at, now) === "OVERDUE" ? " over" : ""}`}>
            {level === 4 ? "Advice" : countdown(p.deadline_at, now)}
          </span>
        ) : (
          badge && <span className={`nx-sev ${badge[0]}`}>{badge[1]}</span>
        )}
        <span className="nx-dim nx-mono">{ago(p.created_at)}</span>
      </header>
      {compact ? (
        <div className="nx-bd nx-proposal-compact">{p.edited_action ?? p.proposed_action}</div>
      ) : (
        <div className="nx-bd nx-proposal-body">
          <div>
            <div className="nx-lbl">{mode === "edit" ? field.label : "Proposed action"}</div>
            {mode === "edit" ? (
              <TextArea
                aria-label={field.label}
                fill
                rows={3}
                value={draft}
                onChange={(e) => setDraft(e.currentTarget.value)}
              />
            ) : (
              <div className="nx-proposal-action">{p.edited_action ?? p.proposed_action}</div>
            )}
            {(p.edited_payload || p.edited_action) && mode !== "edit" && (
              <div className="nx-edited">Edited by a person</div>
            )}
            <div className="nx-lbl nx-mt">Why the agent recommends this</div>
            {p.evidence.map((e, i) => (
              <div key={i} className="nx-evidence">
                · {e.text}
              </div>
            ))}
            <div className="nx-row nx-wrap nx-mt-s">
              {[...new Set(p.evidence.map((e) => e.source))].map((s) => (
                <span key={s} className="nx-src">
                  {s}
                </span>
              ))}
            </div>
          </div>
          <div>
            <div className="nx-row nx-proposal-facts">
              <div>
                <div className="nx-lbl">Confidence</div>
                <div className={`nx-mono nx-conf-v${(p.confidence ?? 0) >= 85 ? " hi" : ""}`}>
                  {p.confidence ?? "—"}%
                </div>
              </div>
              <div className="nx-grow">
                <div className="nx-lbl">Approver</div>
                {p.approvals.length ? (
                  p.approvals.map((a) => (
                    <div key={a.step_no} className="nx-approver" data-testid={`approver-${a.step_no}`}>
                      {a.decision === "APPROVE" ? "✓ " : a.decision === "REJECT" ? "✗ " : ""}
                      {roleLabel(a.required_role)}
                      {a.decided_by_name && (
                        <span className="nx-dim">
                          {" "}
                          · {a.decided_by_name}
                          {a.decided_at && ` · ${formatTime(new Date(a.decided_at), HOME_TZ)}`}
                        </span>
                      )}
                    </div>
                  ))
                ) : (
                  <div className="nx-dim">{level === 4 ? "Advice only: never executed" : "Executes automatically"}</div>
                )}
              </div>
            </div>
            {p.risk_if_no_action && (
              <>
                <div className="nx-lbl">Risk if no action</div>
                <div className="nx-risk">{p.risk_if_no_action}</div>
              </>
            )}
            {p.alternatives.length > 0 && (
              <>
                <div className="nx-lbl">Alternatives considered</div>
                {p.alternatives.map((a, i) => (
                  <div key={i} className="nx-row nx-alt">
                    <span className="nx-grow nx-dim" title={a.rationale}>
                      {a.label}
                    </span>
                    {pending && canAct && (
                      <Button
                        size="small"
                        text="Use"
                        aria-label={`Use alternative: ${a.label}`}
                        onClick={() => decide.mutate({ kind: "alternative", index: i })}
                      />
                    )}
                  </div>
                ))}
              </>
            )}
          </div>
        </div>
      )}
      {pending && canAct && (
        <footer className="nx-proposal-ft nx-row">
          {mode === "reject" ? (
            <>
              <span className="nx-dim">Reason:</span>
              {REJECT_REASONS.map((r) => (
                <Button key={r} size="small" text={r} onClick={() => decide.mutate({ kind: "reject", reason: r })} />
              ))}
              <span className="nx-grow" />
              <Button size="small" text="Cancel" onClick={() => setMode("idle")} />
            </>
          ) : mode === "edit" ? (
            <>
              <span className="nx-grow nx-dim">Editing the agent's proposal</span>
              <Button size="small" text="Cancel" onClick={() => setMode("idle")} />
              <Button
                size="small"
                intent="primary"
                icon="tick"
                text="Save & approve"
                disabled={!draft.trim() || draft === field.value}
                onClick={saveEdit}
              />
            </>
          ) : (
            <>
              {p.can_decide && (
                <>
                  <Button
                    size="small"
                    intent="primary"
                    icon="tick"
                    text={`Approve${step ? ` as ${step}` : ""}`}
                    loading={decide.isPending}
                    onClick={() => decide.mutate({ kind: "approve" })}
                  />
                  {p.approvals.every((a) => a.decision === null) && (
                    <Button size="small" icon="edit" text="Edit" onClick={() => setMode("edit")} />
                  )}
                </>
              )}
              <Button
                size="small"
                icon="cross"
                text={p.can_dismiss ? "Dismiss" : "Reject"}
                onClick={() => setMode("reject")}
              />
              <span className="nx-grow" />
              {p.incident_id && (
                <Link to={`/incidents?id=${p.incident_id}`}>Open {p.incident_reference} →</Link>
              )}
            </>
          )}
        </footer>
      )}
      {undoable && p.undo_until && (
        <footer className="nx-proposal-ft nx-row">
          <span className="nx-grow nx-dim">
            Executed automatically under "Auto + notice" ·{" "}
            {countdown(p.undo_until, now).replace("Decide in", "undo for")}
          </span>
          <Button size="small" icon="undo" text="Undo" onClick={() => decide.mutate({ kind: "undo" })} />
        </footer>
      )}
      {p.status === "REJECTED" && p.rejection_reason && (
        <div className="nx-bd nx-dim">Reason: {p.rejection_reason}</div>
      )}
      {decide.isError && <div className="nx-bd nx-error">{errorText(decide.error)}</div>}
    </article>
  );
}
