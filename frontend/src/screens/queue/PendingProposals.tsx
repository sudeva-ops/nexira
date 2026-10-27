import { Link } from "react-router-dom";

import { LEVELS, travelLinks, useProposals } from "../../api/proposals";

/** TA-09: a trip's pending agent proposals, shown where people look at the trip or flight.
 *  Decisions stay in the Decision Queue. */
export function PendingProposals({ tripId }: { tripId: string }) {
  const pending = (useProposals().data ?? []).filter(
    (p) => p.status === "PENDING" && travelLinks(p).trip === tripId,
  );
  if (pending.length === 0) return null;
  return (
    <div className="nx-pending-proposals" aria-label="Agent proposals">
      <div className="nx-lbl">Agent proposals</div>
      {pending.map((p) => (
        <div key={p.id} className="nx-row">
          <span className="nx-grow">
            {p.title} <span className="nx-dim">· {LEVELS[p.effective_level]}</span>
          </span>
        </div>
      ))}
      <Link to="/">Decide in the Decision Queue →</Link>
    </div>
  );
}
