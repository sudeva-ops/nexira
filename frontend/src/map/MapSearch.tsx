import { Button, Icon, type IconName } from "@blueprintjs/core";
import { useEffect, useMemo, useRef, useState } from "react";

import { loadPlaces, type Place, type Result, type ResultKind, search } from "./search";

// The search box on the world maps (SRC-01..04; D-52; plan-pilot-map §4). "/" focuses it; arrow
// keys and Enter choose; Escape closes. The gazetteer loads the first time it gets focus; nothing
// typed here leaves the browser (D-24).

const KIND: Record<ResultKind, { icon: IconName; label: string }> = {
  COORDINATES: { icon: "locate", label: "Point" },
  MISSION: { icon: "office", label: "Mission" },
  SITE: { icon: "home", label: "Site" },
  INCIDENT: { icon: "warning-sign", label: "Incident" },
  FLIGHT: { icon: "airplane", label: "Flight" },
  PLACE: { icon: "map-marker", label: "Place" },
};

function typing(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
}

export function MapSearch({
  records,
  onPick,
  onNearby,
  placeholder = "Search places, missions, incidents or coordinates",
}: {
  records: Result[];
  onPick: (r: Result) => void;
  onNearby?: (r: Result) => void;
  placeholder?: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [places, setPlaces] = useState<Place[] | null>(null);
  const results = useMemo(() => search(query, records, places ?? []), [query, records, places]);

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "/" && !e.ctrlKey && !e.metaKey && !typing(e.target)) {
        e.preventDefault();
        input.current?.focus();
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);

  const choose = (r: Result | undefined, nearby = false) => {
    if (!r) return;
    if (nearby && onNearby) onNearby(r);
    else onPick(r);
    setOpen(false);
    input.current?.blur();
  };

  return (
    <div className="nx-search" role="search">
      <div className="bp6-input-group bp6-small">
        <Icon icon="search" />
        <input
          ref={input}
          className="bp6-input"
          type="search"
          aria-label="Search the map"
          aria-expanded={open && results.length > 0}
          aria-controls="nx-search-results"
          aria-activedescendant={open && results[active] ? `nx-search-${active}` : undefined}
          role="combobox"
          autoComplete="off"
          placeholder={placeholder}
          value={query}
          onFocus={() => {
            setOpen(true);
            if (places === null) void loadPlaces().then(setPlaces);
          }}
          onBlur={() => setOpen(false)}
          onChange={(e) => {
            setQuery(e.currentTarget.value);
            setActive(0);
            setOpen(true);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown" || e.key === "ArrowUp") {
              e.preventDefault();
              const step = e.key === "ArrowDown" ? 1 : -1;
              setActive((a) => (results.length ? (a + step + results.length) % results.length : 0));
            } else if (e.key === "Enter") {
              e.preventDefault();
              choose(results[active], e.shiftKey);
            } else if (e.key === "Escape") {
              setOpen(false);
              input.current?.blur();
            }
          }}
        />
      </div>
      {open && results.length > 0 && (
        <ul className="nx-search-results" id="nx-search-results" role="listbox" aria-label="Search results">
          {results.map((r, i) => (
            <li
              key={`${r.kind}-${r.id}`}
              id={`nx-search-${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? "active" : undefined}
              // mousedown, not click: the input's blur would close the list first.
              onMouseDown={(e) => {
                e.preventDefault();
                choose(r);
              }}
              onMouseEnter={() => setActive(i)}
            >
              <Icon icon={KIND[r.kind].icon} size={12} />
              <span className="nx-search-label">
                {r.label} {r.detail && <span className="nx-dim">· {r.detail}</span>}
              </span>
              <span className="nx-search-kind">{KIND[r.kind].label}</span>
              {onNearby && (
                <Button
                  small
                  minimal
                  icon="locate"
                  aria-label={`What's nearby ${r.label}`}
                  title="What's nearby (Shift+Enter)"
                  onMouseDown={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    choose(r, true);
                  }}
                />
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
