import { Button, HTMLSelect, InputGroup, NonIdealState } from "@blueprintjs/core";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { ApiError } from "../../api/client";
import {
  DIMENSION_LABEL,
  type Exercise,
  type ExerciseSummary,
  type Kind,
  KINDS,
  kindLabel,
  type Kpis,
  LOW_SCORE,
  type Template,
  useAbandon,
  useEnd,
  useExercise,
  useExercises,
  useLaunch,
  useNextInject,
  useTemplates,
} from "../../api/exercises";
import { formatDate, formatStamp } from "../../app/time";
import { Card, Kpi } from "../../ui/primitives";
import { SkeletonRows } from "../../ui/Skeleton";
import { measuredText } from "./format";
import { TileRow } from "../../ui/TileRow";
import { Empty } from "../../ui/Empty";

// EXR-08 (plan-pilot-exr §8): the KPIs, the recent exercises, Run an exercise and the scoring
// breakdown, as the design. Launch, Next inject, End and Abandon show only to those the API
// says may act (can_launch, can_act); the backend checks each through approvals.py.

const INTRO =
  "Exercises use the same scenario engine as the live platform. Injects arrive as simulated alerts; responses are timed and scored.";

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong";
}

function ScoreBar({ score, width }: { score: number | null; width?: number }) {
  return (
    <span className="nx-bar" style={{ width: width ?? "100%" }}>
      <i
        className={score !== null && score < LOW_SCORE ? "warn" : undefined}
        style={{ width: `${score ?? 0}%` }}
      />
    </span>
  );
}

function Figures({ k, templates }: { k: Kpis; templates: Template[] }) {
  const year = new Date().getFullYear();
  const share = k.personnel ? Math.round((100 * k.took_part) / k.personnel) : null;
  const delta =
    k.average !== null && k.average_last_year !== null ? k.average - k.average_last_year : null;
  const themes = [...new Set(templates.map((t) => t.theme).filter(Boolean))];
  return (
    <TileRow label="Exercise figures">
      <Kpi icon="locate" label={`Exercises · ${year}`} value={k.this_year} detail="Completed this year" />
      <Kpi
        icon="chart"
        label="Average score"
        value={k.average === null ? "—" : `${k.average} / 100`}
        detail={
          delta === null
            ? `— vs ${year - 1}`
            : `${delta >= 0 ? "▲" : "▼"} ${Math.abs(delta)} vs ${year - 1}`
        }
        alert={k.average !== null && k.average < LOW_SCORE}
      />
      <Kpi
        icon="people"
        label="Staff who took part"
        value={k.took_part.toLocaleString("en-GB")}
        detail={share === null ? "Last 12 months" : `${share}% of personnel · last 12 months`}
      />
      <Kpi
        icon="layers"
        label="Scenario templates"
        value={k.templates}
        detail={themes.join(" · ") || undefined}
      />
    </TileRow>
  );
}

