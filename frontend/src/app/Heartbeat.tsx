import { useState } from "react";

import type { RealtimeEvent } from "../api/realtimeClient";
import { useRealtimeEvents, useRealtimeStatus } from "../api/realtimeContext";
import { useFlash } from "../ui/useMotion";
import { eventLabel } from "./eventLabel";
import { formatTime, HOME_TZ } from "./time";

// The header's heartbeat: the connection breathes while live, and the newest event
// is named as it arrives.

export function LiveIndicator() {
  const status = useRealtimeStatus();
  // "Reconnecting" once the socket has been live and dropped; "connecting" before that.
  const [wasLive, setWasLive] = useState(false);
  if (status === "live" && !wasLive) setWasLive(true);
  const state = status === "connecting" && wasLive ? "reconnecting" : status;
  const label = {
    live: "LIVE",
    connecting: "CONNECTING",
    reconnecting: "RECONNECTING",
    offline: "OFFLINE",
  }[state];
  return (
    <span className={`nx-live ${state}`} role="status" aria-label={`Realtime ${state}`}>
      <i />
      {label}
    </span>
  );
}

/** The newest realtime event and when it arrived (home time zone, like the clock). */
export function LastEvent() {
  const [last, setLast] = useState<{
    id: string;
    label: string;
    at: Date;
  } | null>(null);
  useRealtimeEvents((event: RealtimeEvent) =>
    setLast({ id: event.id, label: eventLabel(event.event), at: new Date() }),
  );
  const flash = useFlash(last?.id ?? "");
  if (!last) return null;
  return (
    <span className={`nx-last-event ${flash}`} aria-label="Latest event" aria-live="off">
      {last.label} · <span className="nx-mono">{formatTime(last.at, HOME_TZ)}</span>
    </span>
  );
}
