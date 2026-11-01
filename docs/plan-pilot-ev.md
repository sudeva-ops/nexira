# Plan · Pilot module 10: Evacuation Management (Prompt 65)

For the product owner and the coding agent. It maps EV-01..10 (`docs/requirements-pilot.md` §49–53) and D-40 onto the code after pilot module 9, and lists the gaps found, each with a proposed answer. Items marked **needs a decision** wait for the product owner; the rest follows from approved documents. Everything is simulated (D-19, D-40); nothing external is called.

## 1. Requirements against existing code

| EV | Exists today | New work | Prompt |
|---|---|---|---|
| 01 Plans | `mission`; partners Atlas (EVACUATION) and Sentinel (SECURE_TRANSPORT) with coverage | PC-30 `evacuation_plan`, seeded for every mission through a service function as `nexira_api` (§2) | 66, 68 |
| 02 Activation | `START_EVACUATION` (level 3, `HEAD_OF_MISSION`, `HQ_CRISIS_DIRECTOR`; the Phase 1 stub writes a note); `approvals.decide()`; `proposal_approval` | PC-31 `evacuation`; `evacuations.service.request()` and `confirm()` through `approvals.decide()`; the executor calls `activate_from_proposal()` instead of the stub, and still writes the note (§3, G-1, G-3) | 66, 67 |
| 03 Manifest | `person.person_type`, `mission_id`; `checkin_response` and `v_checkin_latest`; exposure; `documents.at_risk()` | PC-32 `evacuation_manifest`, inserted once at activation (§4, G-6) | 66, 67 |
| 04 Muster check-in | Redis Streams to worker consumers | `check_in()` by hand (roles through `approvals.py`) and from the simulated scanner (`MUSTER_SCAN`, a new `evacuation` consumer group); seats in check-in order (§5, G-9, G-10) | 67, 68 |
| 05 Sequence | — | `step` 1..6 with database-written times; steps 4–6 by a person or by the scenario's simulated progress (§6, G-2) | 67, 68 |
| 06 Partners and message | `partners.service._insert` (AS-08); `compose.prepare_for_approval`, the D-31 `gate`; `resolve_audience` | partner requests at activation (G-4); the movement message as a PENDING_APPROVAL campaign with the audience `{"evacuation_id": …}` (§7, G-7) | 67 |
| 07 Stand down | `partners.service._move`; `compose` cancel | `stand_down()`, HQ Crisis Director only, before step 5; cancels the open partner requests and an unsent message (§8, G-11) | 67 |
| 08 Screen | Blueprint dark; `ui/motion`; `Kpi`, `Card`; `GET /api/me/permissions` | the screen under RESPOND, after Response Playbooks (§10) | 69 |
| 09 Who sees what | `documents.service._scope` (a union of grants, plan-pilot-dx G-7) | names only within the readers' scope; counts for everyone (§9, G-8) | 67 |
| 10 NBO-EVACUATION | the scenario player and presenter bar | the scenario (§11, G-13) | 68 |

## 2. Plans

`EVP-<code>` for each of the 36 missions, seeded by `evacuations.service.ensure_plans()` from `seed/data.py` (as the health reference data). Options are a JSON array of at most three, in role order PRIMARY, BACKUP, CONTINGENCY. EVP-NBO as the design: muster point "Embassy courtyard" at the chancery; route "Route B"; destination "Dubai"; charter "Wilson Airport → Dubai", 72 seats, Atlas Air Evacuation; commercial "JKIA · 30 seats held", 30, no partner; road "Namanga border → Arusha", no seats, Sentinel Secure Transport. Every other mission gets a charter to a regional safe haven (Atlas where it covers the country, else none), held commercial seats and a road option. Canberra and Buenos Aires have no evacuation partner (the existing coverage gaps, AS-07), so their charter names none and the screen says so.

## 3. Activation (EV-02, D-40)

Two ways, one rule: a Head of Mission (scoped to the mission, or unscoped) and an HQ Crisis Director, two different people.

