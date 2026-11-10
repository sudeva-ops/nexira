import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { useOperationsSummary } from "../api/intel";
import { useMissions } from "../api/people";
import { useAgents, usePendingCount } from "../api/proposals";
import { IntroGlobe } from "../map/IntroGlobe";
import { CountUp } from "../ui/motion";
import { useReducedMotion } from "../ui/useMotion";
import { automatedBrowser, INTRO_MS, introPlayed, introTarget, markIntroPlayed, shouldPlayIntro } from "./introRules";

const TYPE_MS = 28; // per character of the status line

function Typed({ text, startMs }: { text: string; startMs: number }) {
  const [shown, setShown] = useState(0);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = (n: number) => {
      setShown(n);
      if (n < text.length) timer = setTimeout(() => tick(n + 1), TYPE_MS);
    };
    timer = setTimeout(() => tick(1), startMs);
    return () => clearTimeout(timer);
  }, [text, startMs]);
  return (
    <span aria-label={text}>
      {text.slice(0, shown)}
      <span className="nx-intro-caret" aria-hidden="true" />
    </span>
  );
}

function Playing({ onDone }: { onDone: () => void }) {
  const missions = useMissions().data ?? [];
  const summary = useOperationsSummary().data;
  const agents = useAgents().data?.agents.length ?? 0;
  const pending = usePendingCount();
  const [phase, setPhase] = useState<"spin" | "descend" | "fade">("spin");
  const done = useRef(onDone);
  useEffect(() => {
    done.current = onDone;
  });

  useEffect(() => {
    const timers = [
      setTimeout(() => setPhase("descend"), INTRO_MS.zoom),
      setTimeout(() => setPhase("fade"), INTRO_MS.fade),
      setTimeout(() => done.current(), INTRO_MS.done),
    ];
    const skip = () => done.current();
    window.addEventListener("keydown", skip);
    return () => {
      timers.forEach(clearTimeout);
      window.removeEventListener("keydown", skip);
    };
  }, []);

  const incidents = summary?.incidents_active ?? 0;
  const status = summary
    ? [
        `${missions.length || summary.missions} missions monitored`,
        incidents ? `${incidents} active incident${incidents === 1 ? "" : "s"}` : "no active incidents",
        `${pending} decision${pending === 1 ? "" : "s"} waiting`,
        "agents on watch",
      ].join(" · ")
    : "Connecting to the operations picture";

  return (
    <div
      className={`nx-intro${phase === "fade" ? " out" : ""}`}
      role="dialog"
      aria-modal="true"
      aria-label="NEXIRA"
      onClick={() => done.current()}
    >
      <IntroGlobe missions={missions} descend={phase !== "spin"} />
      <div className="nx-intro-veil" aria-hidden="true" />
      <div className={`nx-intro-copy${phase === "spin" ? "" : " away"}`}>
        <div className="nx-intro-mark">
          <svg viewBox="0 0 40 40" aria-hidden="true">
            <circle cx="20" cy="20" r="15" fill="none" stroke="#4C90F0" strokeWidth="4" />
            <circle cx="20" cy="20" r="6" fill="#4C90F0" />
          </svg>
          <h1>NEXIRA</h1>
        </div>
        <p className="nx-intro-tagline">Sovereign resilience for people and missions abroad</p>
        <dl className="nx-intro-counts" aria-label="Monitored now">
          <div>
            <dd>
              <CountUp value={missions.length} ms={1_400} />
            </dd>
            <dt>Missions</dt>
          </div>
          <div>
            <dd>
              <CountUp value={summary?.personnel ?? 0} ms={1_600} />
            </dd>
            <dt>Personnel</dt>
          </div>
          <div>
            <dd>
              <CountUp value={summary?.travellers_active ?? 0} ms={1_200} />
            </dd>
            <dt>Travellers in transit</dt>
          </div>
          <div>
            <dd>
              <CountUp value={agents} ms={1_000} />
            </dd>
            <dt>Agents</dt>
          </div>
        </dl>
        <p className="nx-intro-status">
          <Typed text={status} startMs={1_300} />
        </p>
      </div>
      <div className="nx-intro-skip" aria-hidden="true">
        Simulated data · press any key to skip
      </div>
    </div>
  );
}

/** Plays once per sign-in, then hands over to Global Operations (or the page asked for). */
export function Intro() {
  const reduced = useReducedMotion();
  const [playing, setPlaying] = useState(() =>
    shouldPlayIntro({ reduced, automated: automatedBrowser(), played: introPlayed() }),
  );
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const from = useRef(pathname);
  useEffect(() => {
    if (playing) markIntroPlayed();
  }, [playing]);
  if (!playing) return null;
  return (
    <Playing
      onDone={() => {
        const target = introTarget(from.current);
        if (target) navigate(target, { replace: true });
        setPlaying(false);
      }}
    />
  );
}
