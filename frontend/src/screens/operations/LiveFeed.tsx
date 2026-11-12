import { Icon } from "@blueprintjs/core";
import { useEffect, useRef, useState } from "react";

import type { Incident, Signal } from "../../api/intel";
import { useRealtimeEvents } from "../../api/realtimeContext";
import { ago } from "../../app/time";
import { SEVERITY_COLOUR } from "../../map/geo";
import { feedItems, MERGE_MS } from "./feed";
import { categoryLabel } from "../../ui/format";
import { Sev, SourceChip } from "../../ui/primitives";
import { Empty } from "../../ui/Empty";

/** Ids of signals that just fused, each kept for MERGE_MS. */
function useMergingSignals(): Set<number> {
  const [merging, setMerging] = useState<Set<number>>(new Set());
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  useRealtimeEvents((event) => {
    if (event.event !== "SIGNAL_INGESTED" || !event.data.incident_id) return;
    const id = Number(event.data.signal_id);
    setMerging((current) => new Set(current).add(id));
    timers.current.push(
      setTimeout(() => {
        setMerging((current) => {
          const next = new Set(current);
          next.delete(id);
          return next;
        });
      }, MERGE_MS),
    );
  });
  useEffect(() => () => timers.current.forEach(clearTimeout), []);
  return merging;
}

interface Props {
  incidents: Incident[];
  signals: Signal[];
  onSelect: (incident: Incident) => void;
}

export function LiveFeed({ incidents, signals, onSelect }: Props) {
  const merging = useMergingSignals();
  const items = feedItems(incidents, signals, merging);
  if (items.length === 0) {
    return <Empty>No signals yet.</Empty>;
  }
  return (
    <div className="nx-feed" aria-label="Live intelligence feed">
      {items.map((item) =>
        item.kind === "incident" ? (
          <button
            type="button"
            key={`i-${item.incident.id}`}
            className="nx-fi fused"
            style={{ ["--c" as string]: SEVERITY_COLOUR[item.incident.severity] }}
            onClick={() => onSelect(item.incident)}
            aria-label={`Open ${item.incident.reference}`}
          >
            <div className="nx-row">
              <Sev severity={item.incident.severity} />
              <span className="nx-chip nx-fused-chip">
                <Icon icon="git-merge" size={10} />
                FUSED · {item.incident.signal_count}{" "}
                {item.incident.signal_count === 1 ? "SOURCE" : "SOURCES"}
              </span>
              <span className="nx-grow nx-dim nx-mono nx-right">{ago(item.at)}</span>
            </div>
            <div className="t">
              {item.incident.reference} · {item.incident.title}
            </div>
            <div className="m">
              <Icon icon="map-marker" size={10} />
              {item.incident.place_label} · {categoryLabel(item.incident.category)}
            </div>
            <div className="m">
              {item.incident.sources.map((s) => (
                <SourceChip key={s.code} source={s} />
              ))}
              {item.incident.confidence !== null && (
                <span className="nx-src nx-conf">Confidence {item.incident.confidence}%</span>
              )}
            </div>
          </button>
        ) : (
          <div
            key={`s-${item.signal.id}`}
            className={`nx-fi raw${item.merging ? " merging" : ""}`}
            style={{
              ["--c" as string]: item.signal.norm_severity
                ? SEVERITY_COLOUR[item.signal.norm_severity]
                : "#738091",
            }}
          >
            <div className="nx-row">
              {item.signal.norm_severity && <Sev severity={item.signal.norm_severity} />}
              <span className="nx-chip">RAW SIGNAL</span>
              {item.merging && item.signal.incident_reference && (
                <span className="nx-chip nx-fused-chip">→ {item.signal.incident_reference}</span>
              )}
              {item.signal.norm_status === "DISCARDED" && (
                <span className="nx-chip">DISCARDED</span>
              )}
              <span className="nx-grow nx-dim nx-mono nx-right">{ago(item.at)}</span>
            </div>
            <div className="t">{item.signal.title}</div>
            <div className="m">
              <Icon icon="map-marker" size={10} />
              {item.signal.place_label ?? "No location"}
            </div>
            <div className="m">
              <SourceChip
                source={{ name: item.signal.source_name, simulated: item.signal.source_simulated }}
              />
              <span className="nx-src">
                {item.signal.provider_severity ?? "?"} → {item.signal.norm_severity ?? "unmapped"}
              </span>
            </div>
          </div>
        ),
      )}
    </div>
  );
}
