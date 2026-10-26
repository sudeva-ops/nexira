import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { checkinKeys } from "./checkin";
import { apiGet, apiSend } from "./client";

// Mass Notification (Prompts 20-21; MN-01..10, D-31). The backend decides every
// action; the screen only hides what GET /api/me/permissions says is not allowed.

export type CampaignKind = "ALERT" | "ADVISORY" | "CHECKIN";
export type CampaignStatus = "DRAFT" | "PENDING_APPROVAL" | "SENDING" | "SENT" | "CANCELLED";
export type DeliveryStatus = "QUEUED" | "SENT" | "DELIVERED" | "READ" | "FAILED";

export interface NtfCampaign {
  id: string;
  reference: string;
  incident_id: string | null;
  campaign_type: CampaignKind | "TEST";
  message: string;
  translations: Record<string, string>;
  channels: string[];
  audience_filter: {
    missions?: string[];
    person_types?: string[];
    exposed?: boolean;
  };
  status: CampaignStatus;
  created_by_type: "USER" | "AGENT" | "PLAYBOOK";
  created_by: string | null;
  created_by_name: string | null;
  template_id: string | null;
  submitted_by: string | null;
  approved_by: string | null;
  approved_by_name: string | null;
  approved_at: string | null;
  rejection_reason: string | null;
  created_at: string;
  sent_at: string | null;
  recipients: number;
  deliveries: Partial<Record<DeliveryStatus, number>>;
  funnel: Record<string, Partial<Record<DeliveryStatus, number>>>;
  simulated: boolean;
}

export interface Draft {
  kind: CampaignKind;
  message: string;
  channels: string[];
  missions: string[];
  person_types: string[] | null;
  exposed_to_incident: boolean;
  incident_id: string | null;
  translations: Record<string, string>;
  template_id: string | null;
}

export interface Preview {
  recipients: number;
  by_person_type: Record<string, number>;
  by_mission: Record<string, number>;
}

export type Rendered = Record<
  string,
  { title?: string; body?: string; text?: string; subject?: string; script?: string; sms_segments?: number }
>;

export interface Template {
  id: string;
  code: string;
  kind: CampaignKind;
  mission_id: string | null;
  name: string;
  texts: Record<string, string>;
  reviewed: Record<string, boolean>;
  is_active: boolean;
}

export interface CampaignPermissions {
  edit_campaign: boolean;
  submit_campaign: boolean;
  approve_campaign: boolean;
  cancel_campaign: boolean;
}

export interface CampaignFilters {
  kind?: string;
  status?: string;
  mission_id?: string;
}

export const ntfKeys = {
  // checkinKeys.campaigns is what realtime invalidates on CAMPAIGN_* events.
  list: (filters: CampaignFilters) => [...checkinKeys.campaigns, "list", filters] as const,
  one: (id: string) => [...checkinKeys.campaigns, "one", id] as const,
  permissions: (id: string) => [...checkinKeys.campaigns, "permissions", id] as const,
  templates: ["templates"] as const,
};

export function useNtfCampaigns(filters: CampaignFilters) {
  const params: Record<string, string> = {};
  for (const [k, v] of Object.entries(filters)) if (v) params[k] = v;
  return useQuery({
    queryKey: ntfKeys.list(filters),
    queryFn: () => apiGet<NtfCampaign[]>("/api/campaigns", params),
  });
}

export function useNtfCampaign(id: string | undefined) {
  return useQuery({
    queryKey: ntfKeys.one(id ?? ""),
    queryFn: () => apiGet<NtfCampaign>(`/api/campaigns/${id}`),
    enabled: !!id,
  });
}

/** Plan G-07: what this user may do, from the same checks that enforce it. */
export function useCampaignPermissions(id: string | undefined) {
  return useQuery({
    queryKey: ntfKeys.permissions(id ?? ""),
    queryFn: () =>
      apiGet<CampaignPermissions>("/api/me/permissions", {
        entity_type: "notification_campaign",
        entity_id: id ?? "",
      }),
    enabled: !!id,
  });
}

export function useTemplates() {
  return useQuery({
    queryKey: ntfKeys.templates,
    queryFn: () => apiGet<Template[]>("/api/templates"),
  });
}

function useCampaignMutation<T>(send: (arg: T) => Promise<NtfCampaign>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: send,
    onSuccess: (campaign) => {
      client.setQueryData(ntfKeys.one(campaign.id), campaign);
      void client.invalidateQueries({ queryKey: checkinKeys.campaigns });
    },
  });
}

export function useSaveDraft() {
  return useCampaignMutation(({ id, draft }: { id: string | null; draft: Draft }) =>
    id
      ? apiSend<NtfCampaign>("PATCH", `/api/campaigns/${id}`, draft)
      : apiSend<NtfCampaign>("POST", "/api/campaigns", draft),
  );
}

export function useCampaignAction() {
  return useCampaignMutation(
    ({ id, action }: { id: string; action: "submit" | "approve" | "cancel" }) =>
      apiSend<NtfCampaign>("POST", `/api/campaigns/${id}/${action}`, {}),
  );
}

export function useRejectCampaign() {
  return useCampaignMutation(({ id, reason }: { id: string; reason: string }) =>
    apiSend<NtfCampaign>("POST", `/api/campaigns/${id}/reject`, { reason }),
  );
}

export function usePreview() {
  return useMutation({
    mutationFn: (id: string) => apiSend<Preview>("POST", `/api/campaigns/${id}/preview`, {}),
  });
}

export function useTestSend() {
  return useMutation({
    mutationFn: (id: string) => apiSend<Rendered>("POST", `/api/campaigns/${id}/test-send`, {}),
  });
}
