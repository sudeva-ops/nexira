import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiSend } from "./client";

export interface PlaybookStep {
  id: string;
  seq: number;
  name: string;
  action_type: string;
  requires_approval_role: string | null;
}

export interface Playbook {
  id: string;
  code: string;
  name: string;
  category: string;
  version: number;
  trigger_rules: Record<string, unknown>;
  steps: PlaybookStep[];
}

export type StepStatus = "PENDING" | "RUNNING" | "AWAITING_APPROVAL" | "DONE" | "SKIPPED" | "FAILED";
// SCHEDULED and DISARMED: armed runs (PC-24, HZ-05).
export type RunStatus =
  "SCHEDULED" | "RUNNING" | "AWAITING_APPROVAL" | "COMPLETED" | "CANCELLED" | "FAILED" | "DISARMED";

export interface RunStep extends PlaybookStep {
  status: StepStatus;
  started_at: string | null;
  completed_at: string | null;
  approved_by: string | null;
  approved_by_name: string | null;
  result: Record<string, unknown>;
}

export interface PlaybookRun {
  id: string;
  playbook_code: string;
  playbook_name: string;
  incident_id: string | null;
  incident_reference: string | null;
  status: RunStatus;
  started_by_type: "USER" | "AGENT";
  started_by_name: string | null;
  proposal_id: string | null;
  started_at: string;
  scheduled_for: string | null; // an armed run starts by itself then (HZ-05)
  completed_at: string | null;
  steps: RunStep[];
}

export interface Permissions {
  entity_type: string;
  entity_id: string;
  approve_step: string[];
}

export const playbookKeys = {
  playbooks: ["playbooks"] as const,
  runs: ["playbook-runs"] as const,
  run: (id: string) => ["playbook-run", id] as const,
  permissions: ["permissions"] as const,
};

export function usePlaybooks() {
  return useQuery({
    queryKey: playbookKeys.playbooks,
    queryFn: () => apiGet<Playbook[]>("/api/playbooks"),
    staleTime: 60_000,
  });
}

export function useRuns() {
  return useQuery({
    queryKey: playbookKeys.runs,
    queryFn: () => apiGet<PlaybookRun[]>("/api/playbook-runs", { limit: 50 }),
  });
}

export function useRun(id: string | undefined) {
  return useQuery({
    queryKey: playbookKeys.run(id ?? ""),
    queryFn: () => apiGet<PlaybookRun>(`/api/playbook-runs/${id}`),
    enabled: !!id,
  });
}

/** Plan G-07: the steps this user may approve now, from approvals.can_decide(). */
export function useRunPermissions(runId: string | undefined) {
  return useQuery({
    queryKey: [...playbookKeys.permissions, "playbook_run", runId ?? ""],
    queryFn: () =>
      apiGet<Permissions>("/api/me/permissions", {
        entity_type: "playbook_run",
        entity_id: runId ?? "",
      }),
    enabled: !!runId,
  });
}

function useRunMutation<T>(send: (body: T) => Promise<PlaybookRun>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: send,
    onSuccess: (run) => {
      client.setQueryData(playbookKeys.run(run.id), run);
      void client.invalidateQueries({ queryKey: playbookKeys.runs });
      void client.invalidateQueries({ queryKey: playbookKeys.permissions });
    },
  });
}

export function useStartRun() {
  return useRunMutation((body: { playbook_code: string; incident_id: string }) =>
    apiSend<PlaybookRun>("POST", "/api/playbook-runs", body),
  );
}

export function useApproveStep(runId: string) {
  return useRunMutation((stepId: string) =>
    apiSend<PlaybookRun>("POST", `/api/playbook-runs/${runId}/steps/${stepId}/approve`, {}),
  );
}
