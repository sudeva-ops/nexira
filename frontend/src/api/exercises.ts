import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiSend } from "./client";

// Exercise & Training (Prompts 113-117; EXR-01..09, D-48). An exercise is a scenario run in
// EXERCISE mode on the live engine; people respond through the normal screens, and everything
// it produces is labelled EXERCISE and left out of leadership figures. It is scored from the
// record when it ends, and the scores are frozen. The backend decides every action through
// app/core/approvals.py and says what the caller may do (can_launch, can_act).

export type Kind = "TABLETOP" | "FUNCTIONAL" | "FULL_SCALE";
export type Dimension =
  | "DETECTION"
  | "ACCOUNTABILITY"
  | "DECISION_SPEED"
  | "COMMUNICATION"
  | "PLAN_ADHERENCE";

export const KINDS: Kind[] = ["TABLETOP", "FUNCTIONAL", "FULL_SCALE"];

export interface Kpis {
  this_year: number;
  average: number | null;
  average_last_year: number | null;
  took_part: number;
  personnel: number;
  templates: number;
}

export interface ExerciseSummary {
  id: string;
  name: string;
  kind: Kind;
  status: "RUNNING" | "COMPLETED" | "ABANDONED";
  source: "EXERCISE" | "ILLUSTRATIVE";
  mission_id: string;
  mission_code: string;
  scenario_code: string | null;
  incident_id: string | null;
  incident_reference: string | null;
  overall_score: number | null;
  participants: number | null;
  started_at: string;
  ended_at: string | null;
}

export interface Score {
  dimension: Dimension;
  score: number | null; // null is "—"
  measured: Record<string, unknown>;
}

export interface Run {
  status: "IDLE" | "PLAYING" | "PAUSED" | "FINISHED";
  current_scene: number;
  scenes: { scene_no: number; name: string }[]; // never the expected result (plan §2)
}

export interface Exercise extends ExerciseSummary {
  reason: string | null;
  scores: Score[];
  run: Run | null;
  can_act: boolean;
}

export interface Template {
  code: string;
  name: string;
  mission_id: string;
  mission_code: string;
  theme: string;
  scenes: number;
  running: boolean;
  can_launch: boolean;
}

export interface Exercises {
  kpis: Kpis;
  exercises: ExerciseSummary[];
}

export const exerciseKeys = {
  all: ["exercises"] as const, // what realtime invalidates
  list: ["exercises", "list"] as const,
  templates: ["exercises", "templates"] as const,
  running: ["exercises", "running"] as const,
  exercise: (id: string) => ["exercises", "one", id] as const,
};

export const DIMENSION_LABEL: Record<Dimension, string> = {
  DETECTION: "Detection → alert",
  ACCOUNTABILITY: "Accountability (check-in)",
  DECISION_SPEED: "Decision speed",
  COMMUNICATION: "Communication",
  PLAN_ADHERENCE: "Plan adherence",
};

/** "Full scale" from FULL_SCALE. */
export function kindLabel(kind: Kind): string {
  const words = kind.toLowerCase().replace(/_/g, " ");
  return words[0]?.toUpperCase() + words.slice(1);
}

/** The design's amber below 80 (plan §8). */
export const LOW_SCORE = 80;

export function useExercises() {
  return useQuery({
    queryKey: exerciseKeys.list,
    queryFn: () => apiGet<Exercises>("/api/exercises"),
  });
}

export function useTemplates() {
  return useQuery({
    queryKey: exerciseKeys.templates,
    queryFn: () => apiGet<Template[]>("/api/exercises/templates"),
  });
}

/** The header banner's: every running exercise (plan §4). */
export function useRunning() {
  return useQuery({
    queryKey: exerciseKeys.running,
    queryFn: () => apiGet<ExerciseSummary[]>("/api/exercises/running"),
  });
}

export function useExercise(id: string | undefined) {
  return useQuery({
    queryKey: exerciseKeys.exercise(id ?? ""),
    queryFn: () => apiGet<Exercise>(`/api/exercises/${id ?? ""}`),
    enabled: Boolean(id),
  });
}

function useExerciseMutation<V>(request: (v: V) => Promise<Exercise>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: request,
    onSuccess: (exercise) => {
      client.setQueryData(exerciseKeys.exercise(exercise.id), exercise);
      void client.invalidateQueries({ queryKey: exerciseKeys.all });
    },
  });
}

export const useLaunch = () =>
  useExerciseMutation((body: { template: string; kind: Kind }) =>
    apiSend<Exercise>("POST", "/api/exercises", body),
  );

export const useNextInject = () =>
  useExerciseMutation((id: string) =>
    apiSend<Exercise>("POST", `/api/exercises/${id}/next`, {}),
  );

export const useEnd = () =>
  useExerciseMutation((id: string) =>
    apiSend<Exercise>("POST", `/api/exercises/${id}/end`, {}),
  );

export const useAbandon = () =>
  useExerciseMutation(({ id, reason }: { id: string; reason: string }) =>
    apiSend<Exercise>("POST", `/api/exercises/${id}/abandon`, { reason }),
  );
