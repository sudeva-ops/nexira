import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { Answer, Report } from "../../api/copilot";
import { INCIDENT } from "../../test/fixtures";
import { DUTY_OFFICER, mockServer, type Reply, renderApp } from "../../test/render";

const LABEL = "Simulated copilot · rule-based wording · simulated data";
const INC = { kind: "INCIDENT", reference: "INC-2026-1042", href: "/incidents?id=inc-1042" };
const NTF = { kind: "CHECKIN", reference: "NTF-3103", href: "/checkin?campaign=c-3103" };

const SITUATION: Answer = {
  kind: "SITUATION",
  sentences: [
    { text: "INC-2026-1042, civil unrest at Nairobi CBD: CRITICAL, active.", sources: [INC] },
    { text: "Check-in NTF-3103: of 17 personnel, 15 safe, 1 need help and 1 not yet answered.", sources: [NTF] },
  ],
  sources: [INC, NTF],
  incident_id: null,
  label: LABEL,
};

const REPORT_ANSWER: Answer = {
  kind: "REPORT",
  sentences: [{ text: "Here is a draft situation report for INC-2026-1042.", sources: [INC] }],
  sources: [INC],
  incident_id: "inc-1042",
  label: LABEL,
};

const REPORT: Report = {
  incident_id: "inc-1042",
  reference: "INC-2026-1042",
  title: "Situation report · INC-2026-1042 · Civil unrest · Nairobi CBD",
  as_of: new Date().toISOString(),
  sections: [
    { heading: "Summary", sentences: [{ text: "Civil unrest, severity CRITICAL.", sources: [INC] }], note: null },
    { heading: "Our people", sentences: [{ text: "15 safe of 17.", sources: [NTF] }], note: null },
    {
      heading: "Recommendations",
      sentences: [{ text: "Reassess at the next check-in or on escalation.", sources: [INC] }],
      note: "Rule-based recommendations from the record",
    },
  ],
  sources: [INC, NTF],
  label: LABEL,
};

function setup(extra: Record<string, Reply> = {}) {
  return mockServer({
    "GET /api/me": { body: DUTY_OFFICER },
    "GET /api/proposals": { body: [] },
    "GET /api/incidents": { body: [INCIDENT] },
    "GET /api/campaigns": { body: [{ id: "c-3103", campaign_type: "CHECKIN" }] },
    "GET /api/playbook-runs": { body: [] },
    "GET /api/missions": { body: [] },
    "GET /api/exercises/running": { body: [] },
    ...extra,
  });
}

const asked = (fetchMock: ReturnType<typeof setup>, path: string) =>
  fetchMock.mock.calls
    .filter(([url, init]) => String(url) === path && init?.method === "POST")
    .map(([, init]) => init?.body);

afterEach(() => vi.unstubAllGlobals());

describe("AI Risk Copilot", () => {
  it("opens empty, with the suggestions, the grounding context and the guardrails", async () => {
    setup();
    renderApp("/copilot");
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("AI Risk Copilot");
    expect(screen.getByText("How can I help the operations centre?")).toBeInTheDocument();
    expect(within(screen.getByLabelText("Suggestions")).getAllByRole("button")).toHaveLength(3);
    const grounding = screen.getByLabelText("Grounding context");
    await within(grounding).findByText("Active incidents");
    expect(within(grounding).getByText("Safety check-ins").closest("li")).toHaveClass("on");
    expect(within(grounding).getByText("Playbook runs").closest("li")).not.toHaveClass("on");
    expect(screen.getByLabelText("Guardrails")).toHaveTextContent("Every answer cites its sources");
  });

  it("answers a suggestion with cited sentences, each source linking to its record", async () => {
    const fetchMock = setup({ "POST /api/copilot/ask": { body: SITUATION } });
    renderApp("/copilot");
    await userEvent.click(await screen.findByRole("button", { name: "Summarise the Nairobi situation" }));
    const answer = await screen.findByLabelText("Answer");
    await within(answer).findByText(/15 safe, 1 need help/);
    expect(within(answer).getByRole("link", { name: "INC-2026-1042" })).toHaveAttribute(
      "href",
      "/incidents?id=inc-1042",
    );
    expect(within(answer).getByRole("link", { name: "NTF-3103" })).toHaveAttribute("href", "/checkin?campaign=c-3103");
    expect(answer).toHaveTextContent(LABEL);
    expect(asked(fetchMock, "/api/copilot/ask")).toEqual([
      JSON.stringify({ question: "Summarise the Nairobi situation" }),
    ]);
  });

  it("asks a typed question and drafts a situation report with an export, never a send", async () => {
    const fetchMock = setup({
      "POST /api/copilot/ask": { body: REPORT_ANSWER },
      "POST /api/copilot/report": { body: REPORT },
    });
    renderApp("/copilot");
    await userEvent.type(await screen.findByLabelText("Question"), "Draft a situation report for Nairobi{Enter}");
    const report = await screen.findByLabelText("Situation report");
    expect(report).toHaveTextContent(REPORT.title);
    expect(report).toHaveTextContent("Recommendations · Rule-based recommendations from the record");
    expect(within(report).getByRole("link", { name: "Export as PDF" })).toHaveAttribute(
      "href",
      "/copilot/report/inc-1042/print",
    );
    expect(screen.queryByRole("button", { name: /send/i })).toBeNull();
    expect(asked(fetchMock, "/api/copilot/report")).toEqual([JSON.stringify({ incident_id: "inc-1042" })]);
    expect(asked(fetchMock, "/api/copilot/report/export")).toEqual([]); // drafting is not an export
  });

  it("shows an error instead of an answer when the question fails", async () => {
    setup({ "POST /api/copilot/ask": { status: 422, body: { detail: "Question too long" } } });
    renderApp("/copilot");
    await userEvent.type(await screen.findByLabelText("Question"), "x{Enter}");
    expect(await within(await screen.findByLabelText("Answer")).findByText(/Question too long|went wrong/)).toBeInTheDocument();
  });

  it("exports the report once for print, with no shell", async () => {
    const fetchMock = setup({ "POST /api/copilot/report/export": { body: REPORT } });
    renderApp("/copilot/report/inc-1042/print");
    const page = await screen.findByTestId("copilot-print");
    expect(within(page).getByRole("heading", { level: 1 })).toHaveTextContent(REPORT.title);
    expect(page).toHaveTextContent("Reassess at the next check-in or on escalation. [INC-2026-1042]");
    expect(page).toHaveTextContent("INC-2026-1042 · NTF-3103");
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(asked(fetchMock, "/api/copilot/report/export")).toHaveLength(1);
  });
});
