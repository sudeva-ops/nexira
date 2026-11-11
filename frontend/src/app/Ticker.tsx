import { useLayoutEffect, useRef, useState } from "react";

import { useIncidents } from "../api/intel";
import type { RealtimeEvent } from "../api/realtimeClient";
import { useRealtimeEvents } from "../api/realtimeContext";
import { useReducedMotion } from "../ui/useMotion";
import { scrolls, tickerItems } from "./tickerItems";

// The live ticker under the header (UI 3): the latest realtime events as they arrive, then the
// open incidents, most severe first (UIP-01). Events carry ids only (PLT-05), so an event shows its kind, and the incident's
// reference when the incident is one every role can see in the list. The text is drawn by CSS
// (data-text), and the strip is hidden from assistive technology: it repeats what the screens
// show, and must not be read twice or match a search for the screens' own text. It scrolls only
// when the items do not fit; otherwise it stands still and shows each once (UIP-01).

const KEEP = 12; // the latest events kept

export function Ticker() {
  const incidents = useIncidents().data ?? [];
  const reduced = useReducedMotion();
  const view = useRef<HTMLDivElement>(null);
  const track = useRef<HTMLDivElement>(null);
  const [overflow, setOverflow] = useState(false);
  const [events, setEvents] = useState<
    { id: string; event: string; incident_id?: string; code?: string; at: Date }[]
  >([]);
  useRealtimeEvents((event: RealtimeEvent) => {
    if (event.event === "FLIGHT_POSITIONS") return; // every 15 s: noise in a ticker
    const incident = typeof event.data.incident_id === "string" ? event.data.incident_id : undefined;
    const code = typeof event.data.code === "string" ? event.data.code : undefined;
    setEvents((list) => [{ id: event.id, event: event.event, incident_id: incident, code, at: new Date() }, ...list].slice(0, KEEP));
  });
  const items = tickerItems(incidents, events);
  const moving = overflow && !reduced;
  const signature = items.map((i) => i.text).join("|");
  // One copy's width against the strip's, again whenever either changes size.
  useLayoutEffect(() => {
    const measure = () => {
      const t = track.current;
      const v = view.current;
      if (!t || !v) return;
      const copies = t.dataset.copies === "2" ? 2 : 1;
      setOverflow(scrolls(t.scrollWidth / copies, v.clientWidth));
    };
    measure();
    if (typeof ResizeObserver === "undefined" || !view.current) return;
    const observer = new ResizeObserver(measure);
    observer.observe(view.current);
    return () => observer.disconnect();
  }, [signature]);
  if (!items.length) return <div className="nx-ticker" aria-hidden="true" />;
  // Twice over, so the strip loops without a gap; once when still.
  const shown = moving ? [...items, ...items] : items;
  return (
    <div className={`nx-ticker${moving ? "" : " still"}`} aria-hidden="true" data-testid="ticker">
      <span className="nx-ticker-tag" data-text="LIVE FEED" />
      <div className="nx-ticker-viewport" ref={view}>
        <div
          ref={track}
          className="nx-ticker-track"
          data-copies={moving ? 2 : 1}
          style={{ animationDuration: `${Math.max(30, items.length * 7)}s` }}
        >
          {shown.map((item, k) => (
            <span key={`${item.key}-${k}`} className={`nx-ticker-item ${item.tone}`} data-text={item.text} />
          ))}
        </div>
      </div>
    </div>
  );
}
