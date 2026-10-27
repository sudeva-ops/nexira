import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiSend } from "./client";

export type ProposalStatus =
  | "PENDING"
  | "APPROVED"
  | "EDITED_APPROVED"
  | "REJECTED"
  | "AUTO_EXECUTED"
  | "UNDONE"
  | "EXPIRED"
  | "SUPERSEDED"
  | "FAILED";

export interface Alternative {
  label: string;
  action_type: string;
  action_payload: Record<string, unknown>;
  rationale: string;
}

export interface ApprovalStep {
  step_no: number;
  required_role: string;
  decision: "APPROVE" | "REJECT" | null;
  decided_by: string | null;
  decided_by_name: string | null;
  decided_at: string | null;
}

export interface Proposal {
  id: string;
  agent_code: string;
  agent_name: string;
  incident_id: string | null;
  incident_reference: string | null;
  proposal_key: string;
  action_type: string;
  title: string;
  proposed_action: string;
  action_payload: Record<string, unknown>;
  evidence: { text: string; source: string }[];
  alternatives: Alternative[];
  risk_if_no_action: string | null;
  confidence: number | null;
  is_proactive: boolean;
  effective_level: number; // set by the database (D-12)
  status: ProposalStatus;
  superseded_by: string | null;
  edited_action: string | null;
  edited_payload: Record<string, unknown> | null;
  rejection_reason: string | null;
  deadline_at: string | null;
  undo_until: string | null;
  created_at: string;
  decided_at: string | null;
  executed_at: string | null;
  approvals: ApprovalStep[];
  can_decide: boolean;
  can_edit: boolean; // the server decides: editable type, and you decide step 1
  can_dismiss: boolean;
  can_undo: boolean;
}

/** One action type an agent proposes, with its policy (D-12, D-16; TA-09). */
export interface AgentAction {
  action_type: string;
  level: number; // the policy floor; 4 (advise only) with no policy
  approver_roles: string[]; // one entry per step
  decision_deadline_s: number | null;
}

export const ACTION_LABEL: Record<string, string> = {
  LOG_INFO: "Log information",
  POST_INTERNAL_NOTE: "Internal note",
  START_PLAYBOOK: "Start a playbook",
  SEND_EXTERNAL_MESSAGE: "Citizen advisory",
  START_EVACUATION: "Evacuation",
  NOTIFY_TRAVELLERS: "Notify a trip's travellers",
  CANCEL_TRIP: "Cancel a trip",
  ADVISE_REBOOKING: "Onward travel advice",
};

/** The trip and flight a travel proposal is about (D-34), read from its payload. */
export function travelLinks(p: Pick<Proposal, "action_payload">): { trip?: string; flight?: string } {
  const { trip_id: trip, flight_id: flight } = p.action_payload;
  return {
    ...(typeof trip === "string" ? { trip } : {}),
    ...(typeof flight === "string" ? { flight } : {}),
  };
}

export interface AgentRow {
  code: string;
  name: string;
  description: string | null;
  watches: string[];
  actions: AgentAction[];
  autonomy_level: number;
  is_enabled: boolean;
  model_ref: string | null;
  proposals_pending: number;
  proposals_total: number;
  accepted_pct: number | null;
}

export interface AgentsState {
  paused: boolean;
  agents: AgentRow[];
}

export interface Activity {
  occurred_at: string;
  actor: string;
  action: string;
  proposal_id: string | null;
  text: string;
}

// D-12/D-13 levels, as the demo names them.
export const LEVELS = ["Auto", "Auto + notice", "Approve", "Senior approval", "Advise only"] as const;
export const LEVEL_COLOUR = ["#72CA9B", "#8ABBFF", "#FBB360", "#FA999C", "#BDADFF"] as const;

export const proposalKeys = {
  proposals: ["proposals"] as const,
  agents: ["agents"] as const,
  activity: ["agents", "activity"] as const,
};

export function useProposals() {
  return useQuery({
    queryKey: proposalKeys.proposals,
    queryFn: () => apiGet<Proposal[]>("/api/proposals", { limit: 200 }),
  });
}

/** DQ-07: the header pill. */
export function usePendingCount() {
  const { data } = useProposals();
  return data?.filter((p) => p.status === "PENDING").length ?? 0;
}

export function useAgents() {
  return useQuery({
    queryKey: proposalKeys.agents,
    queryFn: () => apiGet<AgentsState>("/api/agents"),
  });
}

export function useAgentActivity() {
  return useQuery({
    queryKey: proposalKeys.activity,
    queryFn: () => apiGet<Activity[]>("/api/agents/activity", { limit: 40 }),
  });
}

function useProposalMutation<T>(send: (body: T) => Promise<unknown>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: send,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: proposalKeys.proposals });
      void client.invalidateQueries({ queryKey: proposalKeys.agents });
    },
  });
}

export type Decision =
  | { kind: "approve" }
  | { kind: "edit"; edited_action?: string; edited_payload?: Record<string, unknown> }
  | { kind: "reject"; reason: string }
  | { kind: "alternative"; index: number }
  | { kind: "undo" };

export function useDecide(id: string) {
  return useProposalMutation((d: Decision) => {
    const base = `/api/proposals/${id}`;
    switch (d.kind) {
      case "approve":
        return apiSend("POST", `${base}/approve`, {});
      case "edit":
        return apiSend("POST", `${base}/edit-approve`, {
          edited_action: d.edited_action ?? null,
          edited_payload: d.edited_payload ?? null,
        });
      case "reject":
        return apiSend("POST", `${base}/reject`, { reason: d.reason });
      case "alternative":
        return apiSend("POST", `${base}/use-alternative`, { index: d.index });
      case "undo":
        return apiSend("POST", `${base}/undo`, {});
    }
  });
}

export function useSetAutonomy() {
  return useProposalMutation((v: { code: string; autonomy_level: number }) =>
    apiSend("PATCH", `/api/agents/${v.code}`, { autonomy_level: v.autonomy_level }),
  );
}

export function useKillSwitch() {
  return useProposalMutation((pause: boolean) =>
    apiSend("POST", pause ? "/api/agents/pause-all" : "/api/agents/resume-all", {}),
  );
}
