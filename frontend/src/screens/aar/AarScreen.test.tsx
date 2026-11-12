import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { Item, Review, Reviews } from "../../api/aar";
import { teamLabel } from "../../api/aar";
import { VIEWER } from "../../test/fixtures";
import {
  DUTY_OFFICER,
  mockServer,
  type Reply,
  renderApp,
} from "../../test/render";

const NOW = new Date().toISOString();
const draft = (rule: string, extra: Partial<Item> = {}): Item => ({
  id: `i-${rule}`,
  rule_code: rule,
  finding: `${rule} finding`,
  action: `${rule} action`,
  owner_team: "SECURITY",
  priority: "HIGH",
  evidence: {},
  status: "DRAFT",
  due_on: null,
  reason: null,
  decided_at: null,
  done_at: null,
  ...extra,
});

const REVIEW: Review = {
  id: "r-1042",
  reference: "AAR-2026-1042",
  incident_id: "inc-1042",
  incident_reference: "INC-2026-1042",
  incident_title: "Civil unrest",
  incident_status: "MONITORING",
  status: "DRAFT",
  started_at: NOW,
  finalised_at: null,
  label: "Drafted from the platform record by rules · reviewed by people",
  metrics: [
    {
      key: "detection_to_incident",
      label: "Detection → incident",
      value: 0,
      unit: "s",
      target: 5,
      met: true,
      detail: null,
    },
    {
      key: "detection_to_notification",
      label: "Detection → first notification",
      value: 105,
      unit: "s",
      target: 120,
      met: true,
      detail: null,
    },
    {
      key: "decision_slowest",
      label: "Decision speed · slowest",
      value: 400,
      unit: "s",
      target: 300,
      met: false,
      detail: "Step 7 · Approve evacuation route B · Head of Mission",
    },
    {
      key: "personnel_accounted",
      label: "Personnel accounted",
      value: 94,
      unit: "%",
      target: null,
      met: null,
      detail: "16 of 17 · NTF-3103 · in 22 s",
    },
    {
      key: "playbook",
      label: "Playbook · started → completed",
      value: null,
      unit: "s",
      target: null,
      met: null,
      detail: null,
    },
  ],
  timeline: [
    { at: NOW, source: "INCIDENT", text: "Opened from Dataminr: High → HIGH." },
    {
      at: NOW,
      source: "DECISION",
      text: "Step 7 · Approve evacuation route B: approved by the Head of Mission.",
    },
  ],
  items: [
    draft("CHECKIN_SILENT", { owner_team: "HR" }),
    draft("SITE_FAULT", { owner_team: "FACILITIES" }),
    draft("FLEET_ZONE", {
      status: "ACCEPTED",
      owner_team: "FLEET",
      due_on: "2026-12-09",
      priority: "MEDIUM",
    }),
  ],
  can_act: true,
  can_finalise: true,
  simulated: true,
};
const LIST: Reviews = {
  reviews: [
    {
      id: REVIEW.id,
      reference: REVIEW.reference,
      incident_reference: REVIEW.incident_reference,
      incident_title: REVIEW.incident_title,
      status: "DRAFT",
      started_at: NOW,
      accepted: 1,
      drafts: 2,
      items: 3,
    },
  ],
  ready: [
    {
      incident_id: "inc-1077",
      reference: "INC-2026-1077",
      title: "Flooding",
      status: "CLOSED",
      can_start: true,
    },
  ],
};

function setup(me = DUTY_OFFICER, extra: Record<string, Reply> = {}) {
  return mockServer({
    "GET /api/me": { body: me },
    "GET /api/proposals": { body: [] },
    "GET /api/aar": { body: LIST },
    "GET /api/aar/r-1042": { body: REVIEW },
    ...extra,
  });
}

const posts = (fetchMock: ReturnType<typeof setup>, path: string) =>
  fetchMock.mock.calls.filter(
    ([url, init]) => String(url) === path && init?.method === "POST",
  );

afterEach(() => vi.unstubAllGlobals());

