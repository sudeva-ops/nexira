import { Button, ButtonGroup, NonIdealState, Spinner } from "@blueprintjs/core";
import { type CSSProperties, lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { type Replay, useReplay } from "../../api/replay";
import { Card, ExerciseTag, Kpi, Sev } from "../../ui/primitives";
import { useReducedMotion } from "../../ui/useMotion";
import { axis, bounds, elapsed, entryAt, rate, SPEEDS, STATE_COLOUR, stateAt, step, toPlay, toRecord } from "./state";
import { SkeletonRows } from "../../ui/Skeleton";
import { plural } from "../../ui/format";

// MapLibre is most of the bundle; load it only with this screen.
const ReplayMap = lazy(() => import("../../map/ReplayMap").then((m) => ({ default: m.ReplayMap })));

// Incident Replay (RPL-02, RPL-03, RPL-06, RPL-07; D-51; plan-pilot-rpl §3): the incident played
// back from its record. The map, the figures and the timeline all show the same moment t.

const STEP_MS = 2000; // reduced motion or Calm: one entry every two seconds
const SOURCE_COLOUR: Record<string, string> = {
  INCIDENT: "#E76A6E",
  PLAYBOOK: "#4C90F0",
  CHECKIN: "#32A467",
  NOTIFICATION: "#8ABBFF",
  AGENT: "#BDADFF",
  DECISION: "#FBB360",
  STATUS: "#ABB3BF",
  FLEET: "#2EE6D6",
  SITE: "#F5498B",
  SUPPLY: "#D1980B",
  ANNOTATION: "#FBD065",
};

const clock = (iso: string) => new Date(iso).toISOString().slice(11, 19);

function Player({ replay, initial }: { replay: Replay; initial: number | null }) {
  const { start, end } = bounds(replay);
  const [, setParams] = useSearchParams();
  const reduced = useReducedMotion();
  const [t, setT] = useState(() => (initial === null ? start : Math.min(end, start + initial * 1000)));
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<number>(1);
  const tRef = useRef(t); // the loops read the moment without restarting on each frame
  const move = useCallback((next: number) => {
    tRef.current = next;
    setT(next);
  }, []);
  const play = useMemo(() => axis(replay), [replay]);
  const moment = useMemo(() => stateAt(replay, t), [replay, t]);
  const current = entryAt(replay, t);
  const list = useRef<HTMLDivElement>(null);

  // RPL-07: the moment goes in the address while paused, replacing it (no history entry each step).
  useEffect(() => {
    if (playing) return;
    setParams(
      (p) => {
        const next = new URLSearchParams(p);
        next.set("t", String(Math.round((t - start) / 1000)));
        return next;
      },
      { replace: true },
    );
  }, [playing, t, start, setParams]);

  useEffect(() => {
    if (!playing) return undefined;
    if (reduced) {
      const timer = window.setInterval(() => {
        const next = step(replay, tRef.current, 1);
        move(next);
        if (next >= end) setPlaying(false);
      }, STEP_MS);
      return () => window.clearInterval(timer);
    }
    let frame = 0;
    let last = performance.now();
    const per = rate(play, speed);
    const tick = (now: number) => {
      const next = Math.min(end, toRecord(play, toPlay(play, tRef.current) + (now - last) * per));
      last = now;
      move(next);
      if (next >= end) setPlaying(false);
      else frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, reduced, speed, replay, play, end, move]);

  useEffect(() => {
    list.current?.querySelector(".current")?.scrollIntoView?.({ block: "nearest" });
  }, [current]);

  const toggle = useCallback(() => {
    setPlaying((p) => {
      if (!p && tRef.current >= end) move(start); // play again from the start
      return !p;
    });
  }, [start, end, move]);
  const jump = (to: number) => {
    setPlaying(false);
    move(Math.max(start, Math.min(end, to)));
  };

  const pct = (p: number) => `${(p / play.total) * 100}%`;
  const tally = moment.tally;
  return (
    <div
      className="nx-rpl"
      tabIndex={-1}
      onKeyDown={(e) => {
        if (e.key === " ") {
          e.preventDefault();
          toggle();
        } else if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
          e.preventDefault();
          jump(step(replay, t, e.key === "ArrowRight" ? 1 : -1));
        }
      }}
    >
      <div className="nx-card nx-mapwrap nx-rpl-map">
        <Suspense fallback={<Spinner className="nx-map-loading" />}>
          <ReplayMap replay={replay} moment={moment} />
        </Suspense>
        <div className="nx-legend">
          <span className="nx-chip"><i style={{ background: STATE_COLOUR.NOT_ASKED }} />Not asked</span>
          <span className="nx-chip"><i style={{ background: STATE_COLOUR.WAITING }} />Waiting</span>
          <span className="nx-chip"><i style={{ background: STATE_COLOUR.SAFE }} />Safe</span>
          <span className="nx-chip"><i style={{ background: STATE_COLOUR.NEED_HELP }} />Needs help</span>
          <span className="nx-chip"><i style={{ background: "#4C90F0" }} />Site</span>
        </div>
      </div>

      <div className="nx-rpl-side">
        <div className="nx-rpl-kpis">
          <Kpi icon="time" label="Since first signal" value={<span>{elapsed(moment.elapsedMs)}</span>} />
          <Kpi icon="feed" label="Signals" value={<span>{moment.signals.length}</span>} />
          <Kpi icon="people" label="People exposed" value={<span>{moment.exposed}</span>} detail={replay.trips ? `${replay.trips} trips` : undefined} />
          <Kpi
            icon="endorsed"
            label="Check-in · personnel"
            value={<span>{tally ? `${tally.safe} / ${tally.need_help} / ${tally.pending}` : "—"}</span>}
            detail={tally ? "safe / needs help / waiting" : "not sent yet"}
            alert={(tally?.need_help ?? 0) > 0}
          />
        </div>
        <Card icon="timeline-events" title="Timeline" chip={{ text: plural(replay.timeline.length, "entry", "entries") }} className="nx-rpl-tl">
          <div className="nx-bd nx-tl" ref={list} aria-label="Replay timeline">
            {replay.timeline.map((e, i) => (
              <div
                key={`${e.at}-${i}`}
                className={[i === current && "current", Date.parse(e.at) > t && "ahead"].filter(Boolean).join(" ") || undefined}
                style={{ "--c": SOURCE_COLOUR[e.source] ?? "#4c90f0" } as CSSProperties}
              >
                <button type="button" className="nx-rpl-entry" onClick={() => jump(Date.parse(e.at))}>
                  <span>{clock(e.at)}</span>
                  {e.text}
                </button>
                {e.site_id && e.sensor && (
                  <Link
                    className="nx-rpl-camera"
                    to={`/twin?${new URLSearchParams({ site: e.site_id, camera: e.sensor }).toString()}`}
                  >
                    View camera
                  </Link>
                )}
              </div>
            ))}
          </div>
        </Card>
      </div>

      <div className="nx-card nx-rpl-bar">
        <ButtonGroup>
          <Button icon="step-backward" aria-label="Previous entry" onClick={() => jump(step(replay, t, -1))} />
          <Button
            icon={playing ? "pause" : "play"}
            intent="primary"
            aria-label={playing ? "Pause replay" : "Play replay"}
            onClick={toggle}
          />
          <Button icon="step-forward" aria-label="Next entry" onClick={() => jump(step(replay, t, 1))} />
        </ButtonGroup>
        <div className="nx-rpl-track">
          {replay.timeline.map((e, i) => (
            <i
              key={`${e.at}-${i}`}
              className="nx-rpl-mark"
              style={{ left: pct(toPlay(play, Date.parse(e.at))), background: SOURCE_COLOUR[e.source] ?? "#4c90f0" }}
              title={e.text}
              aria-hidden="true"
            />
          ))}
          {play.breaks.map((b) => (
            <i
              key={b.from}
              className="nx-rpl-quiet"
              style={{ left: pct(b.from), width: pct(b.to - b.from) }}
              title={`Quiet for ${elapsed(b.quietMs).slice(1)}; shortened`}
              aria-hidden="true"
            />
          ))}
          <input
            type="range"
            aria-label="Moment"
            min={0}
            max={play.total}
            step={Math.max(1, Math.round(play.total / 1000))}
            value={toPlay(play, t)}
            onChange={(e) => jump(toRecord(play, Number(e.target.value)))}
          />
        </div>
        <span className="nx-rpl-time" aria-label="Elapsed">{elapsed(moment.elapsedMs)}</span>
        <ButtonGroup aria-label="Speed">
          {SPEEDS.map((s) => (
            <Button key={s} small text={`${s}×`} active={speed === s} onClick={() => setSpeed(s)} />
          ))}
        </ButtonGroup>
      </div>
    </div>
  );
}

/** RPL-06: opened from Incidents, After-Action Review and Exercise & Training. */
export function ReplayScreen() {
  const [params] = useSearchParams();
  const id = params.get("id");
  const raw = params.get("t");
  const initial = raw !== null && /^\d+$/.test(raw) ? Number(raw) : null;
  const replay = useReplay(id);
  const [initialT] = useState(initial); // read once: the player writes t back as it moves
  if (!id) return <NonIdealState icon="play" title="No incident chosen" description={<Link to="/incidents">Choose an incident</Link>} />;
  if (replay.isError) return <NonIdealState icon="error" title="The replay could not be loaded" />;
  if (!replay.data) return <SkeletonRows rows={8} />;
  const r = replay.data;
  return (
    <div className="nx-rpl-page">
      <div className="nx-rpl-head">
        <Sev severity={r.incident.severity} />
        <b>{r.incident.reference}</b>
        <span>{r.incident.title}</span>
        <ExerciseTag on={r.incident.exercise} />
        <span className="nx-grow" />
        <span className="nx-dim">Positions as now; the platform keeps no location history</span>
        <Button
          small
          icon="refresh"
          text="Refresh"
          loading={replay.isFetching}
          onClick={() => void replay.refetch()}
        />
        <Link to={`/incidents?id=${r.incident.id}`}>Open incident</Link>
      </div>
      <Player key={r.incident.id} replay={r} initial={initialT} />
    </div>
  );
}
