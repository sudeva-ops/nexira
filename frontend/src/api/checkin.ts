import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiSend } from "./client";

export interface Campaign {
  id: string;
  reference: string;
  incident_id: string | null;
  campaign_type: "ALERT" | "CHECKIN" | "ADVISORY" | "TEST";
  message: string;
  channels: string[];
  status: "DRAFT" | "SENDING" | "SENT" | "CANCELLED";
  created_by_type: string;
  created_at: string;
  sent_at: string | null;
  escalate_after_s: number;
  recipients: number;
  deliveries: Record<string, number>;
  simulated: boolean;
}

export interface Tally {
  recipients: number;
  safe: number;
  need_help: number;
  pending: number;
  accounted_pct: number;
}

export interface CheckinSummary {
  campaign_id: string;
  reference: string;
  incident_id: string | null;
  status: string;
  sent_at: string | null;
  escalate_after_s: number;
  personnel: Tally;
  citizens: Tally;
}

export interface CheckinPerson {
  person_id: string;
  full_name: string;
  person_type: string;
  role_title: string | null;
  mission_code: string | null;
  status: "SAFE" | "NEED_HELP" | "PENDING";
  channel: string | null;
  note: string | null;
  responded_at: string | null;
  escalated: boolean;
}

export const checkinKeys = {
  campaigns: ["campaigns"] as const,
  checkin: (id: string) => ["checkin", id] as const,
};

export function useCampaigns() {
  return useQuery({
    queryKey: checkinKeys.campaigns,
    queryFn: () => apiGet<Campaign[]>("/api/campaigns"),
  });
}

export function useCheckinSummary(id: string | undefined) {
  return useQuery({
    queryKey: [...checkinKeys.checkin(id ?? ""), "summary"],
    queryFn: () => apiGet<CheckinSummary>(`/api/checkin/${id}/summary`),
    enabled: !!id,
    placeholderData: keepPreviousData,
  });
}

export function useCheckinResponses(id: string | undefined) {
  return useQuery({
    queryKey: [...checkinKeys.checkin(id ?? ""), "responses"],
    queryFn: () => apiGet<CheckinPerson[]>(`/api/checkin/${id}/responses`, { limit: 60 }),
    enabled: !!id,
    placeholderData: keepPreviousData,
  });
}

export function usePendingPersonnel(id: string | undefined) {
  return useQuery({
    queryKey: [...checkinKeys.checkin(id ?? ""), "pending-personnel"],
    queryFn: () =>
      apiGet<CheckinPerson[]>(`/api/checkin/${id}/people`, { group: "personnel", status: "PENDING" }),
    enabled: !!id,
  });
}

function useCheckinMutation<T, R>(id: string, send: (body: T) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: send,
    onSuccess: () => void client.invalidateQueries({ queryKey: checkinKeys.checkin(id) }),
  });
}

/** D-28: the phone preview panel answers through the API. */
export function useRespond(id: string) {
  return useCheckinMutation(id, (body: { person_id: string; status: "SAFE" | "NEED_HELP" }) =>
    apiSend<unknown>("POST", `/api/checkin/${id}/respond`, { ...body, channel: "APP" }),
  );
}

export function useEscalate(id: string) {
  return useCheckinMutation(id, () =>
    apiSend<{ personnel: string[]; citizens: number }>("POST", `/api/checkin/${id}/escalate`, {}),
  );
}