describe("After-Action Review", () => {
  it("opens the first review: figures, metrics, lessons and the timeline, with no name", async () => {
    setup();
    renderApp("/aar");
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent(
      "After-Action Review",
    );
    const note = await screen.findByRole("note");
    expect(note).toHaveTextContent(
      "After-action review AAR-2026-1042 · INC-2026-1042 · Civil unrest.",
    );
    expect(screen.getByText("1 / 3")).toBeInTheDocument(); // actions accepted
    expect(screen.getAllByText("94%")).toHaveLength(2); // the KPI and the metrics table
    const metrics = screen.getByRole("table", { name: "Response metrics" });
    expect(
      within(metrics).getByText("Decision speed · slowest").closest("tr"),
    ).toHaveTextContent("6m 40starget 5m 00sMISSED");
    expect(
      within(metrics).getByText("Detection → first notification").closest("tr"),
    ).toHaveTextContent("MET");
    expect(
      within(metrics).getByText("Playbook · started → completed").closest("tr"),
    ).toHaveTextContent("—");
    expect(screen.getByLabelText("Reconstructed timeline")).toHaveTextContent(
      "approved by the Head of Mission",
    );
    const lessons = screen.getByRole("table", { name: "Lessons and actions" });
    expect(
      within(lessons).getAllByRole("button", { name: "Accept" }),
    ).toHaveLength(2);
    expect(lessons.querySelector('[data-item="FLEET_ZONE"]')).toHaveTextContent(
      "Fleet",
    );
    expect(screen.getByText(REVIEW.label)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Finalise" })).toBeDisabled(); // 2 drafts left
    expect(document.body).not.toHaveTextContent("Daniel Mercer Approved");
  });

  it("accepts a draft with a team, a due date and a reworded action", async () => {
    const fetchMock = setup(DUTY_OFFICER, {
      "POST /api/aar/items/i-CHECKIN_SILENT/accept": { body: REVIEW },
    });
    renderApp("/aar");
    const row = (
      await screen.findByRole("table", { name: "Lessons and actions" })
    ).querySelector('[data-item="CHECKIN_SILENT"]') as HTMLElement;
    await userEvent.click(within(row).getByRole("button", { name: "Accept" }));
    const form = screen.getByLabelText("Accept CHECKIN_SILENT");
    await userEvent.selectOptions(
      within(form).getByLabelText("Owner team"),
      "SECURITY",
    );
    const action = within(form).getByLabelText("Action");
    await userEvent.clear(action);
    await userEvent.type(action, "Add a second channel");
    await userEvent.click(
      within(form).getByRole("button", { name: "Confirm" }),
    );
    const [call] = posts(fetchMock, "/api/aar/items/i-CHECKIN_SILENT/accept");
    const body = JSON.parse(String(call?.[1]?.body)) as Record<string, string>;
    expect(body.owner_team).toBe("SECURITY");
    expect(body.action).toBe("Add a second channel");
    expect(body.due_on).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("rejects a draft with a reason and finalises once nothing is left", async () => {
    const decided: Review = {
      ...REVIEW,
      items: REVIEW.items.map((i) =>
        i.status === "DRAFT"
          ? { ...i, status: "REJECTED", reason: "Not needed" }
          : i,
      ),
    };
    const fetchMock = setup(DUTY_OFFICER, {
      "POST /api/aar/items/i-SITE_FAULT/reject": { body: decided },
      "POST /api/aar/r-1042/finalise": {
        body: {
          ...decided,
          status: "FINAL",
          finalised_at: NOW,
          can_finalise: false,
        },
      },
    });
    renderApp("/aar");
    const row = (
      await screen.findByRole("table", { name: "Lessons and actions" })
    ).querySelector('[data-item="SITE_FAULT"]') as HTMLElement;
    await userEvent.click(within(row).getByRole("button", { name: "Reject" }));
    await userEvent.click(
      within(screen.getByLabelText("Reject reason")).getByRole("button", {
        name: "Not needed",
      }),
    );
    expect(
      JSON.parse(
        String(
          posts(fetchMock, "/api/aar/items/i-SITE_FAULT/reject")[0]?.[1]?.body,
        ),
      ),
    ).toEqual({
      reason: "Not needed",
    });
    const finalise = await screen.findByRole("button", { name: "Finalise" });
    expect(finalise).toBeEnabled();
    await userEvent.click(finalise);
    expect(await screen.findByRole("note")).toHaveTextContent(
      "the metrics are frozen",
    );
    expect(posts(fetchMock, "/api/aar/r-1042/finalise")).toHaveLength(1);
  });

  it("adds a lesson of a reviewer's own", async () => {
    const fetchMock = setup(DUTY_OFFICER, {
      "POST /api/aar/r-1042/items": { status: 201, body: REVIEW },
    });
    renderApp("/aar");
    await userEvent.click(
      await screen.findByRole("button", { name: "Add lesson" }),
    );
    const form = screen.getByLabelText("Add a lesson");
    await userEvent.type(
      within(form).getByLabelText("Finding"),
      "The hotline was busy",
    );
    await userEvent.type(
      within(form).getByLabelText("New action"),
      "Open the portal earlier",
    );
    await userEvent.selectOptions(
      within(form).getByLabelText("Team"),
      "CONSULAR",
    );
    await userEvent.click(within(form).getByRole("button", { name: "Add" }));
    const body = JSON.parse(
      String(posts(fetchMock, "/api/aar/r-1042/items")[0]?.[1]?.body),
    ) as Record<string, string>;
    expect([body.finding, body.action, body.owner_team, body.priority]).toEqual(
      ["The hotline was busy", "Open the portal earlier", "CONSULAR", "MEDIUM"],
    );
  });

  it("lets the Viewer read and nothing more", async () => {
    setup(VIEWER, {
      "GET /api/aar": {
        body: { ...LIST, ready: [{ ...LIST.ready[0], can_start: false }] },
      },
      "GET /api/aar/r-1042": {
        body: { ...REVIEW, can_act: false, can_finalise: false },
      },
    });
    renderApp("/aar");
    await screen.findByRole("table", { name: "Lessons and actions" });
    for (const name of [
      "Accept",
      "Reject",
      "Add lesson",
      "Finalise",
      "Done",
      "Start review",
    ]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    expect(
      screen.getByRole("button", { name: "Export review" }),
    ).toBeInTheDocument();
  });

  it("starts a review from an incident ready for one", async () => {
    const fetchMock = setup(DUTY_OFFICER, {
      "GET /api/aar": { body: { reviews: [], ready: LIST.ready } },
      "POST /api/aar": { status: 201, body: { ...REVIEW, id: "r-1077" } },
      "GET /api/aar/r-1077": { body: { ...REVIEW, id: "r-1077" } },
    });
    renderApp("/aar");
    expect(
      await screen.findByText(/^No incident to review yet\. A review is built/),
    ).toBeInTheDocument();
    // DC-01: the screen's figures, at rest
    const figures = screen.getByRole("group", { name: "Review figures" });
    expect(figures).toHaveTextContent(`Reviews00 draft · 0 final`);
    expect(figures).toHaveTextContent(`Ready for review${LIST.ready.length}`);
    await userEvent.click(
      await screen.findByRole("button", { name: "Start review" }),
    );
    expect(
      JSON.parse(String(posts(fetchMock, "/api/aar")[0]?.[1]?.body)),
    ).toEqual({ incident_id: "inc-1077" });
  });

  it("exports a print-ready review once, an audited export with no shell", async () => {
    const fetchMock = setup(VIEWER, {
      "POST /api/aar/r-1042/export": { body: REVIEW },
    });
    renderApp("/aar/r-1042/print");
    const page = await screen.findByTestId("aar-print");
    expect(within(page).getByRole("heading", { level: 1 })).toHaveTextContent(
      "After-action review AAR-2026-1042",
    );
    expect(page).toHaveTextContent("Simulated data");
    expect(
      within(page).getByRole("table", { name: "Review actions" }),
    ).toHaveTextContent("Fleet");
    expect(
      within(page).getByRole("table", { name: "Review actions" }),
    ).not.toHaveTextContent("CHECKIN_SILENT finding");
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(posts(fetchMock, "/api/aar/r-1042/export")).toHaveLength(1);
  });
});

describe("aar helpers", () => {
  it("labels teams", () => {
    expect(["HR", "IT", "MISSION_MANAGEMENT", "FLEET"].map(teamLabel)).toEqual([
      "HR",
      "IT",
      "Mission management",
      "Fleet",
    ]);
  });
});
