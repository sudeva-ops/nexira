# Plan · Pilot module 17: After-Action Review (Prompt 106)

For the product owner and the coding agent. It maps AAR-01..09 (`docs/requirements-pilot.md` §84–88) and D-47 onto the code after pilot module 16, and lists the gaps found, each with a proposed answer. Items marked **needs a decision** wait for the product owner. The review is built from what the platform recorded (D-47); rules draft and people decide (§88 Q3, Q4); roles, not names (§88 Q5). Figures quoted from "the demo record" are from a `make acceptance` run on 2026-11-09.

## 1. Requirements against existing code

| AAR | Exists today | New work | Prompt |
|---|---|---|---|
| 01 Start | `incident.status` (ACTIVE, MONITORING, CLOSED), `reference`, `mission_id`; `approvals.require_roles` and the mission-scope check used by playbook gates (D-05, D-06) | PC-49 `after_action_review`; start (§6) | 107, 109 |
| 02 Timeline | `incident_event` (13 types), `agent_proposal` + `proposal_approval` (`required_role`, `decided_at`), `playbook_run_step` + `playbook_step.requires_approval_role`, `notification_campaign.sent_at`; Executive's `timeline_summary()` (G-11) | `aar.service.timeline()`, on read, names removed (§2) | 108 |
| 03 Metrics | Executive's detection → notification and personnel accounted queries; `incident_exposure.computed_at`; `incident_signal` → `raw_signal.received_at` | `aar.service.metrics()` (§3) | 108 |
| 04 Drafts | escalations, exposure confidence, FLEET, SITE and SUPPLY timeline events, `evacuations.documents_flagged()` | eight rules (§4); PC-50 `aar_item` | 107, 108 |
| 05, 06 Decide, finalise | `audit.write`; the Decision Queue's reject reasons | the API (§6) | 109 |
| 07 Export | Executive's audited export and standalone print page | the same pattern (§7) | 109, 110 |
| 08 Screen | Blueprint dark; `Kpi`, `Card`, `nx-table-plain`; the Incidents screen's status actions | `/aar` and the Incidents link (§8) | 110 |
| 09 Demo | NBO-CIVIL-UNREST and the pilot specs that add FLEET, SITE, SUPPLY and evacuation entries to INC-<year>-1042 | the acceptance spec (§9) | 111 |

New backend module: `app/modules/aar/{models,schemas,service,rules,router}`.

## 2. The reconstructed timeline (AAR-02)

Worked out on read and ordered by time. Each entry has a time, a source tag and a sentence **built from the row's type and data, never copied from a summary that may hold a name** (G-1).

| Source | Entries | Text |
|---|---|---|
| `incident_event` SIGNAL, FUSED | first signal, each fused report | provider and severities (no names in these) |
| ESCALATED | severity raised by exposure | "Severity raised to CRITICAL" |
| EXPOSURE | exposure computed | the counts (staff, delegates, citizens, sites, trips) |
| PLAYBOOK_STEP, NOTIFICATION | each step done; campaigns | step name, campaign reference, recipients |
| CHECKIN | a person needs help | "Check-in: a person needs help" (G-11 of Executive) |
| ESCALATION | silent people escalated | person scope → "A person not answering NTF-n was escalated after n s"; citizens scope → the count |
| DECISION | a gate approved | step and the approving **role** from `data`, not the name in the summary |
| STATUS | status changes | "Status ACTIVE → MONITORING" |
| FLEET, SITE, SUPPLY | vehicles, sensors, suppliers | as written (codes, site and supplier names; no person) |
| `agent_proposal` | raised and decided | agent, title, outcome; the deciding role from `proposal_approval.required_role`, or "automatic" |
| NOTE | — | left out: free text may hold anything (as Executive) |

The window runs from the first signal to the review's start, or to `closed_at` if earlier. FLEET, SITE and SUPPLY entries are already on the incident's timeline, so no other module is queried for the timeline.

