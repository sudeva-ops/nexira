import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { DocumentPermissions, DocumentSummary, TravelDocument } from "../../api/documents";
import type { Me } from "../../api/me";
import { staleKeys } from "../../api/realtimeClient";
import { eventLabel } from "../../app/eventLabel";
import { HOM_NAIROBI, MISSIONS, NBO_ID, VIEWER } from "../../test/fixtures";
import { DUTY_OFFICER, mockServer, type Reply, renderApp } from "../../test/render";

const doc = (id: string, name: string, change: Partial<TravelDocument> = {}): TravelDocument => ({
  id,
  person_id: `p-${id}`,
  holder_name: name,
  holder_type: "DIPLOMAT",
  mission_id: NBO_ID,
  mission_code: "NBO",
  doc_type: "DIPLOMATIC_PASSPORT",
  issuing_country: "AE",
  valid_until: "2026-11-21",
  days_left: 21,
  urgency: "CRITICAL",
  holder_ready: false,
  could_block_evacuation: true,
  renewal_status: "NONE",
  renewal_requested_by: null,
  renewal_requested_at: null,
  renewal_started_by: null,
  renewal_started_at: null,
  renewed_by: null,
  renewed_at: null,
  can_act: true,
  simulated: true,
  ...change,
});
const HANA = doc("d-hana", "Hana Takeda");
const AIKO = doc("d-aiko", "Aiko Takeda", {
  holder_type: "DEPENDANT",
  doc_type: "PASSPORT",
  days_left: 12,
  valid_until: "2026-11-12",
});
const PARIS = doc("d-par", "Fictional Diplomat P", {
  mission_id: "m-par",
  mission_code: "PAR",
  doc_type: "VISA",
  issuing_country: "FR",
  days_left: 60,
  urgency: "HIGH",
  could_block_evacuation: false,
  renewal_status: "IN_PROGRESS",
  renewal_started_by: "system:seed",
  renewal_started_at: "2026-10-30T08:00:00Z",
  can_act: false,
});
const FINE = doc("d-ok", "Fictional Attaché", {
  days_left: 900,
  urgency: "OK",
  holder_ready: true,
  could_block_evacuation: false,
});
const SUMMARY: DocumentSummary = {
  tracked: 4812,
  expiring_30: 6,
  expiring_90: 31,
  in_renewal_90: 19,
  could_block: 2,
  people: 1338,
  ready: 1320,
  ready_pct: 98.7,
  missions: [],
  simulated: true,
};
const READ_ALL: DocumentPermissions = {
  read_documents: true,
  act_documents: true,
  read_document_missions: null,
  act_document_missions: null,
};

function setup(me: Me, permissions: DocumentPermissions, extra: Record<string, Reply> = {}) {
  return mockServer({
    "GET /api/me": { body: me },
    "GET /api/proposals": { body: [] },
    "GET /api/missions": { body: [...MISSIONS, { ...MISSIONS[0], id: "m-par", code: "PAR", city: "Paris" }] },
    "GET /api/me/permissions": { body: permissions },
    "GET /api/documents/summary": { body: SUMMARY },
    "GET /api/documents": { body: [HANA, AIKO, PARIS, FINE] },
    ...extra,
  });
}

function sent(fetchMock: ReturnType<typeof mockServer>, path: string): unknown[] {
  return fetchMock.mock.calls
    .filter(([url, init]) => String(url) === path && init?.method === "POST")
    .map(([, init]) => JSON.parse(String(init?.body)) as unknown);
}

const rowOf = (name: string) => screen.getByText(name).closest("tr") as HTMLElement;

afterEach(() => vi.unstubAllGlobals());

