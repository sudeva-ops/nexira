import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiSend } from "./client";

// After-Action Review (Prompts 106-111; AAR-01..09, D-47). Built from the platform record:
// rules draft the lessons, people decide (accept, reject, add, done) and a Security Officer or
// the HQ Crisis Director finalises, freezing the metrics. Roles, references and counts only;
// the backend decides every action through app/core/approvals.py and says what the caller may
// do (can_act, can_finalise). The export is audited (AAR-07).

export type Team =
  | "SECURITY"
  | "HR"
  | "FACILITIES"
  | "FLEET"
  | "CONSULAR"
  | "LOGISTICS"
  | "COMMUNICATIONS"
  | "IT"
  | "MISSION_MANAGEMENT";
export type Priority = "HIGH" | "MEDIUM" | "LOW";
export type ItemStatus = "DRAFT" | "ACCEPTED" | "REJECTED" | "DONE";

export const TEAMS: Team[] = [
  "SECURITY",
  "HR",
  "FACILITIES",
  "FLEET",
  "CONSULAR",
  "LOGISTICS",
  "COMMUNICATIONS",
  "IT",
  "MISSION_MANAGEMENT",
];

export interface Metric {
  key: string;
  label: string;
  value: number | null;
  unit: "s" | "%";
  target: number | null;
  met: boolean | null;
  detail: string | null;
}

export interface TimelineEntry {
  at: string;
  source: string;
  text: string;
}

export interface Item {
  id: string;
  rule_code: string | null;
  finding: string;
  action: string;
  owner_team: Team;
  priority: Priority;
  evidence: Record<string, unknown>;
  status: ItemStatus;
  due_on: string | null;
  reason: string | null;
  decided_at: string | null;
  done_at: string | null;
}

export interface Review {
  id: string;
  reference: string;
  incident_id: string;
  incident_reference: string;
  incident_title: string;
  incident_status: string;
  exercise?: boolean; // EXR-03: from a scenario run in EXERCISE mode (D-48); the API always sends it
  status: "DRAFT" | "FINAL";
  started_at: string;
  finalised_at: string | null;
  label: string;
  metrics: Metric[];
  timeline: TimelineEntry[];
  items: Item[];
  can_act: boolean;
  can_finalise: boolean;
  simulated: boolean;
}

export interface ReviewSummary {
  id: string;
  reference: string;
  incident_reference: string;
  incident_title: string;
  status: "DRAFT" | "FINAL";
  started_at: string;
  accepted: number;
  drafts: number;
  items: number;
  exercise?: boolean; // EXR-03: from a scenario run in EXERCISE mode (D-48); the API always sends it
}

export interface Ready {
  incident_id: string;
  reference: string;
  title: string;
  status: string;
  can_start: boolean;
  exercise?: boolean; // EXR-03: from a scenario run in EXERCISE mode (D-48); the API always sends it
}

export interface Reviews {
  reviews: ReviewSummary[];
  ready: Ready[];
}

export interface AcceptBody {
  owner_team: Team;
  due_on: string;
  action?: string;
}

export interface ItemBody {
  finding: string;
  action: string;
  owner_team: Team;
  priority: Priority;
  due_on: string;
}

export const aarKeys = {
  all: ["aar"] as const, // what realtime invalidates
  list: ["aar", "list"] as const,
  review: (id: string) => ["aar", "review", id] as const,
  // Not under "aar": realtime must not refetch it, since every fetch is an audited export.
  export: (id: string) => ["aar-export", id] as const,
};

/** "Mission management" from MISSION_MANAGEMENT. */
export function teamLabel(team: string): string {
  const words = team.toLowerCase().replace(/_/g, " ");
  return team === "HR" || team === "IT"
    ? team
    : words[0]?.toUpperCase() + words.slice(1);
}

/** Accepted (or done) out of everything decided or still a draft. */
export function acceptedOf(items: Item[]): [number, number] {
  return [
    items.filter((i) => i.status === "ACCEPTED" || i.status === "DONE").length,
    items.length,
  ];
}

export function useReviews() {
  return useQuery({
    queryKey: aarKeys.list,
    queryFn: () => apiGet<Reviews>("/api/aar"),
  });
}

export function useReview(id: string | undefined) {
  return useQuery({
    queryKey: aarKeys.review(id ?? ""),
    queryFn: () => apiGet<Review>(`/api/aar/${id ?? ""}`),
    enabled: Boolean(id),
  });
}

/** AAR-07: the print-ready review's figures; each fetch is audited, so once per visit. */
export function useReviewExport(id: string) {
  return useQuery({
    queryKey: aarKeys.export(id),
    queryFn: () => apiSend<Review>("POST", `/api/aar/${id}/export`, {}),
    staleTime: Infinity,
    gcTime: 0,
    refetchOnWindowFocus: false,
    retry: false,
  });
}

function useAarMutation<V>(request: (v: V) => Promise<Review>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: request,
    onSuccess: (review) => {
      client.setQueryData(aarKeys.review(review.id), review);
      void client.invalidateQueries({ queryKey: aarKeys.list });
    },
  });
}

export const useStartReview = () =>
  useAarMutation((incidentId: string) =>
    apiSend<Review>("POST", "/api/aar", { incident_id: incidentId }),
  );

export const useAccept = () =>
  useAarMutation(({ id, body }: { id: string; body: AcceptBody }) =>
    apiSend<Review>("POST", `/api/aar/items/${id}/accept`, body),
  );

export const useReject = () =>
  useAarMutation(({ id, reason }: { id: string; reason: string }) =>
    apiSend<Review>("POST", `/api/aar/items/${id}/reject`, { reason }),
  );

export const useDone = () =>
  useAarMutation((id: string) =>
    apiSend<Review>("POST", `/api/aar/items/${id}/done`, {}),
  );

export const useAddItem = () =>
  useAarMutation(({ reviewId, body }: { reviewId: string; body: ItemBody }) =>
    apiSend<Review>("POST", `/api/aar/${reviewId}/items`, body),
  );

export const useFinalise = () =>
  useAarMutation((reviewId: string) =>
    apiSend<Review>("POST", `/api/aar/${reviewId}/finalise`, {}),
  );
