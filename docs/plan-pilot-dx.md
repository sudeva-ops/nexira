# Plan · Pilot module 7: Document Expiry (Prompt 48)

For the product owner and the coding agent. It maps DX-01..09 (`docs/requirements-pilot.md` §34–38) and D-37 onto the code after the UI motion work, and lists the gaps found, each with a proposed answer. Items marked **needs a decision** wait for the product owner; the rest follows from approved documents. Documents are simulated (D-19, D-37); no document numbers, scans or photos are stored.

## 1. Requirements against existing code

| DX | Exists today | New work | Prompt |
|---|---|---|---|
| 01 Register | `person` (type, mission) | `travel_document` (PC-23); `app/modules/documents` model, `GET /api/documents`; seed (§8) | 49, 50 |
| 02 Urgency | nothing | `urgency()` in the service, from days left on the UTC date (§3) | 50 |
| 03 Readiness | mission display risk (D-08), active incidents | `travel_ready()` per person; mission and overall share; the "could block evacuation" flag (§3) | 50 |
| 04 Renewal | nothing | forward-only renewal enforced by the guard (§6); `POST /api/documents/{id}/renewal`; `DOCUMENT_UPDATED` to browsers | 49, 50 |
| 05 Reminders | staff campaigns; `audience_filter` with `trip_id` (TA-05) | a `document_ids` audience in `notifications.resolve_audience` (§5); `POST /api/documents/reminders` | 50 |
| 06 Trips warn | trip detail, checklist (JR-05) | `document_warnings` on the trip detail and a checklist note; never blocks approval | 50, 51 |
| 07 Compliance agent | the agent framework; Travel & Air as the pattern | `agents/agents/compliance.py`, action `START_DOCUMENT_RENEWAL` and its executor, policy seed (§4) | 50 🔒 |
| 08 Screen | Blueprint screens, `ui/motion` | `screens/documents/DocumentsScreen.tsx`, nav entry under PLAN & INSIGHT (the design) | 51 |
| 09 Who sees what | `approvals.user_has_role`, mission scope (D-05) | list and summary scoped by role (§2); Viewer gets the summary only | 50, 51 |

## 2. Who may do what

| Action | Roles | Scope |
|---|---|---|
| Read the list (`GET /api/documents`) | DUTY_OFFICER, SECURITY_OFFICER, CONSULAR_OFFICER, HQ_CRISIS_DIRECTOR, TRAVEL_DESK, ADMIN | all missions |
| | HEAD_OF_MISSION | their own mission only |
| | VIEWER | 403; the screen shows the summary only |
| Read the summary (`GET /api/documents/summary`) | every role | a Head of Mission's summary covers their mission |
| Renewal steps, reminders | CONSULAR_OFFICER, DUTY_OFFICER | any mission |
| | HEAD_OF_MISSION | own mission (D-05) |

All role checks go through `app/core/approvals.py` (`user_has_role` with the mission), as partners do. A user with roles in several scopes sees the union.

## 3. Rules

- **Days left** = `valid_until − current_date` in UTC (as trips use UTC dates, plan-pilot-ast G-5).
- **Urgency:** `< 0` EXPIRED; `< 30` CRITICAL; `< 90` HIGH; a PASSPORT or DIPLOMATIC_PASSPORT with `< 180` MODERATE; otherwise OK. Boundaries: 29 → CRITICAL, 30 → HIGH; 89 → HIGH, 90 → MODERATE (passport) or OK; 179 → MODERATE, 180 → OK.
- **Travel-ready:** the person holds a PASSPORT or DIPLOMATIC_PASSPORT with at least 180 days left (§38 Q3). Population: active DIPLOMAT, LOCAL_STAFF, DEPENDANT, CONTRACTOR.
- **Could block evacuation:** a passport-type document whose holder is not travel-ready, in a mission whose display risk is HIGH or CRITICAL or that has an ACTIVE incident. Visas, permits, accreditations and clearances are never flagged (G-4).
- **A renewal in progress** (REQUESTED or IN_PROGRESS) does not make a person travel-ready; only RENEWED with a new date does.

## 4. The Compliance agent (Prompt 50, 🔒)