describe("Document Expiry", () => {
  it("shows the KPIs from the summary (DX-08)", async () => {
    setup(DUTY_OFFICER, READ_ALL);
    renderApp("/documents");
    expect(await screen.findByText("98.7%")).toBeInTheDocument();
    expect(screen.getByText("2 could block evacuation")).toBeInTheDocument();
    expect(screen.getByText("Renewal in progress: 19")).toBeInTheDocument();
    expect(screen.getByText("1320 of 1338 people · passport valid 180+ days")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Document Expiry/ })).toBeInTheDocument();
    expect(screen.getByText("PLAN & INSIGHT")).toBeInTheDocument();
  });

  it("lists expiring documents, most urgent first, with impact and renewal (DX-02, DX-03)", async () => {
    setup(DUTY_OFFICER, READ_ALL);
    renderApp("/documents");
    const table = await screen.findByRole("table", { name: "Expiring documents" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getByText(/Takeda|Fictional/).textContent)).toEqual([
      "Hana Takeda",
      "Aiko Takeda",
      "Fictional Diplomat P",
    ]); // OK documents are hidden by default
    expect(rows[0]).toHaveTextContent("Diplomatic passport");
    expect(rows[0]).toHaveTextContent("CRITICAL");
    expect(rows[0]).toHaveTextContent("Could block evacuation");
    expect(rows[0]).toHaveTextContent("Not started");
    expect(rows[2]).toHaveTextContent("Renewal due");
    expect(rows[2]).toHaveTextContent("Renewal in progress");
    expect(screen.getByText(/simulated/)).toBeInTheDocument();
  });

  it("filters by mission and type through the API, and by urgency", async () => {
    const fetchMock = setup(DUTY_OFFICER, READ_ALL);
    renderApp("/documents");
    await screen.findByRole("table", { name: "Expiring documents" });
    await userEvent.selectOptions(screen.getByLabelText("Filter by mission"), "PAR");
    await userEvent.selectOptions(screen.getByLabelText("Filter by document type"), "VISA");
    await userEvent.selectOptions(screen.getByLabelText("Filter by urgency"), "HIGH");
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([url]) => {
          const u = String(url);
          return (
            u.startsWith("/api/documents?") &&
            u.includes("mission_id=m-par") &&
            u.includes("doc_type=VISA") &&
            u.includes("urgency=HIGH")
          );
        }),
      ).toBe(true),
    );
    await userEvent.selectOptions(screen.getByLabelText("Filter by urgency"), "ANY");
    expect(await screen.findByText("Fictional Attaché")).toBeInTheDocument(); // every document, OK too
  });

  it("offers renewal steps only where the row allows it, and sends them (DX-04)", async () => {
    const fetchMock = setup(DUTY_OFFICER, READ_ALL, {
      "POST /api/documents/d-hana/renewal": { body: { ...HANA, renewal_status: "IN_PROGRESS" } },
      "POST /api/documents/d-aiko/renewal": { body: { ...AIKO, renewal_status: "RENEWED" } },
      "GET /api/documents": {
        body: [HANA, { ...AIKO, renewal_status: "IN_PROGRESS", renewal_started_by: DUTY_OFFICER.id }, PARIS],
      },
    });
    renderApp("/documents");
    await screen.findByRole("table", { name: "Expiring documents" });
    expect(within(rowOf("Fictional Diplomat P")).queryByRole("button")).toBeNull(); // can_act false
    await userEvent.click(within(rowOf("Hana Takeda")).getByRole("button", { name: "Start renewal" }));
    expect(sent(fetchMock, "/api/documents/d-hana/renewal")).toEqual([{ step: "IN_PROGRESS" }]);

    const aiko = rowOf("Aiko Takeda");
    expect(aiko).toHaveTextContent("Renewal in progress by you");
    await userEvent.click(within(aiko).getByRole("button", { name: "Mark renewed" }));
    expect(within(aiko).getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(within(aiko).getByLabelText("New valid-until date"), "2036-11-12");
    await userEvent.click(within(aiko).getByRole("button", { name: "Save" }));
    expect(sent(fetchMock, "/api/documents/d-aiko/renewal")).toEqual([{ step: "RENEWED", valid_until: "2036-11-12" }]);
  });

  it("sends renewal reminders for the selected documents (DX-05)", async () => {
    const fetchMock = setup(DUTY_OFFICER, READ_ALL, {
      "POST /api/documents/reminders": {
        status: 201,
        body: { campaign_id: "c-1", reference: "NTF-3110", recipients: 2, documents: 2 },
      },
    });
    renderApp("/documents");
    await screen.findByRole("table", { name: "Expiring documents" });
    expect(screen.getByRole("button", { name: "Send renewal reminders" })).toBeDisabled();
    expect(screen.queryByLabelText(/Select Fictional Diplomat P/)).toBeNull(); // not theirs to act on
    await userEvent.click(screen.getByLabelText("Select every document you can act on"));
    await userEvent.click(screen.getByRole("button", { name: "Send renewal reminders (2)" }));
    expect(sent(fetchMock, "/api/documents/reminders")).toEqual([{ document_ids: ["d-hana", "d-aiko"] }]);
    expect(await screen.findByText(/REMINDERS SENT · NTF-3110 · 2 recipients/)).toBeInTheDocument();
  });

  it("says why when the backend refuses", async () => {
    setup(DUTY_OFFICER, READ_ALL, {
      "POST /api/documents/d-hana/renewal": { status: 409, body: { detail: "The holder is no longer active" } },
    });
    renderApp("/documents");
    await screen.findByRole("table", { name: "Expiring documents" });
    await userEvent.click(within(rowOf("Hana Takeda")).getByRole("button", { name: "Request renewal" }));
    expect(await screen.findByText("The holder is no longer active")).toBeInTheDocument();
  });

  it("gives a Head of Mission their own missions in the filter", async () => {
    setup(HOM_NAIROBI, { ...READ_ALL, read_document_missions: [NBO_ID], act_document_missions: [NBO_ID] });
    renderApp("/documents");
    await screen.findByRole("table", { name: "Expiring documents" });
    const options = within(screen.getByLabelText("Filter by mission")).getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual(["My missions", "NBO"]);
  });

  it("shows a Viewer the KPIs only, never the list (DX-09)", async () => {
    const fetchMock = setup(VIEWER, {
      read_documents: false,
      act_documents: false,
      read_document_missions: null,
      act_document_missions: null,
    });
    renderApp("/documents");
    expect(await screen.findByText("Totals only")).toBeInTheDocument();
    expect(screen.getByText("98.7%")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByText("Hana Takeda")).toBeNull();
    expect(screen.queryByRole("button", { name: /Send renewal reminders/ })).toBeNull();
    const paths = fetchMock.mock.calls.map(([url]) => String(url).split("?")[0]);
    expect(paths).not.toContain("/api/documents");
  });

  it("refetches the register and trips on DOCUMENT_UPDATED, labelled in the header", () => {
    const keys = staleKeys({ type: "event", event: "DOCUMENT_UPDATED", id: "e", occurred_at: "", data: {} });
    expect(keys).toEqual([["documents"], ["trips"]]);
    expect(eventLabel("DOCUMENT_UPDATED")).toBe("Document updated");
  });
});