## 3. The metrics (AAR-03, §88 Q8)

| Metric | Formula | Target | Demo record |
|---|---|---|---|
| Detection → incident | `incident.opened_at` − min `received_at` of its signals | ≤ 5 s | 0 s |
| Incident → exposure | the first EXPOSURE timeline event − `opened_at` (G-8) | ≤ 5 s | 0.03 s |
| Detection → first notification | min `sent_at` of its campaigns − min `received_at` (Executive's query) | < 2 min | 1m 45s, met |
| Decision speed | proposals decided by a person (not AUTO_EXECUTED), `decided_at − created_at`; gates, completed − previous step completed (G-2) | median; the slowest named by title | median 56 s (4 decisions); slowest the document renewal, 3m 56s |
| Personnel accounted | Executive's rule for the incident's CHECKIN campaign, and the time from `sent_at` to the last of those answers | — | 16 of 17, 94%, in 23 s |
| Playbook | PB run `started_at` → `completed_at` | — | 13 s |

- Each metric is `{value_s, target_s, met}` or `null`, which shows as "—".
- Finalising writes the same object to `metrics` (PC-49). A final review reads only what was stored.

## 4. The drafting rules (AAR-04, §88 Q3)

Run once when the review starts. Each rule fires only on evidence in the window and writes one `aar_item` (`DRAFT`, rule code UNIQUE with the review). Evidence is references and counts.

| Code | Fires when | Finding (example) | Action | Team | Priority |
|---|---|---|---|---|---|
| `CHECKIN_SILENT` | an ESCALATION with person scope | "1 staff member did not answer NTF-3103 and was escalated" | Confirm contact details and a second channel for staff who did not answer | HR | HIGH |
| `LOW_CONFIDENCE` | an exposed DIPLOMAT, LOCAL_STAFF, CONTRACTOR or DELEGATE below 80% (G-3) | "1 of 17 staff located below 80% (lowest 55%)" | Enable mobile check-in for staff located from calendar or badge data | SECURITY | HIGH |
| `NOTIFY_LATE` | detection → first notification over 2 min | "First notification after 2m 40s (target 2 min)"; does not fire in the demo (1m 45s) | Review the alert template and its approval for a faster first message | COMMUNICATIONS | MEDIUM |
| `GATE_WAIT` | a gate or proposal waited > 5 min for a person (G-2) | "Run PB-07 waited 6m 10s for a Duty Officer" | Name a deputy for this approval | MISSION_MANAGEMENT | MEDIUM |
| `FLEET_ZONE` | a FLEET entry "entered the impact zone" | "VH-04 entered the impact zone" | Add impact-zone alerts to vehicle routing | FLEET | MEDIUM |
| `SITE_FAULT` | a SITE entry at FAULT or OFFLINE | "Embassy Nairobi: Gate 2 badge reader fault, Camera 7 offline" | Fit backup power and a spare for these devices | FACILITIES | HIGH |
| `SUPPLY_IMPACT` | SUPPLY entries | "3 suppliers impacted (SUP-104, SUP-117, SUP-121)" | Confirm backup suppliers and routes in the continuity plan | LOGISTICS | MEDIUM |
| `DOCS_EXPIRING` | an evacuation at the mission in the window with `documents_flagged > 0` | "2 travel documents could block the evacuation (EVN-1001)" | Check document validity for the evacuation list every quarter | CONSULAR | MEDIUM |

- The label on every draft: "Drafted from the platform record by rules · reviewed by people".
- The finding text is generated; tests assert no seeded person's name is in it (or anywhere in the review).

## 5. Roles (§88 Q7)

Through `approvals.py`, as playbook gates (D-05, D-06):

| Action | Who |
|---|---|
| Read | every role |
| Start; accept, reject, add; mark done | SECURITY_OFFICER, DUTY_OFFICER, HQ_CRISIS_DIRECTOR; HEAD_OF_MISSION of the incident's mission |
| Finalise | SECURITY_OFFICER or HQ_CRISIS_DIRECTOR |

No two-person rule: a review changes nothing outside itself.

## 6. State and the API (AAR-01, AAR-05, AAR-06)

- **Review:** DRAFT → FINAL. Start only at MONITORING or CLOSED (409 otherwise), and once per incident (409). The reference is `AAR-` plus the incident's year and number (`INC-2026-1042` → `AAR-2026-1042`).
- **Item:** DRAFT → ACCEPTED (team, due date, optional reword) or REJECTED (reason from the Decision Queue's list or free text); ACCEPTED → DONE. A reviewer's own item is inserted ACCEPTED (rule code null).
- **Finalise:** refused while any item is DRAFT; it freezes the metrics. On a FINAL review only ACCEPTED → DONE is allowed. The database guard enforces the same rules (PC-50).
- **Endpoints:**
  - `GET /api/aar`: the reviews, plus incidents ready for one;
  - `POST /api/aar`: `{incident_id}`;
  - `GET /api/aar/{id}`: the review, timeline, metrics and items;
  - `POST /api/aar/{id}/items`;
  - `POST /api/aar/items/{id}/accept`, `/reject`, `/done`;
  - `POST /api/aar/{id}/finalise`;
  - `POST /api/aar/{id}/export`.
- **Audit:** `AAR.START`, `AAR.ITEM_ACCEPT`, `AAR.ITEM_REJECT`, `AAR.ITEM_ADD`, `AAR.ITEM_DONE`, `AAR.FINALISE`, `AAR.EXPORT`, each through `audit.py`.
- **Realtime:** `AAR_UPDATED {review_id}`, ids only, forwarded to the browser.

## 7. Export (AAR-07, §88 Q9)

As Executive's briefing:
- `POST /api/aar/{id}/export` returns the review and writes `AAR.EXPORT`;
- `/aar/{id}/print` is a standalone page (no shell) that fetches once and offers "Print / save as PDF";
- it holds the metrics, the timeline and the accepted, rejected and done actions, "Simulated data" and the time produced; no names;
- no file is stored on the server.

## 8. The screen (AAR-08, §88 Q10)

- **Nav entry:** "After-Action Review" (`/aar`, icon `endorsed`, subtitle "Learning · Timeline, lessons & actions") under PLAN & INSIGHT, after Predictive Risk.
- **Left column:** reviews (reference, incident, status, actions accepted out of total), then "Ready for review" incidents with "Start review" for reviewers.
- **The selected review:**
  - banner ("After-action review · INC-… · built from the platform record");
  - four KPIs, as the design: detection → first alert, alert → notification, personnel accounted, actions accepted;
  - the other metrics with met or missed;
  - "Reconstructed timeline";
  - "Lessons & actions" (finding, action, team, priority, due date, status), with Accept (team, date, reword), Reject (reason), Add, Done;
  - "Finalise" and "Export review".
- **Incidents screen:** "Start after-action review" on a MONITORING or CLOSED incident for reviewers, or "Open AAR-…" once one exists.
- **Empty state:** "No incident to review yet."
- **Realtime:** AAR_UPDATED and INCIDENT_UPDATED refetch it.

## 9. Acceptance (§87)

- **Order (G-4):** later pilot specs set INC-<year>-1042 back to ACTIVE, so the review spec runs **after all other specs**, as a second Playwright command in `make acceptance`.
- **The spec, `aar-acceptance.spec.ts`:**
  - **refused while ACTIVE:** a Duty Officer cannot start a review while the incident is ACTIVE;
  - **start:** the Duty Officer sets INC-<year>-1042 to MONITORING (as scene 6 does), then starts AAR-<year>-1042 from Incidents;
  - **the review:** the timeline holds the fusion, exposure, PB-07 steps with the Head of Mission role, the notifications, the check-in and the decisions, and no seeded name; the metrics agree with the Phase 1 numbers and Executive's figure;
  - **the drafts:** at least `CHECKIN_SILENT`, `LOW_CONFIDENCE`, `FLEET_ZONE`, `SITE_FAULT`, `SUPPLY_IMPACT` and `DOCS_EXPIRING`, which the earlier specs produce;
  - **decisions:** two accepted with teams and dates, one rejected, one added; Finalise is refused while drafts remain; the remaining drafts are decided and the Security Officer finalises; marking done works and any other change is refused;
  - **export and roles:** the export is audited with no names; the Viewer reads and cannot act; the chain verifies.
- **The Phase 1 spec is unchanged.**

## 10. Gaps and conflicts, with proposed answers

| # | Gap | Proposed answer |
|---|---|---|
| G-1 | Some timeline summaries name a person: CHECKIN ("Hana Takeda needs help"), person-scope ESCALATION ("… has not answered NTF-3103") and DECISION ("approved by Layla Haddad") | Build every entry's text from its type and `data` (§2); leave NOTE out; a test runs the timeline over the demo seed and checks no `person.full_name` or `app_user.display_name` appears |
| G-2 | `playbook_run_step.started_at` is set when a gate is approved, so a gate's recorded wait is 0 s. In the demo, step 7 is approved about 2 s after step 6 | Measure a gate's wait from the previous step's completion. With a 5-minute threshold `GATE_WAIT` does not fire in the demo, so **§87 and AAR-09 change**: the drafts include the escalated person and the module findings, and step 7 shows in the timeline and decision speed. **Decided: 5 minutes** (PR #135) |
| G-3 | 212 of 229 exposed people in the demo are citizens with confidence below 80% | `LOW_CONFIDENCE` counts staff and delegates only (1 of 17 in the demo); citizens are the consular team's, via the check-in |
| G-4 | Later specs (Document Expiry onwards) set INC-<year>-1042 back to ACTIVE; Playwright orders files by name, and `aar-` would run first | Run the review spec as a second command after all others in `make acceptance`; it sets MONITORING itself through the Incidents status action (audited), as scene 6 does |
| G-5 | A rule's evidence may change after the review starts (e.g. a late answer) | Drafts are written once at the start; the timeline and metrics keep updating until finalised, then freeze. No re-drafting in the pilot |
| G-6 | The design's "Drafted by AI · reviewed by Security" | "Drafted from the platform record by rules · reviewed by people" (§88 Q3) |
| G-7 | 🔒 scope | Prompt 107 (migration: RLS, grants, guards) is 🔒. The API only calls `approvals.py` and `audit.py`, so Prompt 109 is not |
| G-8 | `incident_exposure.computed_at` is rewritten each time exposure is recomputed (in the demo record its earliest value is 310 s after the incident opened) | Time the exposure from the first EXPOSURE timeline event, which is written once (0.03 s in the demo) |

## 11. Migration 0016 (Prompt 107, 🔒)

- **The tables:** PC-49 `after_action_review` and PC-50 `aar_item`.
  - FORCE RLS with `tenant_isolation`; only the grants proposed; no DELETE.
  - CHECKs on the status, team and priority lists, and `status <> 'REJECTED' OR reason IS NOT NULL`.
- **Pinned `search_path` guards:**
  - same-tenant incident, review and users;
  - one review per incident;
  - DRAFT → FINAL once, with the metrics required when final;
  - item transitions as §6, and only DONE on a FINAL review;
  - `started_at`, `finalised_at`, `decided_at` and `done_at` written by the database;
  - finding, rule code, evidence and review frozen once decided.
- **Tests (as `nexira_api`):** isolation, every refusal, the backup role reads, and the downgrade restores 0015 exactly.

## 12. Prompts

As `docs/prompts-pilot.md` Prompts 107–111.

## 13. Decisions by the product owner (2026-11-09, PR #135: "approved to keep 5 minutes")

- G-2: the gate-wait threshold stays at 5 minutes, measured from the previous step's completion. AAR-09 and §87 are reworded to match.
- G-1, G-3..G-8: as proposed.
