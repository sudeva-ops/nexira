import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { useOperationsSummary } from "../api/intel";
import { useMissions } from "../api/people";
import { useAgents, usePendingCount } from "../api/proposals";
import { type GlobeFrame, IntroGlobe } from "../map/IntroGlobe";
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

/** "015°E · 12°N", the globe's centre as it turns. */
function bearingText(lon: number, lat: number): string {
  const wrap = ((((lon + 180) % 360) + 360) % 360) - 180;
  const deg = (v: number, pad: number) => String(Math.abs(Math.round(v))).padStart(pad, "0");
  return `${deg(wrap, 3)}°${wrap < 0 ? "W" : "E"} · ${deg(lat, 2)}°${lat < 0 ? "S" : "N"}`;
}

const RING_GAP = 26; // between the globe's edge and the compass ring, in CSS pixels

/** A thin bezel round the globe: a tick every 10° of longitude, a label every 30°, turning with
 * the globe so the meridian under the top marker is the one facing you. */
function CompassRing({ frame, lon, away }: { frame: GlobeFrame; lon: number; away: boolean }) {
  const size = 2 * (frame.r + RING_GAP);
  const ticks = Array.from({ length: 36 }, (_, i) => i * 10 - 180);
  return (
    <svg
      className={`nx-intro-ring${away ? " away" : ""}`}
      viewBox="-100 -100 200 200"
      style={{ left: frame.x - size / 2, top: frame.y - size / 2, width: size, height: size }}
      aria-hidden="true"
    >
      <circle r="97" />
      <path className="mark" d="M0,-93 L-2.4,-99 L2.4,-99 Z" />
      <g transform={`rotate(${-lon})`}>
        {ticks.map((t) => (
          <g key={t} transform={`rotate(${t})`}>
            <line y1="-97" y2={t % 30 ? -95.4 : -93.6} />
            {t % 30 === 0 && (
              <text y="-89.6">{t === 0 || t === -180 ? `${Math.abs(t)}°` : `${Math.abs(t)}°${t < 0 ? "W" : "E"}`}</text>
            )}
          </g>
        ))}
      </g>
    </svg>
  );
}

function Playing({ onDone }: { onDone: () => void }) {
  const [centre, setCentre] = useState("020°E · 15°N");
  const [lon, setLon] = useState(20);
  const [frame, setFrame] = useState<GlobeFrame | null>(null);
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
      <div className={`nx-intro-halo${phase === "spin" ? "" : " centred"}`} aria-hidden="true" />
      <IntroGlobe
        missions={missions}
        descend={phase !== "spin"}
        onTurn={(at, lat) => {
          setLon(at);
          setCentre(bearingText(at, lat));
        }}
        onFrame={setFrame}
      />
      {frame && <CompassRing frame={frame} lon={lon} away={phase !== "spin"} />}
      <div className="nx-intro-veil" aria-hidden="true" />
      <div className={`nx-intro-hud${phase === "spin" ? "" : " away"}`} aria-hidden="true">
        <i className="tl" />
        <i className="tr" />
        <i className="bl" />
        <i className="br" />
        <span className="nx-intro-hud-top">Secure session · in-country · simulated data</span>
        <span className="nx-intro-hud-scan">
          Global scan <b>{centre}</b>
        </span>
      </div>
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
      <div className="nx-intro-progress" aria-hidden="true">
        <i style={{ animationDuration: `${INTRO_MS.fade}ms` }} />
      </div>
      <div className="nx-intro-skip" aria-hidden="true">
        Press any key to skip
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