function Recent({
  rows,
  selected,
  onSelect,
}: {
  rows: ExerciseSummary[];
  selected: string | undefined;
  onSelect: (id: string) => void;
}) {
  if (!rows.length) return <Empty>No exercise yet.</Empty>;
  return (
    <table className="nx-table-plain" aria-label="Recent exercises">
      <thead>
        <tr>
          <th>Scenario</th>
          <th>Mission</th>
          <th>Type</th>
          <th>Date</th>
          <th>Score</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((e) => (
          <tr
            key={e.id}
            data-exercise={e.id}
            className={`click${e.id === selected ? " sel" : ""}`}
            onClick={() => onSelect(e.id)}
          >
            <td>
              <b>{e.name}</b>{" "}
              {e.status === "RUNNING" && <span className="nx-sev crit">RUNNING</span>}
              {e.status === "ABANDONED" && <span className="nx-sev nt">ABANDONED</span>}
              {e.source === "ILLUSTRATIVE" && <span className="nx-sev nt">Illustrative</span>}
            </td>
            <td>{e.mission_code}</td>
            <td>{kindLabel(e.kind)}</td>
            <td className="nx-mono nx-dim nx-nowrap">
              {formatDate(e.ended_at ?? e.started_at)}
            </td>
            <td>
              {e.overall_score === null ? (
                <span className="nx-dim">—</span>
              ) : (
                <span className="nx-row nx-exr-score">
                  <ScoreBar score={e.overall_score} width={60} />
                  <span className="nx-mono">{e.overall_score}</span>
                </span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Launch({ templates, onLaunched }: { templates: Template[]; onLaunched: (id: string) => void }) {
  const open = templates.filter((t) => t.can_launch && !t.running);
  const [code, setCode] = useState<string>("");
  const [kind, setKind] = useState<Kind>("FUNCTIONAL");
  const launch = useLaunch();
  if (!templates.some((t) => t.can_launch)) return null;
  if (!open.length)
    return <div className="nx-dim">Every template's mission has an exercise running.</div>;
  const chosen = open.find((t) => t.code === code) ?? open[0];
  return (
    <div className="nx-row nx-exr-launch" aria-label="Launch an exercise">
      <HTMLSelect
        aria-label="Template"
        value={chosen?.code}
        onChange={(e) => setCode(e.currentTarget.value)}
        options={open.map((t) => ({ value: t.code, label: `${t.name} · ${t.mission_code} · ${t.theme}` }))}
      />
      <HTMLSelect
        aria-label="Kind"
        value={kind}
        onChange={(e) => setKind(e.currentTarget.value as Kind)}
        options={KINDS.map((k) => ({ value: k, label: kindLabel(k) }))}
      />
      <Button
        intent="danger"
        icon="play"
        text="Launch"
        loading={launch.isPending}
        disabled={!chosen}
        onClick={() =>
          chosen &&
          launch.mutate({ template: chosen.code, kind }, { onSuccess: (x) => onLaunched(x.id) })
        }
      />
      {launch.isError && <span className="nx-error">{errorText(launch.error)}</span>}
    </div>
  );
}

function Controls({ x }: { x: Exercise }) {
  const next = useNextInject();
  const end = useEnd();
  const abandon = useAbandon();
  const [reason, setReason] = useState<string | null>(null);
  const run = x.run;
  const scene = run?.scenes.find((s) => s.scene_no === run.current_scene);
  const last = run ? Math.max(...run.scenes.map((s) => s.scene_no)) : 0;
  const error = [next, end, abandon].find((m) => m.isError)?.error;
  return (
    <div className="nx-col" aria-label="Running exercise">
      <div className="nx-row">
        <span className="nx-sev crit">RUNNING</span>
        <b>
          {x.name} · {x.mission_code}
        </b>
      </div>
      {run && (
        <div className="nx-dim" aria-label="Current scene">
          Scene {run.current_scene} of {last}
          {scene?.name ? ` · ${scene.name}` : ""}
          {run.status === "PLAYING" ? " · injects arriving" : ""}
        </div>
      )}
      {x.can_act && (
        <div className="nx-row">
          <Button
            icon="step-forward"
            text="Next inject"
            loading={next.isPending}
            disabled={!run || run.status === "FINISHED" || run.current_scene >= last}
            onClick={() => next.mutate(x.id)}
          />
          <Button
            intent="primary"
            icon="stop"
            text="End exercise"
            loading={end.isPending}
            onClick={() => end.mutate(x.id)}
          />
          <Button icon="cross" text="Abandon" onClick={() => setReason("")} />
        </div>
      )}
      {x.can_act && reason !== null && (
        <div className="nx-row" aria-label="Abandon the exercise">
          <InputGroup
            aria-label="Reason"
            placeholder="Why it is called off"
            value={reason}
            onChange={(e) => setReason(e.currentTarget.value)}
          />
          <Button
            size="small"
            intent="danger"
            text="Confirm"
            loading={abandon.isPending}
            disabled={!reason.trim()}
            onClick={() =>
              abandon.mutate({ id: x.id, reason: reason.trim() }, { onSuccess: () => setReason(null) })
            }
          />
          <Button size="small" text="Cancel" onClick={() => setReason(null)} />
        </div>
      )}
      {error !== undefined && <span className="nx-error">{errorText(error)}</span>}
    </div>
  );
}

function Breakdown({ x }: { x: Exercise }) {
  if (x.status === "RUNNING")
    return <div className="nx-bd nx-dim">Scored from the record when the exercise ends.</div>;
  if (x.status === "ABANDONED")
    return (
      <div className="nx-bd nx-dim">
        Abandoned{x.reason ? `: ${x.reason}` : ""}. Not scored.
      </div>
    );
  return (
    <div className="nx-bd nx-col" aria-label="Scoring breakdown">
      {x.scores.map((s) => (
        <div key={s.dimension} data-dimension={s.dimension}>
          <div className="nx-row nx-exr-dim">
            <span className="nx-grow">{DIMENSION_LABEL[s.dimension]}</span>
            <span className="nx-mono">{s.score ?? "—"}</span>
          </div>
          <ScoreBar score={s.score} />
          <div className="nx-dim">
            {measuredText(s)}
            {s.dimension === "COMMUNICATION" && s.measured.simulated_delivery === true
              ? " · simulated delivery"
              : ""}
          </div>
        </div>
      ))}
      <div className="nx-row nx-exr-dim" data-dimension="OVERALL">
        <b className="nx-grow">Overall</b>
        <b className="nx-mono">{x.overall_score ?? "—"}</b>
      </div>
      <div className="nx-dim">
        {x.source === "ILLUSTRATIVE"
          ? "Illustrative: seeded history, not a recorded exercise."
          : `${x.incident_reference ?? "No incident"} · ${x.participants ?? 0} took part · frozen ${formatStamp(x.ended_at ?? x.started_at)}`}
        {/* RPL-06 (D-51): the exercise's incident, played back. */}
        {x.incident_id && (
          <>
            {" · "}
            <Link to={`/incidents/replay?id=${x.incident_id}`}>Replay</Link>
          </>
        )}
      </div>
    </div>
  );
}

export function ExercisesScreen() {
  const list = useExercises();
  const templates = useTemplates();
  const [params, setParams] = useSearchParams();
  const rows = list.data?.exercises ?? [];
  const selected = params.get("exercise") ?? rows[0]?.id;
  const exercise = useExercise(selected);
  const running = rows.find((e) => e.status === "RUNNING" && e.id === selected) ?? rows.find((e) => e.status === "RUNNING");
  const active = useExercise(running?.id);
  const select = (id: string) => setParams({ exercise: id });
  if (list.isError) return <NonIdealState icon="error" title="The exercises could not be loaded" />;
  return (
    <div className="nx-pad">
      {list.data ? (
        <Figures k={list.data.kpis} templates={templates.data ?? []} />
      ) : (
        <SkeletonRows rows={2} />
      )}
      <div className="nx-exr">
        <Card icon="locate" title="Recent exercises">
          {list.data ? (
            <Recent rows={rows} selected={selected} onSelect={select} />
          ) : (
            <SkeletonRows rows={6} />
          )}
        </Card>
        <div className="nx-col">
          <Card icon="flash" title="Run an exercise">
            <div className="nx-bd nx-col">
              <div className="nx-dim">{INTRO}</div>
              {active.data?.status === "RUNNING" && <Controls x={active.data} />}
              <Launch templates={templates.data ?? []} onLaunched={select} />
            </div>
          </Card>
          <Card
            icon="chart"
            title={`Scoring breakdown${exercise.data ? ` · ${exercise.data.name}` : ""}`}
            sub={exercise.data ? `${exercise.data.mission_code} · ${kindLabel(exercise.data.kind)}` : undefined}
          >
            {exercise.data ? (
              <Breakdown x={exercise.data} />
            ) : selected ? (
              <SkeletonRows rows={5} />
            ) : (
              <Empty>No exercise yet.</Empty>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
