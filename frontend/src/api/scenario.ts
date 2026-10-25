import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiSend } from "./client";

export interface Scene {
  scene_no: number;
  name: string;
  expect: string | null;
  events: number;
}

export interface ScenarioState {
  code: string;
  name: string;
  run_id: string;
  status: "IDLE" | "PLAYING" | "PAUSED" | "FINISHED";
  current_scene: number;
  position: number;
  scene_complete: boolean;
  scenes: Scene[];
}

export type ScenarioCommand = "play" | "pause" | "next" | "reset";

export const DEMO_SCENARIO = "NBO-CIVIL-UNREST";

export function useScenario(code: string, enabled: boolean) {
  return useQuery({
    queryKey: ["scenario", code],
    queryFn: () => apiGet<ScenarioState>(`/api/scenarios/${code}`),
    enabled,
    // While a scene plays, follow its progress.
    refetchInterval: (query) => (query.state.data?.status === "PLAYING" ? 1_000 : false),
  });
}

export function useScenarioCommand(code: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (command: ScenarioCommand) =>
      apiSend<ScenarioState>("POST", `/api/scenarios/${code}/${command}`, {}),
    onSuccess: (state) => client.setQueryData(["scenario", code], state),
  });
}
