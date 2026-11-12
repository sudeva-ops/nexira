import {
  Button,
  HTMLSelect,
  Icon,
  InputGroup,
  NonIdealState,
} from "@blueprintjs/core";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import {
  acceptedOf,
  type Item,
  type Metric,
  type Priority,
  type Review,
  TEAMS,
  type Team,
  teamLabel,
  useAccept,
  useAddItem,
  useDone,
  useFinalise,
  useReject,
  useReview,
  useReviews,
  useStartReview,
} from "../../api/aar";
import { ApiError } from "../../api/client";
import { formatStamp } from "../../app/time";
import { Card, ExerciseTag, Kpi } from "../../ui/primitives";
import { SkeletonRows } from "../../ui/Skeleton";
import { REJECT_REASONS } from "../queue/format";
import { inDays, metricTarget, metricValue } from "./format";
import { TileRow } from "../../ui/TileRow";
import { Empty } from "../../ui/Empty";

const PRIORITY_SEV: Record<Priority, string> = {
  HIGH: "high",
  MEDIUM: "med",
  LOW: "low",
};
const STATUS_SEV: Record<string, string> = {
  DRAFT: "med",
  ACCEPTED: "ok",
  DONE: "ok",
  REJECTED: "nt",
};

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong";
}

function byKey(metrics: Metric[], key: string): Metric | undefined {
  return metrics.find((m) => m.key === key);
}

/** The design's four KPIs (AAR-08). */
function Figures({ r }: { r: Review }) {
  const [accepted, total] = acceptedOf(r.items);
  const kpi = (
    key: string,
    icon: "time" | "notifications" | "people",
    fallback: string,
  ) => {
    const m = byKey(r.metrics, key);
    return (
      <Kpi
        icon={icon}
        label={m?.label ?? fallback}
        value={m ? metricValue(m) : "—"}
        detail={
          m
            ? [m.detail, metricTarget(m)].filter(Boolean).join(" · ") ||
              undefined
            : undefined
        }
        alert={m?.met === false}
      />
    );
  };
  return (
    <TileRow>
      {kpi("detection_to_incident", "time", "Detection → incident")}
      {kpi(
        "detection_to_notification",
        "notifications",
        "Detection → first notification",
      )}
      {kpi("personnel_accounted", "people", "Personnel accounted")}
      <Kpi
        icon="endorsed"
        label="Improvement actions"
        value={`${accepted} / ${total}`}
        detail="Accepted"
      />
    </TileRow>
  );
}

