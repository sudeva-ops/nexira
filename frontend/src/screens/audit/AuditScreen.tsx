import { Icon, NonIdealState } from "@blueprintjs/core";

import { useAuditLog, useAuditVerify } from "../../api/audit";
import { ApiError } from "../../api/client";
import { hasRole, useMe } from "../../api/me";
import { AUDIT_PAGE, auditFigures } from "../../ui/figures";
import { plural } from "../../ui/format";
import { Card, Kpi } from "../../ui/primitives";
import { SkeletonRows } from "../../ui/Skeleton";
import { TileRow } from "../../ui/TileRow";
import { useNow } from "../../ui/useNow";

// Audit view (admin, D-25). The backend enforces ADMIN; this only avoids
// showing an empty screen to other roles. DC-01, DC-05 (D-56): figures in a tile row and the
// log in a card, like every other screen. Display only: the chain and the API are unchanged.
export function AuditScreen() {
  const me = useMe();
  const isAdmin = hasRole(me.data, "ADMIN");
  const log = useAuditLog();
  const verify = useAuditVerify(isAdmin);
  const now = useNow(true, 60_000);

  if (me.isPending) return <SkeletonRows rows={8} />;
  if (!isAdmin || (log.error instanceof ApiError && log.error.status === 403)) {
    return <NonIdealState icon="lock" title="Administrators only" />;
  }
  const v = verify.data;
  const f = log.data && auditFigures(log.data, now);

  return (
    <div className="nx-pad">
      {v && !v.intact && (
        <div className="nx-banner red" role="alert">
          <Icon icon="error" />
          <div className="nx-grow">
            <b>Hash chain broken.</b> First broken entry: #{v.first_broken_seq}.
          </div>
        </div>
      )}
      <TileRow label="Audit figures">
        <Kpi icon="history" label="Entries" value={v ? v.rows : "—"} detail="Every state change, in order" />
        <Kpi
          icon={v?.intact === false ? "error" : "endorsed"}
          label="Chain"
          value={v ? <span className={v.intact ? "nx-safe" : "nx-help"}>{v.intact ? "Intact" : "Broken"}</span> : "—"}
          detail={v ? (v.intact ? `${plural(v.rows, "entry", "entries")} verified by the database` : "Verification failed") : ""}
          alert={v?.intact === false}
        />
        <Kpi
          icon="time"
          label="Entries · 24 h"
          value={f ? f.day : "—"}
          detail={f ? (f.full ? `The latest ${AUDIT_PAGE} are all from today` : `${f.agents} by agents`) : ""}
        />
        <Kpi icon="person" label="People acting · 24 h" value={f ? f.people : "—"} detail="Named users, by id" />
      </TileRow>
      <Card
        icon="th-list"
        title="Audit log"
        sub={`The latest ${AUDIT_PAGE} entries · newest first · times in UTC`}
        chip={v && { text: v.intact ? "Hash chain intact" : "Hash chain broken", tone: v.intact ? "ok" : "warn" }}
      >
        {log.isPending ? (
          <SkeletonRows rows={8} />
        ) : (
          <table className="nx-table-plain" aria-label="Audit log">
            <thead>
              <tr>
                <th>#</th>
                <th>Time (UTC)</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Entity</th>
              </tr>
            </thead>
            <tbody>
              {log.data?.map((e) => (
                <tr key={e.chain_seq}>
                  <td className="nx-mono">{e.chain_seq}</td>
                  <td className="nx-mono">{e.occurred_at.slice(0, 19).replace("T", " ")}</td>
                  <td>
                    <span className="nx-chip">{e.actor_type}</span> {e.actor_id}
                  </td>
                  <td className="nx-mono">{e.action}</td>
                  <td>
                    {e.entity_type}
                    {e.entity_id && <span className="nx-dim"> · {e.entity_id}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
