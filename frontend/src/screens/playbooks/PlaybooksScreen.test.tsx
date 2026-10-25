import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { Me } from "../../api/me";
import type { Playbook, PlaybookRun, RunStep } from "../../api/playbooks";
import { HOM_NAIROBI, INCIDENT, VIEWER } from "../../test/fixtures";
import { DUTY_OFFICER, mockApi, renderApp } from "../../test/render";

const NOW = new Date().toISOString();
const NAMES = [
  ["Confirm incident & severity", "TASK", null],
  ["Notify Head of Mission & Security Attaché", "NOTIFY", null],
  ["Notify HQ Global Operations Centre", "TASK", null],
  ["Issue shelter-in-place advisory & activate BCP-NBO", "NOTIFY", null],
  ["Send safety check-in", "CHECKIN", null],
  ["Place assistance partner on standby", "PARTNER_REQUEST", null],
  ["Approve evacuation route B", "NOTIFY", "HEAD_OF_MISSION"],
  ["Brief leadership", "BRIEFING", null],
] as const;

const PB07: Playbook = {
  id: "pb-07",
  code: "PB-07",
  name: "Civil unrest near mission",
  category: "CIVIL_UNREST",
  version: 1,
  trigger_rules: {},
  steps: NAMES.map(([name, action_type, role], i) => ({
    id: `s${i + 1}`,
    seq: i + 1,
    name,
    action_type,
    requires_approval_role: role,
  })),
};

function runStep(i: number, status: RunStep["status"], result: Record<string, unknown> = {}): RunStep {
  const step = PB07.steps[i];
  if (!step) throw new Error(`no step ${i}`);
  return {
    ...step,
    status,
    started_at: status === "DONE" ? NOW : null,
    completed_at: status === "DONE" ? NOW : null,
    approved_by: null,
    approved_by_name: null,
    result,
  };
}

const RUN: PlaybookRun = {
  id: "run-1",
  playbook_code: "PB-07",
  playbook_name: PB07.name,
  incident_id: INCIDENT.id,
  incident_reference: INCIDENT.reference,
  status: "AWAITING_APPROVAL",
  started_by_type: "USER",
  started_by_name: "Daniel Mercer",
  proposal_id: null,
  started_at: NOW,
  completed_at: null,
  steps: [
    runStep(0, "DONE", { summary: "Fusion engine · sources and confidence confirmed" }),
    runStep(1, "DONE", { reference: "NTF-3101", recipients: 2, channels: ["APP", "SMS", "VOICE"] }),
    runStep(2, "DONE", { summary: "HQ GOC alerted" }),
    runStep(3, "DONE", { reference: "NTF-3102", recipients: 17, channels: ["APP"] }),
    runStep(4, "DONE", { reference: "NTF-3103", recipients: 229, channels: ["APP"] }),
    runStep(5, "DONE", { partner: "Kestrel Medical Assistance", simulated: true }),
    runStep(6, "AWAITING_APPROVAL"),
    runStep(7, "PENDING"),
  ],
};

function setup(me: Me, approvable: string[]) {
  return mockApi({
    "/api/me": { body: me },
    "/api/playbooks": { body: [PB07] },
    "/api/playbook-runs": { body: [RUN] },
    "/api/playbook-runs/run-1": { body: RUN },
    "/api/me/permissions": {
      body: { entity_type: "playbook_run", entity_id: RUN.id, approve_step: approvable },
    },
    "/api/incidents": { body: [] },
    "/api/audit": {
      body: [
        {
          chain_seq: 2,
          occurred_at: NOW,
          actor_type: "SYSTEM",
          actor_id: "playbook.engine",
          action: "PLAYBOOK.STEP_AWAIT_APPROVAL",
          entity_type: "playbook_run",
          entity_id: RUN.id,
          details: { seq: 7 },
          prev_hash: null,
          row_hash: "x",
        },
      ],
    },
    "/api/playbook-runs/run-1/steps/s7/approve": { body: { ...RUN, status: "RUNNING" } },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Response Playbooks", () => {
  it("shows the run's steps with their states and results", async () => {
    setup(DUTY_OFFICER, []);
    renderApp("/playbooks");
    const steps = await screen.findByLabelText("Steps");
    expect(await within(steps).findByTestId("step-2")).toHaveTextContent(
      "NTF-3101 · 2 recipients · APP · SMS · VOICE",
    );
    expect(within(steps).getByTestId("step-5")).toHaveTextContent("NTF-3103 · 229 recipients");
    expect(within(steps).getByTestId("step-6")).toHaveTextContent("(simulated)");
    expect(within(steps).getByTestId("step-7")).toHaveTextContent("Awaiting approval");
    expect(within(steps).getByTestId("step-7")).toHaveTextContent("Requires Head of Mission approval");
    expect(screen.getByText("6/8 complete")).toBeInTheDocument();
    expect(await screen.findByLabelText("Audit trail")).toHaveTextContent(
      "PLAYBOOK.STEP_AWAIT_APPROVAL · step 7",
    );
  });

  it.each([
    ["the Duty Officer", DUTY_OFFICER],
    ["a Viewer", VIEWER],
  ])("hides the approve button from %s (PB-03)", async (_who, me) => {
    setup(me, []);
    renderApp("/playbooks");
    await screen.findByTestId("step-7");
    expect(screen.queryByRole("button", { name: /Approve as/ })).toBeNull();
  });

  it("lets the Nairobi Head of Mission approve step 7", async () => {
    const fetchMock = setup(HOM_NAIROBI, ["s7"]);
    renderApp("/playbooks");
    await userEvent.click(await screen.findByRole("button", { name: "Approve as Head of Mission" }));
    const approvals = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/approve"));
    expect(approvals.map(([url, init]) => [String(url), init?.method])).toEqual([
      ["/api/playbook-runs/run-1/steps/s7/approve", "POST"],
    ]);
  });
});
