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

export function useAuditVerify(enabled: boolean) {
  return useQuery({
    queryKey: ["audit-verify"],
    queryFn: () => apiGet<AuditVerify>("/api/audit/verify"),
    enabled,
  });
}