- **From the screen.** `POST /api/evacuations` `{mission_id}`: the caller holds `HEAD_OF_MISSION` (for the mission) or `HQ_CRISIS_DIRECTOR`, and the mission has an ACTIVE incident (G-6). It inserts a `PENDING_ACTIVATION` evacuation with `requested_by`, `requested_role` (G-1) and the incident. `POST /api/evacuations/{id}/confirm`: a gate `required_role` = the role the requester did not use, `deciders_of_other_steps` = {requester}; `approvals.decide()`; then `_activate()`.
- **From a proposal.** The `START_EVACUATION` executor (`actions._start_evacuation`, 🔒) calls `evacuations.service.activate_from_proposal(session, ctx)`: the incident's mission and plan; `requested_by` = the step 1 decider, `requested_role` = `HEAD_OF_MISSION`, `activated_by` = the step 2 decider (`ctx.approved_by`); the incident note is still written. `approvals.py` has already enforced both steps (D-16).
- **`_activate()`** (both ways, one transaction): status `ACTIVE`, step 2 (decision and manifest), the manifest (§4), the partner requests and the message (§7), audit `EVACUATION.ACTIVATE`, then `EVACUATION_UPDATED` after commit.
- **The database backstop** (PC-31): `activated_by <> requested_by`; one live evacuation per mission (partial unique index).

## 4. The manifest (EV-03)

Inserted once, by `_activate()`, in one statement; the guard refuses later inserts.

- **Mission people:** active `DIPLOMAT` → STAFF, `DELEGATE` → DELEGATE, `DEPENDANT` → DEPENDANT, of the plan's mission. Local staff are not added (§53 Q3).
- **Citizens:** if the incident has a CHECKIN campaign, its citizen recipients whose latest response (`v_checkin_latest`) is not `SAFE`; if it has none, the citizens exposed to the incident (G-6).
- **Document flag:** read live from `documents.at_risk()` (DX-03), not stored.
- Nairobi after NBO-CIVIL-UNREST scenes 1–4: 12 + 3 + 1 = 16, and 4 need help + 40 no reply = 44 citizens. That makes **60**. Hana and Aiko Takeda are flagged.

## 5. Muster check-in and seats (EV-04)

- **By hand:** `POST /api/evacuations/{id}/manifest/{entry_id}/check-in`. The caller holds `SECURITY_OFFICER|CONSULAR_OFFICER|DUTY_OFFICER|HEAD_OF_MISSION` for the mission (`approvals.user_has_role`). `checked_in_by_type` USER.
- **By the scanner:** a `MUSTER_SCAN` scenario event `{mission_code, count}` goes to the worker's `evacuation` group. `check_in_next(count)` checks in the next EXPECTED entries in manifest order, with `checked_in_by_type` SCANNER and `checked_in_by` `muster-scanner (simulated)`.
- **Seats** (G-10): the next free seat of the primary option, labelled `1A, 1B, 1C, 1D, 2A, …`, taken with the evacuation row locked. With no seats left, or no seats on the option, the seat is null and the screen says "No seat".
- **Assembly:** when the last EXPECTED entry is checked in, step 3 is reached. Audit `EVACUATION.CHECK_IN` per person, with no name in the details.

## 6. The sequence (EV-05)

| Step | Reached by |
|---|---|
| 1 Decision to evacuate | activation |
| 2 Manifest confirmed | activation |
| 3 Assembly at muster point | the last check-in, or a person closing it (`advance` to 3) |
| 4 Convoy departed | a person, or `EVACUATION_PROGRESS` step 4 |
| 5 Flight departed | a person, or step 5 |
| 6 Arrival and reception | a person, or step 6: status `COMPLETED`; the evacuation's open partner requests are completed |

`POST /api/evacuations/{id}/advance` `{step}`: the next step only. The caller holds `SECURITY_OFFICER|DUTY_OFFICER|HEAD_OF_MISSION` for the mission. The database writes each step's time into `step_times`. Audit `EVACUATION.STEP`.

## 7. Partners and the movement message (EV-06)

