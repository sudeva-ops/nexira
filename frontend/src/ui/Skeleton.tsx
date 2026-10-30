import { Classes } from "@blueprintjs/core";

/** Grey placeholder lines shaped like the list that is loading (Blueprint's skeleton). */
export function SkeletonRows({ rows = 4 }: { rows?: number }) {
  return (
    <div className="nx-skeleton" role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className={Classes.SKELETON} />
      ))}
    </div>
  );
}
