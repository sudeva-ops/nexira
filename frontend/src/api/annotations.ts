import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { LineString, Point, Polygon } from "geojson";

import { apiGet, apiSend } from "./client";

// Map annotations (Prompts 127-129; ANN-01..06, D-52): marks, lines and areas people draw on the
// world map. Every role reads them; the API says who may add (can_add) and change (can_edit).
// The author is shown by role only (ANN-04).

export type AnnotationKind = "MARK" | "LINE" | "AREA";
export type AnnotationSymbol = "CHECKPOINT" | "CLOSED_ROAD" | "RALLY_POINT" | "HAZARD" | "NOTE";
export type Shape = Point | LineString | Polygon;

export interface Annotation {
  id: string;
  kind: AnnotationKind;
  symbol: AnnotationSymbol | null;
  shape: Shape;
  label: string;
  note: string | null;
  incident_id: string | null;
  incident_reference: string | null;
  mission_code: string | null;
  ends_at: string | null;
  status: "ACTIVE" | "WITHDRAWN";
  reason: string | null;
  role: string;
  created_at: string;
  updated_at: string | null;
  can_edit: boolean;
}

export interface Annotations {
  annotations: Annotation[];
  can_add: boolean;
}

export interface AnnotationBody {
  kind: AnnotationKind;
  symbol: AnnotationSymbol | null;
  shape: Shape;
  label: string;
  note: string | null;
  incident_id: string | null;
  ends_at: string | null;
}

export type AnnotationEdit = Partial<Pick<AnnotationBody, "label" | "note" | "ends_at" | "shape">>;

export const SYMBOL_LABEL: Record<AnnotationSymbol, string> = {
  CHECKPOINT: "Checkpoint",
  CLOSED_ROAD: "Closed road",
  RALLY_POINT: "Rally point",
  HAZARD: "Hazard",
  NOTE: "Note",
};

export const annotationKeys = {
  all: ["annotations"] as const, // what realtime invalidates
  list: (incidentId: string | null) => ["annotations", "list", incidentId ?? "all"] as const,
};

/** "Checkpoint", "Area": what it is, without its free text. */
export function annotationWhat(a: Pick<Annotation, "kind" | "symbol">): string {
  return a.symbol ? SYMBOL_LABEL[a.symbol] : a.kind === "LINE" ? "Line" : "Area";
}

export function useAnnotations(incidentId: string | null = null) {
  return useQuery({
    queryKey: annotationKeys.list(incidentId),
    queryFn: () =>
      apiGet<Annotations>("/api/annotations", incidentId ? { incident_id: incidentId } : undefined),
  });
}

function useAnnotationMutation<V>(request: (v: V) => Promise<Annotation>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: request,
    onSuccess: () => void client.invalidateQueries({ queryKey: annotationKeys.all }),
  });
}

export const useAddAnnotation = () =>
  useAnnotationMutation((body: AnnotationBody) => apiSend<Annotation>("POST", "/api/annotations", body));

export const useEditAnnotation = () =>
  useAnnotationMutation(({ id, body }: { id: string; body: AnnotationEdit }) =>
    apiSend<Annotation>("PATCH", `/api/annotations/${id}`, body),
  );

export const useWithdrawAnnotation = () =>
  useAnnotationMutation(({ id, reason }: { id: string; reason: string }) =>
    apiSend<Annotation>("POST", `/api/annotations/${id}/withdraw`, { reason }),
  );
