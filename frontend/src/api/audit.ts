import { useQuery } from "@tanstack/react-query";

import { apiGet } from "./client";

export interface AuditEntry {
  chain_seq: number;
  occurred_at: string;
  actor_type: "USER" | "AGENT" | "SYSTEM";
  actor_id: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  details: Record<string, unknown>;
  prev_hash: string | null;
  row_hash: string;
}

export interface AuditVerify {
  intact: boolean;
  first_broken_seq: number | null;
  rows: number;
}

export function useAuditLog(limit = 200) {
  return useQuery({
    queryKey: ["audit", limit],
    queryFn: () => apiGet<AuditEntry[]>("/api/audit", { limit }),
  });
}

/** Any role may read the audit trail of one entity (plan G-06). */
export function useEntityAudit(entityType: string, entityId: string | undefined) {
  return useQuery({
    queryKey: ["audit", entityType, entityId ?? ""],
    queryFn: () =>
      apiGet<AuditEntry[]>("/api/audit", {
        entity_type: entityType,
        entity_id: entityId ?? "",
        limit: 100,
      }),
    enabled: !!entityId,
  });
}

export function useAuditVerify(enabled: boolean) {
  return useQuery({
    queryKey: ["audit-verify"],
    queryFn: () => apiGet<AuditVerify>("/api/audit/verify"),
    enabled,
  });
}
