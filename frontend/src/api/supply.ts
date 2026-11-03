import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiSend } from "./client";

// Supply Chain & Third-Party Risk (Prompts 90-94; SUP-01..07, D-44). The register, routes and
// their statuses are simulated (D-19). ROUTE BLOCKED, ALTERNATE and "impacted" are worked out by
// the backend on every read (plan-pilot-sup §3, §4). The names of who acted only within the
// caller's scope (§6). Every button comes from GET /api/me/permissions; the backend decides
// through app/core/approvals.py. Nothing is sent to a supplier.

export type ReportedStatus = "NORMAL" | "WATCH" | "DELAYED" | "AT_RISK";
export type ShownStatus = ReportedStatus | "ROUTE_BLOCKED";
export type RouteStatus = "OPEN" | "RESTRICTED" | "DELAYED" | "BLOCKED";
export type ShownRouteStatus = RouteStatus | "ALTERNATE";

export interface SupplierRef {
  id: string;
  code: string;
  name: string;
}

export interface Mitigation {
  id: string;
  supplier_id: string;
  supplier_code: string;
  incident_id: string | null;
  incident_reference: string | null;
  backup: SupplierRef | null;
  route_code: string | null;
  route_label: string | null;
  note: string | null;
  activated_at: string;
  activated_by_name: string | null;
  stood_down_at: string | null;
  stood_down_by_name: string | null;
  active: boolean;
}

export interface Supplier {
  id: string;
  code: string;
  name: string;
  service: string;
  mission_id: string | null;
  mission_code: string | null;
  city: string | null;
  tier: number;
  status: ReportedStatus;
  status_detail: string | null;
  status_at: string;
  shown: ShownStatus;
  detail: string | null;
  impacted: boolean;
  incident_id: string | null;
  incident_reference: string | null;
  backup: SupplierRef | null;
  in_bcp: boolean;
  vetting_valid_until: string;
  vetting_current: boolean;
  performance_score: number | null;
  fuel_stock_hours: number | null;
  mitigation: Mitigation | null;
  source: string;
}

export interface Route {
  id: string;
  code: string;
  label: string;
  kind: "POUCH" | "FUEL" | "STAFF_TRANSPORT" | "FREIGHT";
  mission_id: string;
  mission_code: string;
  supplier_id: string | null;
  supplier_code: string | null;
  alternate_of_code: string | null;
  status: RouteStatus;
  shown: ShownRouteStatus;
  detail: string | null;
  status_at: string;
  zone_incidents: string[];
}

export interface SupplierDetail extends Supplier {
  routes: Route[];
  mitigations: Mitigation[];
}

export interface Banner {
  incident_id: string;
  incident_reference: string;
  mission_code: string;
  suppliers: {
    code: string;
    name: string;
    shown: ShownStatus;
    detail: string | null;
  }[];
}

export interface SupplySummary {
  suppliers: number;
  missions: number;
  tier1: number;
  impacted: number;
  impacted_missions: string[];
  routes: number;
  banners: Banner[];
}

export interface SupplyPermissions {
  activate_mitigation: boolean;
  stand_down_mitigation: boolean;
}

export const supplyKeys = {
  all: ["supply"] as const, // what realtime invalidates (SUPPLY_UPDATED and ACTIVE incidents)
  summary: ["supply", "summary"] as const,
  suppliers: (missionId: string) => ["supply", "suppliers", missionId] as const,
  supplier: (id: string) => ["supply", "supplier", id] as const,
  permissions: (id: string) => ["supply", "permissions", id] as const,
};

/** The design's status chips (SUP-02). */
export const SHOWN_LABEL: Record<ShownStatus | ShownRouteStatus, string> = {
  ROUTE_BLOCKED: "ROUTE BLOCKED",
  AT_RISK: "AT RISK",
  DELAYED: "DELAYED",
  WATCH: "WATCH",
  NORMAL: "NORMAL",
  BLOCKED: "BLOCKED",
  RESTRICTED: "RESTRICTED",
  ALTERNATE: "ALTERNATE",
  OPEN: "OPEN",
};
export const SHOWN_SEV: Record<ShownStatus | ShownRouteStatus, string> = {
  ROUTE_BLOCKED: "crit",
  AT_RISK: "high",
  DELAYED: "med",
  WATCH: "low",
  NORMAL: "ok",
  BLOCKED: "crit",
  RESTRICTED: "high",
  ALTERNATE: "ok",
  OPEN: "ok",
};

/** "3 third parties impacted by INC-2026-1042." */
export function bannerTitle(banner: Banner): string {
  const n = banner.suppliers.length;
  return `${n} third ${n === 1 ? "party" : "parties"} impacted by ${banner.incident_reference}.`;
}

/** The mission to open: one with impacted suppliers, else every mission (SUP-05). */
export function defaultSupplyMission(
  missions: { id: string; code: string }[],
  summary: Pick<SupplySummary, "impacted_missions"> | undefined,
): string {
  const code = summary?.impacted_missions[0];
  return missions.find((m) => m.code === code)?.id ?? "";
}

export function useSupplySummary() {
  return useQuery({
    queryKey: supplyKeys.summary,
    queryFn: () => apiGet<SupplySummary>("/api/supply/summary"),
  });
}

export function useSuppliers(missionId: string) {
  return useQuery({
    queryKey: supplyKeys.suppliers(missionId),
    queryFn: () =>
      apiGet<Supplier[]>(
        "/api/supply/suppliers",
        missionId ? { mission_id: missionId } : undefined,
      ),
  });
}

export function useSupplier(id: string | undefined) {
  return useQuery({
    queryKey: supplyKeys.supplier(id ?? ""),
    queryFn: () => apiGet<SupplierDetail>(`/api/supply/suppliers/${id}`),
    enabled: !!id,
  });
}

export function useSupplyPermissions(id: string | undefined) {
  return useQuery({
    queryKey: supplyKeys.permissions(id ?? ""),
    queryFn: () =>
      apiGet<SupplyPermissions>("/api/me/permissions", {
        entity_type: "supplier",
        entity_id: id ?? "",
      }),
    enabled: !!id,
  });
}

export function useActivateMitigation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, note }: { id: string; note: string | null }) =>
      apiSend<SupplierDetail>(
        "POST",
        `/api/supply/suppliers/${id}/mitigation`,
        note ? { note } : {},
      ),
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: supplyKeys.all }),
  });
}

export function useStandDown() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (mitigationId: string) =>
      apiSend<SupplierDetail>(
        "POST",
        `/api/supply/mitigations/${mitigationId}/stand-down`,
        {},
      ),
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: supplyKeys.all }),
  });
}
