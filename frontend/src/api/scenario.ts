import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

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

/** The demo scenarios the presenter bar offers; the first is the default. */
export const DEMO_SCENARIOS = [
  { code: "NBO-CIVIL-UNREST", label: "Nairobi civil unrest" },
  { code: "FRA-NATIONAL-PROTESTS", label: "France protests" },
  { code: "NBO-AIR-DIVERSION", label: "Inbound flight diversion" },
  { code: "MNL-TROPICAL-STORM", label: "Manila tropical storm" },
  { code: "DAC-CYCLONE", label: "Dhaka cyclone" },
  { code: "NBO-CHOLERA", label: "Nairobi cholera" },
  { code: "NBO-EVACUATION", label: "Nairobi evacuation" },
  { code: "NBO-FLEET", label: "Nairobi fleet" },
  { code: "ADD-VISIT", label: "Protection programme" },
  { code: "NBO-SITE", label: "Nairobi embassy site" },
  { code: "NBO-SUPPLY", label: "Nairobi supply chain" },
  { code: "ADD-FORECAST", label: "Addis Ababa forecast" },
] as const;
export type DemoScenario = (typeof DEMO_SCENARIOS)[number]["code"];
export const DEMO_SCENARIO: DemoScenario = DEMO_SCENARIOS[0].code;

export function useScenario(code: string, enabled: boolean) {
  return useQuery({
    queryKey: ["scenario", code],
    queryFn: () => apiGet<ScenarioState>(`/api/scenarios/${code}`),
    enabled,
    // Switching scenarios keeps the bar on screen until the new state arrives.
    placeholderData: keepPreviousData,
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