function Metrics({ metrics }: { metrics: Metric[] }) {
  return (
    <table className="nx-table-plain" aria-label="Response metrics">
      <tbody>
        {metrics.map((m) => (
          <tr key={m.key} data-metric={m.key}>
            <td>
              <b>{m.label}</b>
              {m.detail && <div className="nx-dim">{m.detail}</div>}
            </td>
            <td className="nx-mono">{metricValue(m)}</td>
            <td className="nx-dim">{metricTarget(m)}</td>
            <td>
              {m.met === true && <span className="nx-sev ok">MET</span>}
              {m.met === false && <span className="nx-sev high">MISSED</span>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Timeline({ r }: { r: Review }) {
  if (!r.timeline.length)
    return <Empty>Nothing recorded.</Empty>;
  return (
    <ul className="nx-bd nx-aar-timeline" aria-label="Reconstructed timeline">
      {r.timeline.map((t, i) => (
        <li key={`${t.at}-${i}`} data-source={t.source}>
          <span className="nx-mono nx-dim">
            {formatStamp(t.at)} · {t.source.toLowerCase()}
          </span>
          <span>{t.text}</span>
        </li>
      ))}
    </ul>
  );
}

function AcceptForm({ item, onClose }: { item: Item; onClose: () => void }) {
  const [team, setTeam] = useState<Team>(item.owner_team);
  const [due, setDue] = useState(inDays(30));
  const [action, setAction] = useState(item.action);
  const accept = useAccept();
  return (
    <div
      className="nx-aar-form"
      aria-label={`Accept ${item.rule_code ?? "lesson"}`}
    >
      <InputGroup
        aria-label="Action"
        value={action}
        onChange={(e) => setAction(e.currentTarget.value)}
      />
      <HTMLSelect
        aria-label="Owner team"
        value={team}
        onChange={(e) => setTeam(e.currentTarget.value as Team)}
        options={TEAMS.map((t) => ({ value: t, label: teamLabel(t) }))}
      />
      <input
        className="bp6-input"
        type="date"
        aria-label="Due date"
        value={due}
        onChange={(e) => setDue(e.currentTarget.value)}
      />
      <Button
        size="small"
        intent="primary"
        icon="tick"
        text="Confirm"
        loading={accept.isPending}
        disabled={!action.trim() || !due}
        onClick={() =>
          accept.mutate(
            {
              id: item.id,
              body: {
                owner_team: team,
                due_on: due,
                ...(action.trim() !== item.action
                  ? { action: action.trim() }
                  : {}),
              },
            },
            { onSuccess: onClose },
          )
        }
      />
      <Button size="small" text="Cancel" onClick={onClose} />
      {accept.isError && (
        <span className="nx-error">{errorText(accept.error)}</span>
      )}
    </div>
  );
}

function ItemRow({ item, r }: { item: Item; r: Review }) {
  const [mode, setMode] = useState<"idle" | "accept" | "reject">("idle");
  const reject = useReject();
  const done = useDone();
  const open = r.can_act && r.status === "DRAFT" && item.status === "DRAFT";
  return (
    <>
      <tr data-item={item.rule_code ?? "OWN"} data-status={item.status}>
        <td className="nx-aar-finding">{item.finding}</td>
        <td>
          <b>{item.action}</b>
          {item.reason && <div className="nx-dim">Rejected: {item.reason}</div>}
        </td>
        <td>{teamLabel(item.owner_team)}</td>
        <td>
          <span className={`nx-sev ${PRIORITY_SEV[item.priority]}`}>
            {item.priority}
          </span>
        </td>
        <td className="nx-mono">{item.due_on ?? "—"}</td>
        <td className="nx-aar-act">
          {open && mode === "idle" ? (
            <>
              <Button
                size="small"
                intent="primary"
                text="Accept"
                onClick={() => setMode("accept")}
              />
              <Button
                size="small"
                text="Reject"
                onClick={() => setMode("reject")}
              />
            </>
          ) : item.status === "ACCEPTED" && r.can_act ? (
            <Button
              size="small"
              icon="tick-circle"
              text="Done"
              loading={done.isPending}
              onClick={() => done.mutate(item.id)}
            />
          ) : (
            <span className={`nx-sev ${STATUS_SEV[item.status] ?? "low"}`}>
              {item.status}
            </span>
          )}
        </td>
      </tr>
      {mode !== "idle" && (
        <tr className="nx-aar-decide">
          <td colSpan={6}>
            {mode === "accept" ? (
              <AcceptForm item={item} onClose={() => setMode("idle")} />
            ) : (
              <div className="nx-aar-form" aria-label="Reject reason">
                <span className="nx-dim">Reason:</span>
                {REJECT_REASONS.map((reason) => (
                  <Button
                    key={reason}
                    size="small"
                    text={reason}
                    onClick={() =>
                      reject.mutate(
                        { id: item.id, reason },
                        { onSuccess: () => setMode("idle") },
                      )
                    }
                  />
                ))}
                <Button
                  size="small"
                  text="Cancel"
                  onClick={() => setMode("idle")}
                />
                {reject.isError && (
                  <span className="nx-error">{errorText(reject.error)}</span>
                )}
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

function AddForm({ r, onClose }: { r: Review; onClose: () => void }) {
  const [finding, setFinding] = useState("");
  const [action, setAction] = useState("");
  const [team, setTeam] = useState<Team>("SECURITY");
  const [priority, setPriority] = useState<Priority>("MEDIUM");
  const [due, setDue] = useState(inDays(30));
  const add = useAddItem();
  return (
    <div className="nx-bd nx-aar-form" aria-label="Add a lesson">
      <InputGroup
        aria-label="Finding"
        placeholder="What happened"
        value={finding}
        onChange={(e) => setFinding(e.currentTarget.value)}
      />
      <InputGroup
        aria-label="New action"
        placeholder="What to change"
        value={action}
        onChange={(e) => setAction(e.currentTarget.value)}
      />
      <HTMLSelect
        aria-label="Team"
        value={team}
        onChange={(e) => setTeam(e.currentTarget.value as Team)}
        options={TEAMS.map((t) => ({ value: t, label: teamLabel(t) }))}
      />
      <HTMLSelect
        aria-label="Priority"
        value={priority}
        onChange={(e) => setPriority(e.currentTarget.value as Priority)}
        options={["HIGH", "MEDIUM", "LOW"]}
      />
      <input
        className="bp6-input"
        type="date"
        aria-label="Due"
        value={due}
        onChange={(e) => setDue(e.currentTarget.value)}
      />
      <Button
        size="small"
        intent="primary"
        text="Add"
        disabled={!finding.trim() || !action.trim() || !due}
        loading={add.isPending}
        onClick={() =>
          add.mutate(
            {
              reviewId: r.id,
              body: {
                finding: finding.trim(),
                action: action.trim(),
                owner_team: team,
                priority,
                due_on: due,
              },
            },
            { onSuccess: onClose },
          )
        }
      />
      <Button size="small" text="Cancel" onClick={onClose} />
      {add.isError && <span className="nx-error">{errorText(add.error)}</span>}
    </div>
  );
}

function Lessons({ r }: { r: Review }) {
  const [adding, setAdding] = useState(false);
  return (
    <Card
      icon="lightbulb"
      title="Lessons & actions"
      sub={r.label}
      actions={
        r.can_act &&
        r.status === "DRAFT" &&
        !adding && (
          <Button
            size="small"
            icon="add"
            text="Add lesson"
            onClick={() => setAdding(true)}
          />
        )
      }
    >
      {adding && <AddForm r={r} onClose={() => setAdding(false)} />}
      {r.items.length ? (
        <table
          className="nx-table-plain nx-aar-items"
          aria-label="Lessons and actions"
        >
          <thead>
            <tr>
              <th>Finding</th>
              <th>Action</th>
              <th>Team</th>
              <th>Priority</th>
              <th>Due</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {r.items.map((item) => (
              <ItemRow key={item.id} item={item} r={r} />
            ))}
          </tbody>
        </table>
      ) : (
        <Empty>The record shows nothing to draft. Add a lesson of your own.</Empty>
      )}
    </Card>
  );
}

function ReviewView({ r }: { r: Review }) {
  const navigate = useNavigate();
  const finalise = useFinalise();
  const drafts = r.items.filter((i) => i.status === "DRAFT").length;
  return (
    <div className="nx-col">
      <div
        className={`nx-banner${r.status === "FINAL" ? " green" : ""}`}
        role="note"
      >
        <Icon icon="endorsed" />
        <div className="nx-grow">
          <b>
            After-action review {r.reference} · {r.incident_reference} ·{" "}
            {r.incident_title}.
          </b>{" "}
          <ExerciseTag on={r.exercise} />{" "}
          {r.status === "FINAL"
            ? `Final since ${formatStamp(r.finalised_at ?? r.started_at)}: the metrics are frozen.`
            : "Built from the platform record; the metrics stay live until the review is finalised."}{" "}
          Simulated data.
        </div>
        <Button
          icon="play"
          text="Replay"
          onClick={() => void navigate(`/incidents/replay?id=${r.incident_id}`)}
        />
        <Button
          icon="document-share"
          text="Export review"
          onClick={() => void navigate(`/aar/${r.id}/print`)}
        />
        {r.can_finalise && (
          <Button
            intent="primary"
            icon="lock"
            text="Finalise"
            disabled={drafts > 0}
            title={
              drafts > 0
                ? `${drafts} draft${drafts === 1 ? "" : "s"} still to be decided`
                : undefined
            }
            loading={finalise.isPending}
            onClick={() => finalise.mutate(r.id)}
          />
        )}
      </div>
      {finalise.isError && (
        <div className="nx-error">{errorText(finalise.error)}</div>
      )}
      <Figures r={r} />
      <div className="nx-ev-grid">
        <div className="nx-col">
          <Lessons r={r} />
          <Card
            icon="dashboard"
            title="Response metrics"
            sub="From the record · targets as requirements §5"
          >
            <Metrics metrics={r.metrics} />
          </Card>
        </div>
        <Card
          icon="time"
          title="Reconstructed timeline"
          sub="Roles and references, no names"
        >
          <Timeline r={r} />
        </Card>
      </div>
    </div>
  );
}

/** After-Action Review (AAR-08; D-47): the reviews, incidents ready for one, and the selected
 * review. Every role reads; the buttons follow can_act and can_finalise from the backend. */
export function AarScreen() {
  const list = useReviews();
  const [params, setParams] = useSearchParams();
  const start = useStartReview();
  const selected = params.get("review") ?? list.data?.reviews[0]?.id;
  const review = useReview(selected);
  if (list.isError)
    return (
      <NonIdealState icon="error" title="The reviews could not be loaded" />
    );
  const data = list.data;
  return (
    <div className="nx-pad nx-aar">
      <div className="nx-col nx-aar-side">
        <Card icon="endorsed" title="Reviews">
          {!data ? (
            <SkeletonRows rows={3} />
          ) : data.reviews.length ? (
            <ul className="nx-aar-list" aria-label="Reviews">
              {data.reviews.map((s) => (
                <li
                  key={s.id}
                  className={s.id === selected ? "sel" : undefined}
                  data-review={s.reference}
                  onClick={() => setParams({ review: s.id })}
                >
                  <div className="nx-row">
                    <b>{s.reference}</b>
                    <ExerciseTag on={s.exercise} />
                    <span className="nx-grow" />
                    <span
                      className={`nx-sev ${s.status === "FINAL" ? "ok" : "med"}`}
                    >
                      {s.status}
                    </span>
                  </div>
                  <div className="nx-dim">
                    {s.incident_reference} · {s.incident_title} · {s.accepted}/
                    {s.items} accepted
                    {s.drafts ? ` · ${s.drafts} to decide` : ""}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <Empty>No review yet.</Empty>
          )}
        </Card>
        <Card icon="inbox" title="Ready for review" sub="Monitoring or closed">
          {data?.ready.length ? (
            <ul className="nx-aar-list" aria-label="Ready for review">
              {data.ready.map((r) => (
                <li key={r.incident_id} data-incident={r.reference}>
                  <div className="nx-row">
                    <b>{r.reference}</b>
                    <ExerciseTag on={r.exercise} />
                    <span className="nx-dim">{r.status}</span>
                    <span className="nx-grow" />
                    {r.can_start && (
                      <Button
                        size="small"
                        intent="primary"
                        text="Start review"
                        loading={
                          start.isPending && start.variables === r.incident_id
                        }
                        onClick={() =>
                          start.mutate(r.incident_id, {
                            onSuccess: (created) =>
                              setParams({ review: created.id }),
                          })
                        }
                      />
                    )}
                  </div>
                  <div className="nx-dim">{r.title}</div>
                </li>
              ))}
            </ul>
          ) : (
            data && <Empty>No incident to review yet.</Empty>
          )}
          {start.isError && (
            <div className="nx-bd nx-error">{errorText(start.error)}</div>
          )}
        </Card>
      </div>
      <div className="nx-aar-main">
        {!data ? (
          <SkeletonRows rows={10} />
        ) : !selected ? (
          <NonIdealState
            icon="endorsed"
            title="No incident to review yet"
            description="A review is built from the platform record once an incident is at Monitoring or Closed."
          />
        ) : review.isError ? (
          <NonIdealState icon="error" title="The review could not be loaded" />
        ) : review.data ? (
          <ReviewView r={review.data} />
        ) : (
          <SkeletonRows rows={10} />
        )}
      </div>
    </div>
  );
}