- **Partner requests** (G-4): for the PRIMARY option's partner (EVACUATION) and Sentinel if the plan names it (SECURE_TRANSPORT), each only if it covers the mission's country. They go through `partners.service._insert` with `created_by_type` USER and the activator as `created_by`. The note: `EVN-… · <n> people · muster <name> · <route>`. No names and no person (AS-08).
- **Message** (G-7): template code `EVACUATION_MOVE` (kind ALERT; a Nairobi text and a generic fallback; English reviewed, other languages `REVIEW REQUIRED`, D-15). Channels SMS and APP; audience `{"evacuation_id": id}` (a new `resolve_audience` spec: the manifest's people). It is created `PENDING_APPROVAL`, so nothing is queued:
  - from a proposal: `compose.prepare_for_approval` (author the agent; both deciders excluded by `_proposal_deciders`);
  - from the screen: `created_by_type` USER, `created_by` the requester, `submitted_by` the activator.

  Either way, `compose.gate` lets neither activator approve. A Duty Officer or Consular Officer sends it (D-31).

## 8. Stand down (EV-07)

`POST /api/evacuations/{id}/stand-down` `{reason}`, with a reason of 1 to 500 characters:
- **An ACTIVE evacuation:** only `HQ_CRISIS_DIRECTOR` (unscoped), and only before step 5.
- **A PENDING_ACTIVATION:** either the requester or anyone allowed to confirm it.

It sets STOOD_DOWN (final), cancels the open partner requests (`_move` to CANCELLED, actor the user) and cancels the message if it is still PENDING_APPROVAL. Audit `EVACUATION.STAND_DOWN` with the reason.

## 9. API and who sees what (EV-09)

Every role reads these endpoints:
- `GET /api/evacuations/plans`: the plans and their options.
- `GET /api/evacuations?mission_id=`: evacuations with counts by category and status, and the step times.
- `GET /api/evacuations/{id}`: the same, plus the manifest. Names, categories and document flags appear only within the caller's **name scope** (G-8). For anyone else the entries come back without names.

`GET /api/me/permissions?entity_type=evacuation&entity_id=<mission>` returns `activate`, `confirm`, `check_in`, `advance` and `stand_down`, from the same checks. Browsers get `EVACUATION_UPDATED` `{evacuation_id, mission_id, status, step, checked_in}`. `staleKeys` maps it, `PARTNER_REQUEST_UPDATED` and `INCIDENT_*` to the evacuation keys.

## 10. The screen (EV-08)

- **Banner:**
  - "No active evacuation. Plans are pre-built for every mission.";
  - "Evacuation plan EVP-NBO is ready but not activated" while the mission has an ACTIVE incident, with **Activate evacuation** when `activate` allows it;
  - "Activation requested by … · waiting for <the other role>", with **Confirm activation**;
  - "Evacuation EVP-NBO in progress · n of N checked in";
  - "Evacuation complete".
- **KPIs:**
  - evacuees on manifest (n mission · n citizens);
  - checked in;
  - seats available on the primary option;
  - documents flagged.
- **Manifest:** name, category, travel documents (EXPIRING / VALID), seat, status. In-scope readers see names; others see "On manifest · <category>" counts only.
- **Sequence:** the six steps with times; **Next step** when `advance` allows it.
- **Options:** the plan's three options with their partner and that partner's request status.
- **Mission picker:** defaults to the mission with a live evacuation, else one with an ACTIVE incident.
- **Stand down:** with a reason, when allowed.
- Under RESPOND, after Response Playbooks.

## 11. Scenario `NBO-EVACUATION` (EV-10)

| Scene | Events | Expect |
|---|---|---|
| 0 Ready | — | EVP-NBO ACTIVE from NBO-CIVIL-UNREST scene 5 (else the bar says to play it first) |
| 1 Muster | `MUSTER_SCAN` `{NBO, 2}` every second for 30 s | all 60 checked in, seats 1A–15D; step 3 |
| 2 Convoy | `EVACUATION_PROGRESS` step 4 | convoy departed |
| 3 Charter | step 5 | flight departed |
| 4 Arrival | step 6 | COMPLETED; the partner requests completed |

The simulated progress events act as `SIMULATOR` (labelled simulated) and only move steps. They never activate or stand down an evacuation, and they approve nothing (§53 Q10). Presenter bar: every scene on `/evacuation`.

## 12. Gaps and conflicts, with proposed answers

| # | Gap | Proposed answer |
|---|---|---|
| G-1 | **Who asked first.** EV-02(b) lets either role press Activate; the confirmer must hold the *other* role. PC-31 records `requested_by` but not the role used, and a requester may hold both roles (the `dual.role` test identity). | **Amend PC-31: add `requested_role` (`HEAD_OF_MISSION` or `HQ_CRISIS_DIRECTOR`, frozen).** The confirm gate requires the other role. From a proposal it is `HEAD_OF_MISSION` (policy step 1). *Decided 2026-11-01: as proposed.* |
| G-2 | **Sequence and the simulated partner.** EV-05 says steps 4–6 "follow the simulated partners' requests". But the adapter moves a request to EN_ROUTE about 20 s after it is made, whatever happens, and only a person completes a request. So the convoy would "depart" before anyone mustered. | Steps 4–6 are **marked by a person or by the scenario's simulated progress events** (§6), not by partner status. The partner's status is shown next to its option, and arrival completes the requests. The partner adapter is unchanged (no 🔒 change there). *Decided 2026-11-01: as proposed.* |
| G-3 | **A second START_EVACUATION while one is live** (the scene 5 fixture run twice, `scene5-decisions.spec.ts`). Failing would mark the proposal FAILED after two people approved it. | The executor writes the note and returns the live evacuation (`already_active: true`) instead of failing. With no mission on the incident, it fails as before (`ActionError`). |
| G-4 | **Who requests the partners.** `partner_request.created_by_type` allows USER and PLAYBOOK, and `REQUESTERS` excludes the HQ Crisis Director. | The requests are inserted with `_insert` as USER, by the activator, without the `REQUESTERS` check: two people decided (D-36: "a person with the right role, or … a person approved"). The audit details name the evacuation. No schema change. |
| G-5 | **Existing specs.** Scene 5 now activates EVP-NBO. That adds two partner requests (USER) and a PENDING campaign. | The partners spec looks for the PLAYBOOK standby and the Mass Notification spec looks for its own campaign, so both are unaffected. `test_proposals.py` keeps its note check. The Phase 1 spec gains a check that EVP-NBO is ACTIVE after scene 5. decisions.md §7 scene 5 is updated (D-40 already amends it). |
| G-6 | **No check-in, or no incident.** The manifest's citizens come from the incident's check-in. | Activation needs an ACTIVE incident at the mission (the screen's Activate is hidden otherwise). With no check-in campaign, the incident's exposed citizens are added instead. |
| G-7 | **Template kind.** `message_template.kind` allows ALERT, ADVISORY and CHECKIN. | Kind ALERT, code `EVACUATION_MOVE` (no schema change). |
| G-8 | **Name scope.** EV-09 says "as People & Sites", but People & Sites shows names to every role, and EV-09 hides them from a Viewer. | Names for `DUTY_OFFICER\|SECURITY_OFFICER\|CONSULAR_OFFICER\|HQ_CRISIS_DIRECTOR\|HEAD_OF_MISSION`, within each grant's mission (the Document Expiry scope helper). Viewer, Travel Desk and Admin see counts. |
| G-9 | **Scanner events.** The manifest is only known at activation, so the scenario cannot name people. | `MUSTER_SCAN` carries a count, not names; the worker checks in the next EXPECTED entries. |
| G-10 | **More people than seats.** | Seats run out: the rest get no seat, are still checked in, and the KPI shows it. Nairobi: 60 of 72. |
| G-11 | **Withdrawing a request.** EV-07 covers an ACTIVE evacuation only. | A PENDING_ACTIVATION can be stood down by its requester or by anyone allowed to confirm it, with a reason (§8). |

## 13. Migration 0010 (Prompt 66, 🔒)

Only after PC-30..32 (and G-1, if accepted) are approved:
- `evacuation_plan`: `options` checked by the guard (an array of at most 3; the role, kind, label and seats; same-tenant partners); UNIQUE (tenant, mission).
- `evacuation`: `requested_role` (G-1); `step_times jsonb` written by the guard.
  - Guard:
    - status forward only (PENDING_ACTIVATION → ACTIVE | STOOD_DOWN; ACTIVE → COMPLETED | STOOD_DOWN);
    - step forward by one, and only while ACTIVE;
    - `activated_by` set once, ≠ `requested_by`, and only on the move to ACTIVE;
    - frozen columns.
  - Partial unique index on (tenant, mission) WHERE status IN ('PENDING_ACTIVATION','ACTIVE').
- `evacuation_manifest`. Guard:
  - inserts only into an evacuation that is ACTIVE with step 2, in the transaction that activated it (checked by the evacuation's `activated_at` = `now()`);
  - person in the same tenant and mission;
  - CHECKED_IN final;
  - seat set only with the check-in;
  - nothing changes once the evacuation is final.
- FORCE RLS and `tenant_isolation` on all three, grants as PC-30..32, a pinned `search_path`, and the backup role's SELECT.
- Tests (as `nexira_api`): isolation; every refusal; no DELETE; the downgrade restores 0009 exactly.

## 14. Prompts

| Prompt | Content | 🔒 |
|---|---|---|
| 66 | Migration 0010 (§13) | yes (RLS, grants) |
| 67 | Activation, the executor, manifest, check-in, sequence, partners, message, stand-down, API and permissions | yes (approvals use, the executor) |
| 68 | Plans and templates in the seed; the scanner and progress consumer; NBO-EVACUATION | no |
| 69 | The screen | no |
| 70 | Playwright acceptance (§52) and `make acceptance` | no |

## 15. Decisions by the product owner (2026-11-01, PR #78: "approved")

- G-1: PC-31 gains `requested_role` (`HEAD_OF_MISSION` or `HQ_CRISIS_DIRECTOR`, frozen); the confirmer holds the other role.
- G-2: sequence steps 4–6 are marked by a person or by the scenario's simulated progress events, not by partner status; arrival completes the partner requests. EV-05 reads accordingly.
- G-3..G-11: as proposed.