`app/modules/agents/agents/compliance.py`, modelled on `travel_air.py`:
- **Observes** `EXPOSURE_COMPUTED` (after every incident change, with its final severity) and `INCIDENT_UPDATED`.
- **Proposes** `START_DOCUMENT_RENEWAL` when the incident's mission meets the "could block evacuation" condition (§3) and at least one document there is flagged. Payload: the flagged document ids, plus the reminder message (a fixed English text, no LLM, AGT-09).
- **Evidence:** each document's holder, type and days left; "a passport needs 180 days left to count as travel-ready"; the mission's risk and the incident. **Alternative:** "Issue emergency travel documents only if needed" (ADVISE_EMERGENCY_DOCUMENTS, advice only, level 4). `is_proactive = true`.
- **One open proposal per mission:** `proposal_key = DX:<mission id>:<incident id>`. A re-observed event is harmless; the same mission in a later incident gets a new proposal only if documents are still flagged.
- **Policy** (seed, not schema): `START_DOCUMENT_RENEWAL`, floor 2, approvers `CONSULAR_OFFICER|DUTY_OFFICER`, not undoable, deadline 3600 s (the design). Agent row `COMPLIANCE`, "Compliance", autonomy 2.
- **Executor:** for each document still at NONE, the renewal step REQUESTED through `documents.service` (actor the agent, approver recorded, as `CANCEL_TRIP`); then one reminders campaign through `notifications.create_campaign` with the `document_ids` audience. Documents already in renewal are skipped and named in the result.

## 5. Reminders and the "document holders" audience

- `{"document_ids": [...]}` in `resolve_audience`: the active holders of those documents, ordered by id, de-duplicated. Refused for any CITIZEN or DELEGATE holder (the guard also refuses such documents, so this is a backstop), and if the list is empty.
- Campaign type `ADVISORY`, channels APP and EMAIL (simulated). Staff-only, so the author sends it without a second person (MN-05, §38 Q2).
- Message: "Your travel document expires soon. Please start the renewal with the consular section." One text for everyone in the campaign; naming each holder's own document and date is not done in the pilot (G-6).

## 6. Data and the guard trigger (Prompt 49, 🔒)

As PC-23, with these details:
- `renewal_status` table: NONE → REQUESTED → IN_PROGRESS → RENEWED; NONE → IN_PROGRESS is allowed (the consular section started it directly); nothing goes back; RENEWED is final until the next document (a renewed document keeps its row with its new `valid_until`, and a later renewal is a new cycle, G-3).
- `valid_until` changes only on the move to RENEWED and only to a later date.
- `renewal_requested_at`, `renewal_started_at`, `renewed_at` are written **by the trigger**, never by the app (the Prompt 24 lesson).
- Who did each step: see **G-1 (needs a decision)**.
- Person, type and issuing country are frozen. A row is inserted only with `renewal_status = 'NONE'`.
- The holder must be same-tenant and of type DIPLOMAT, LOCAL_STAFF, DEPENDANT or CONTRACTOR.
- `SET search_path = pg_catalog, public, pg_temp` (the Prompt 39 lesson).
- Index `(tenant_id, valid_until)` and `(tenant_id, person_id)`.

## 7. API

- `GET /api/documents?mission_id=&doc_type=&urgency=&limit=`: the list with holder name and type, mission code, days left, urgency, flag, renewal (who and when).
- `GET /api/documents/summary`: tracked, expiring < 30, expiring < 90, in renewal among those, travel-ready share overall and per mission.
- `POST /api/documents/{id}/renewal` `{"step": "REQUESTED"|"IN_PROGRESS"|"RENEWED", "valid_until": date}`; clear 409 messages checked before the guard (the Prompt 45 lesson), the guard as the backstop.
- `POST /api/documents/reminders` `{"document_ids": [...]}` → the campaign.
- `GET /api/me/permissions` gains `documents: {read, act}` (and the missions they apply to).
- Trip detail gains `document_warnings`.
- Event `DOCUMENT_UPDATED` (document id, mission id), forwarded to browsers; the screen refetches.
- Audit: `DOCUMENT.RENEWAL_REQUESTED`, `DOCUMENT.RENEWAL_STARTED`, `DOCUMENT.RENEWED`, `DOCUMENT.REMINDERS`.

## 8. Seed (§38 Q1)

