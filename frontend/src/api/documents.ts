import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiSend } from "./client";

// Document Expiry (Prompts 50-51; DX-01..09, D-37). Documents are simulated (D-19) and
// carry no numbers, scans or photos. The backend decides every action; the screen only
// hides what GET /api/me/permissions and each row's can_act say is not allowed.

export type DocType =
  "PASSPORT" | "DIPLOMATIC_PASSPORT" | "VISA" | "RESIDENCE_PERMIT" | "ACCREDITATION" | "SECURITY_CLEARANCE";
export const DOC_TYPES: DocType[] = [
  "PASSPORT",
  "DIPLOMATIC_PASSPORT",
  "VISA",
  "RESIDENCE_PERMIT",
  "ACCREDITATION",
  "SECURITY_CLEARANCE",
];
export const DOC_LABEL: Record<DocType, string> = {
  PASSPORT: "Passport",
  DIPLOMATIC_PASSPORT: "Diplomatic passport",
  VISA: "Visa",
  RESIDENCE_PERMIT: "Residence permit",
  ACCREDITATION: "Accreditation",
  SECURITY_CLEARANCE: "Security clearance",
};

export type Urgency = "EXPIRED" | "CRITICAL" | "HIGH" | "MODERATE" | "OK";
export const URGENCIES: Urgency[] = ["EXPIRED", "CRITICAL", "HIGH", "MODERATE", "OK"];

export type RenewalStatus = "NONE" | "REQUESTED" | "IN_PROGRESS" | "RENEWED";
export type RenewalStep = Exclude<RenewalStatus, "NONE">;

export interface TravelDocument {
  id: string;
  person_id: string;
  holder_name: string;
  holder_type: string;
  mission_id: string | null;
  mission_code: string | null;
  doc_type: DocType;
  issuing_country: string;
  valid_until: string; // ISO date
  days_left: number;
  urgency: Urgency;
  holder_ready: boolean;
  could_block_evacuation: boolean;
  renewal_status: RenewalStatus;
  renewal_requested_by: string | null;
  renewal_requested_at: string | null;
  renewal_started_by: string | null;
  renewal_started_at: string | null;
  renewed_by: string | null;
  renewed_at: string | null;
  can_act: boolean;
  simulated: boolean;
}

export interface DocumentSummary {
  tracked: number;
  expiring_30: number;
  expiring_90: number;
  in_renewal_90: number;
  could_block: number;
  people: number;
  ready: number;
  ready_pct: number | null;
  missions: { mission_id: string; code: string; people: number; ready: number; ready_pct: number | null }[];
  simulated: boolean;
}

export interface DocumentPermissions {
  read_documents: boolean;
  act_documents: boolean;
  read_document_missions: string[] | null; // null: every mission
  act_document_missions: string[] | null;
}

export interface DocumentFilters {
  mission_id?: string;
  doc_type?: string;
  urgency?: string;
}

export interface RemindersSent {
  campaign_id: string;
  reference: string;
  recipients: number;
  documents: number;
}

export const documentKeys = {
  all: ["documents"] as const, // what realtime invalidates on DOCUMENT_UPDATED
  list: (filters: DocumentFilters) => [...documentKeys.all, "list", filters] as const,
  summary: ["documents", "summary"] as const,
  permissions: ["documents", "permissions"] as const,
};

/** "21 days", "1 day", "expired 3 days ago". */
export function daysText(days: number): string {
  if (days < 0) return `expired ${-days} day${days === -1 ? "" : "s"} ago`;
  return `${days} day${days === 1 ? "" : "s"}`;
}

/** The renewal steps that come next (forward only, DX-04; as the guard's _FROM). */
export function nextSteps(status: RenewalStatus): RenewalStep[] {
  if (status === "NONE") return ["REQUESTED", "IN_PROGRESS"];
  if (status === "REQUESTED") return ["IN_PROGRESS"];
  if (status === "IN_PROGRESS") return ["RENEWED"];
  return [];
}

export function useDocumentPermissions() {
  return useQuery({
    queryKey: documentKeys.permissions,
    queryFn: () => apiGet<DocumentPermissions>("/api/me/permissions", { entity_type: "documents" }),
    staleTime: 5 * 60_000, // roles change rarely
  });
}

export function useDocumentSummary() {
  return useQuery({
    queryKey: documentKeys.summary,
    queryFn: () => apiGet<DocumentSummary>("/api/documents/summary"),
  });
}

/** DX-09: only for a role that reads the list; a Viewer never asks. */
export function useDocuments(filters: DocumentFilters, enabled: boolean) {
  const params: Record<string, string> = {};
  for (const [k, v] of Object.entries(filters)) if (v) params[k] = v;
  return useQuery({
    queryKey: documentKeys.list(filters),
    queryFn: () => apiGet<TravelDocument[]>("/api/documents", params),
    enabled,
  });
}

function useDocumentMutation<T, R>(send: (arg: T) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: send,
    onSuccess: () => void client.invalidateQueries({ queryKey: documentKeys.all }),
  });
}

export function useRenew() {
  return useDocumentMutation(({ id, step, validUntil }: { id: string; step: RenewalStep; validUntil?: string }) =>
    apiSend<TravelDocument>(
      "POST",
      `/api/documents/${id}/renewal`,
      validUntil ? { step, valid_until: validUntil } : { step },
    ),
  );
}

export function useSendReminders() {
  return useDocumentMutation((ids: string[]) =>
    apiSend<RemindersSent>("POST", "/api/documents/reminders", { document_ids: ids }),
  );
}
