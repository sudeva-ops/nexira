import { Callout, HTMLTable, NonIdealState, Tag } from "@blueprintjs/core";

import { useAuditLog, useAuditVerify } from "../../api/audit";
import { ApiError } from "../../api/client";
import { hasRole, useMe } from "../../api/me";
import { SkeletonRows } from "../../ui/Skeleton";

// Audit view (admin, D-25). The backend enforces ADMIN; this only avoids
// showing an empty screen to other roles.
export function AuditScreen() {
  const me = useMe();
  const isAdmin = hasRole(me.data, "ADMIN");
  const log = useAuditLog();
  const verify = useAuditVerify(isAdmin);

  if (me.isPending) return <SkeletonRows rows={8} />;
  if (!isAdmin || (log.error instanceof ApiError && log.error.status === 403)) {
    return <NonIdealState icon="lock" title="Administrators only" />;
  }

  return (
    <div className="nx-pad">
      {verify.data && (
        <Callout
          intent={verify.data.intact ? "success" : "danger"}
          icon={verify.data.intact ? "endorsed" : "error"}
          title={verify.data.intact ? "Hash chain intact" : "Hash chain broken"}
        >
          {verify.data.intact
            ? `${verify.data.rows} entries verified by the database.`
            : `First broken entry: #${verify.data.first_broken_seq}.`}
        </Callout>
      )}
      {log.isPending ? (
        <SkeletonRows rows={8} />
      ) : (
        <HTMLTable compact striped className="nx-table" aria-label="Audit log">
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
                  <Tag minimal>{e.actor_type}</Tag> {e.actor_id}
                </td>
                <td className="nx-mono">{e.action}</td>
                <td>
                  {e.entity_type}
                  {e.entity_id && <span className="nx-dim"> · {e.entity_id}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </HTMLTable>
      )}
    </div>
  );
}