- Every active DIPLOMAT, LOCAL_STAFF, DEPENDANT and CONTRACTOR gets **exactly one** passport-type document (DIPLOMAT: DIPLOMATIC_PASSPORT; others: PASSPORT). DIPLOMATs also get an ACCREDITATION; DEPENDANTs a RESIDENCE_PERMIT; CONTRACTORs a VISA. About 2,600 documents.
- Expiry dates are drawn from a SHA-256 digest of the person id (no `random`, and nothing is drawn from the world generator's rng, so every other seeded figure stays where it is). They are then adjusted so that **exactly 6** documents expire within 30 days (2 in Nairobi) and **31** within 90 days (the design's KPIs); about 19 of the 31 are moved to IN_PROGRESS through the service (actor SYSTEM `seed`).
- Nairobi: **Hana Takeda's** diplomatic passport, 21 days; her child's passport, 12 days (G-2). No other Nairobi person has a document under 180 days, so the D-23 figures and the Phase 1 acceptance do not move.
- Dates are relative to the seed date, so `make reset-demo` gives the same days left every time.
- Seeded through the service layer as `nexira_api` with `ensure_documents` (new rows only), like partners (plan-pilot-ast G-12).

## 9. Gaps and conflicts, with proposed answers

**G-1 · Who did each renewal step (needs a decision).** PC-23 as approved grants UPDATE on `renewal_status` and `valid_until` only, and says the guard writes the who columns "from `app.user_id`". There is no `app.user_id` setting today, and adding one changes `app/core/db.py` and every transaction (D-02). **Proposal:** also `GRANT UPDATE (renewal_requested_by, renewal_started_by, renewed_by)`; the guard requires the matching column to be set, and only on its own transition, and freezes it afterwards. The app writes the user (or the approver, for the agent); the database writes the time. This amends PC-23.

**G-2 · Hana Takeda's child (needs a decision).** Nairobi has no dependants in the seed, and adding a person would move the "1,338 personnel" KPI (plan G-10). **Proposal:** take the last generated DEPENDANT of another mission (no rng draw), move them to NBO, name them "Aiko Takeda" (fictional), and place them at a home outside the incident zone, so the D-23 exposure (229 people) and the check-in figures (15 / 1 / 1) do not change. Nairobi's mission headcount rises by one; that mission's count is not asserted anywhere.

**G-3 · A second renewal of the same document.** RENEWED is final in the pilot. A later renewal (years on) is out of scope; if needed, a new row for the new document.

**G-4 · Which documents block evacuation.** Only passport-type documents. A lapsed accreditation or visa is urgent but does not stop a person boarding a flight out.

**G-5 · Proposal timing in the demo.** §38 Q7 says "after scene 3". The agent observes `EXPOSURE_COMPUTED`, which first arrives in **scene 2** (the incident becomes CRITICAL). **Proposal:** the proposal appears in scene 2, next to PB-07. The Phase 1 spec checks that PB-07 and the Exposure note exist, not that they are the only proposals, so it keeps passing. The presenter notes for scene 3 mention it.

**G-6 · Per-person reminder text.** The notification service sends one message per campaign. **Proposal:** a general text in the pilot ("your travel document expires soon"); each holder's own document and date come with per-recipient templates later.

**G-7 · A Head of Mission with several roles.** The union of their scopes (§2), as everywhere else.

**G-8 · Older tenants.** `ensure_documents` adds documents on the next seed; until then the screen is empty and the agent finds nothing.

**G-9 · Navigation.** The design puts Document Expiry under PLAN & INSIGHT. The app has no such group yet. **Proposal:** add the group with this one screen; later modules (Predictive Risk, Executive Overview) join it.

## 10. Migration 0007 (Prompt 49, 🔒)

- PC-23 `travel_document` as §6, FORCE RLS, `tenant_isolation`, SELECT and INSERT for `nexira_app`, the column UPDATE grants (with G-1), no DELETE; the guard trigger.
- The backup role reads it (default privileges).
- Downgrade drops the table, trigger and function and restores the exact previous ACL.

## 11. Decisions needed from the product owner

1. **G-1:** grant UPDATE on the three "who" columns, the guard checking them (amends PC-23).
2. **G-2:** Hana Takeda's child is an existing generated dependant moved to Nairobi, outside the zone.

Everything else follows from D-37 and §38.
