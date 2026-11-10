import { useMutation, useQuery } from "@tanstack/react-query";

import { apiSend } from "./client";

// AI Risk Copilot, simulated (Prompts 118-121; COP-01..08, D-50). Answers are grounded on the
// platform's records as the person asking, each sentence citing its sources; the wording is
// rule-based and labelled simulated. The conversation lives in this tab only (COP-06).

export interface Source {
  kind: string; // INCIDENT, CHECKIN, PLAYBOOK_RUN, PROPOSAL, TRIP, MISSION, EXERCISE, CAMPAIGN…
  reference: string;
  href: string;
}

export interface Sentence {
  text: string;
  sources: Source[];
}

export interface Answer {
  kind: string;
  sentences: Sentence[];
  sources: Source[];
  incident_id: string | null; // a REPORT's incident
  label: string;
}

export interface Report {
  incident_id: string;
  reference: string;
  title: string;
  as_of: string;
  sections: { heading: string; sentences: Sentence[]; note: string | null }[];
  sources: Source[];
  label: string;
}

/** The design's suggestions (plan-pilot-cop §6). */
export const SUGGESTIONS = [
  "Summarise the Nairobi situation",
  "Which missions are at elevated risk this week?",
  "Who has not responded to the check-in?",
];

export const copilotKeys = {
  report: (id: string) => ["copilot", "report", id] as const,
  // Not under "copilot": every fetch is an audited export, so nothing refetches it.
  export: (id: string) => ["copilot-export", id] as const,
};

export function useAsk() {
  return useMutation({
    mutationFn: (question: string) => apiSend<Answer>("POST", "/api/copilot/ask", { question }),
  });
}

/** The draft report (not audited; asking for it was). */
export function useReport(incidentId: string | null) {
  return useQuery({
    queryKey: copilotKeys.report(incidentId ?? ""),
    queryFn: () => apiSend<Report>("POST", "/api/copilot/report", { incident_id: incidentId }),
    enabled: Boolean(incidentId),
    staleTime: Infinity, // a draft as of when it was asked for
  });
}

/** COP-04: the print-ready report; each fetch is audited, so once per visit. */
export function useReportExport(incidentId: string) {
  return useQuery({
    queryKey: copilotKeys.export(incidentId),
    queryFn: () =>
      apiSend<Report>("POST", "/api/copilot/report/export", { incident_id: incidentId }),
    staleTime: Infinity,
    gcTime: 0,
    refetchOnWindowFocus: false,
    retry: false,
  });
}
