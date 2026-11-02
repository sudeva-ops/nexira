/** Globe or flat (UI 2), on the map's corner; the choice is kept in this browser. */
export function MapToggle({ globe, onChange }: { globe: boolean; onChange: (globe: boolean) => void }) {
  return (
    <div className="nx-map-toggle" role="group" aria-label="Map view">
      <button type="button" aria-pressed={globe} onClick={() => onChange(true)}>
        Globe
      </button>
      <button type="button" aria-pressed={!globe} onClick={() => onChange(false)}>
        Flat
      </button>
    </div>
  );
}
