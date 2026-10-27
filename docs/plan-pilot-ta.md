# Plan · Pilot module 4: Travel & Air agent (Prompt 33)

For the product owner and the coding agent. It maps TA-01..09 (`docs/requirements-pilot.md` §19–23) and D-34 onto the agent framework (D-12 to D-17) and the travel modules, and lists the gaps found, each with a proposed answer. Items marked **needs a decision** wait for the product owner; the rest follows from approved documents.

## 1. Requirements against existing code

| TA | Exists today | New work | Prompt |
|---|---|---|---|
| 01 Disrupted flight → notify | `FLIGHT_UPDATED` after every status change and every recorded delay (payload: flight id, status, trip id) | `TravelAir.observe` on `FLIGHT_UPDATED`: reads the flight; HOLDING, DIVERTED, CANCELLED, or `delay_min` ≥ 60 → NOTIFY_TRAVELLERS | 35 |
| 02 Onward travel advice | level 4 = no policy row (D-12) | ADVISE_REBOOKING for DIVERTED and CANCELLED; no policy, no executor | 34, 35 |
| 03 Trip in an incident → notify | `EXPOSURE_COMPUTED` after every exposure run; `trips.impacted_by()` | on `EXPOSURE_COMPUTED`: the incident's impacted PENDING/APPROVED trips → NOTIFY_TRAVELLERS with `incident_id` | 35 |
| 04 Risk rose → cancel or notify | `trips.destination_risks()`, `risk_changed` (JR-07) | on `EXPOSURE_COMPUTED` (it follows every incident change and carries the final severity): APPROVED trips in the incident's mission country whose live risk is HIGH or CRITICAL and above `approved_risk_level`: not started → CANCEL_TRIP with the notify alternative (D-14); started → NOTIFY_TRAVELLERS | 35 |
| 05 Same services | `create_campaign` (agents, playbooks), `trips.cancel` (users) | NOTIFY executor → `create_campaign` with the new trip audience; CANCEL executor → a new `trips.cancel_by_agent` (§3) | 34 |
| 06 Policies | `action_policy`, `ensure_policies` seed | NOTIFY_TRAVELLERS (2, `TRAVEL_DESK\|SECURITY_OFFICER`), CANCEL_TRIP (2, `SECURITY_OFFICER`), both not undoable, `decision_deadline_s` 3600 | 34 |
| 07 Never restricted | `trip.restricted` (PC-17) | skipped in `observe`; refused again by the audience and by `cancel_by_agent` (defence in depth) | 34, 35 |
| 08 One per change | `proposal_key` unique per agent | keys in §2 | 35 |
| 09 Shown where people look | Decision Queue, AI Agents (Phase 1) | travel cards with trip and flight links; AI Agents roster row | 36 |

## 2. Proposal keys, titles and evidence

| Cause | Action | `proposal_key` | Title |
|---|---|---|---|
| Flight HOLDING / DIVERTED / CANCELLED | NOTIFY_TRAVELLERS | `NOTIFY_TRAVELLERS:flight:<flight id>:<status>` | "Notify XW 451 travellers · holding near Nairobi" |
| Flight 60+ min late | NOTIFY_TRAVELLERS | `NOTIFY_TRAVELLERS:flight:<flight id>:DELAY60` | "Notify XW 812 travellers · 75 min late" |
| Flight DIVERTED / CANCELLED | ADVISE_REBOOKING | `ADVISE_REBOOKING:flight:<flight id>:<status>` | "Arrange onward travel · XW 451 diverted to Mombasa" |
| Trip impacted by an incident | NOTIFY_TRAVELLERS | `NOTIFY_TRAVELLERS:impacted:<trip id>:<incident id>` | "Safety message to TRP-8812 travellers · INC-…-1042" |
| Risk rose, trip not started | CANCEL_TRIP (+ notify alternative) | `CANCEL_TRIP:risk:<trip id>:<live level>` | "Cancel TRP-88xx Paris · risk now CRITICAL" |
| Risk rose, trip under way and not impacted | NOTIFY_TRAVELLERS | `NOTIFY_TRAVELLERS:risk:<trip id>:<live level>` | "Notify TRP-8818 travellers · risk now CRITICAL" |

A trip that is impacted gets the "impacted" message only, not also the "risk rose" one. A higher level later (HIGH → CRITICAL) is a new key, so a new proposal. Evidence: the flight's events, the incident reference and severity, or the country risk breakdown (D-19: "simulated"). Messages are deterministic English texts built by the agent (no LLM, AGT-09; D-15 translations are for citizen advisories, and these go to staff).

## 3. Executors (Prompt 34, 🔒)

- **NOTIFY_TRAVELLERS** `{trip_id, message, channels}` → `create_campaign(campaign_type="ALERT", audience={"trip_id": …}, created_by_type="AGENT")`, the same as SEND_EXTERNAL_MESSAGE. Channels default to APP and SMS (simulated).
- **CANCEL_TRIP** `{trip_id}` → `trips.cancel_by_agent(session, trip_id, actor=agent, approved_by=…)`: the trip must be APPROVED, not started (home-zone date), not restricted; it moves to CANCELLED through the same row update and trigger as a user's cancel, audited `TRIP.CANCEL` with actor AGENT and `approved_by` in the details; `TRIP_UPDATED` published. Its flights are then cancelled by the tracker's "stop" step (AT-07).
- **ADVISE_REBOOKING**: no executor, no policy: level 4, dismissed by a person (D-12).

## 4. Gaps and conflicts, with proposed answers

**G-1 · `create_campaign` needs an incident.** Flight and risk notifications have none. **Proposal:** make `incident_id` optional in `create_campaign` (the column is already nullable; composer campaigns have none), and allow the trip audience without an incident.

**G-2 · The trip audience.** **Proposal:** `{"trip_id": <id>}` resolves to that trip's active travellers. It refuses a restricted trip (TA-07) and refuses if any traveller is a CITIZEN (D-31: only `DUTY_OFFICER|CONSULAR_OFFICER` approve citizen messages; the agent's approvers are Travel Desk and Security). Both refusals make the execution FAILED, audited, as for any action error.

**G-3 · Approval scope without an incident.** Proposals take their scope from the incident's mission, else HQ only (D-06, `proposals._mission`). Flight and risk proposals have no incident, so only unscoped (HQ) Travel Desk and Security Officers decide them; impacted-trip proposals carry the incident and its mission scope. **Proposal:** keep this in the pilot (the demo users are unscoped). A trip-scoped proposal would need a `trip_id` on `agent_proposal` (a schema and approvals change); not proposed now.

**G-4 · Who may cancel.** A user cancels as requester, TRAVEL_DESK or ADMIN (Prompt 25), but CANCEL_TRIP is approved by a SECURITY_OFFICER (D-34). **Proposal:** for agent actions the policy is the authority (D-16): the Security Officer's approval runs the cancel; the Journey screen's own cancel rule is unchanged.

**G-5 · Phase 1 scenario.** In NBO-CIVIL-UNREST the agent now adds two pending cards: TRP-8812 impacted (scene 2) and TRP-8818 "risk now CRITICAL" (Kenya rises from MODERATE). The Phase 1 acceptance finds proposals by type and checks the queue only before the incident, so it still passes; the D-23 counts are untouched. **Proposal:** accept; Prompt 35 runs the Phase 1 acceptance to confirm.

**G-6 · The acceptance's Paris trip.** **Proposal:** seed TRP-8811 "Cultural exchange · Paris" (2 Paris staff not on other trips, APPROVED at LOW, 5 days after the scenario date, no flight segment). When the France scenario's Paris incident makes France CRITICAL, it gets a CANCEL_TRIP proposal.

**G-7 · Advice cards expire.** ADVISE_REBOOKING has no policy row, so its deadline is the default. **Proposal:** fine: advice nobody acts on expires like any other proposal.

**G-8 · What the agent reads.** It reads flights, trips, travellers and risks in its rolled-back session (agents only read, runner). It never reads a restricted trip's segments because it skips restricted trips first.

## 5. Data changes

**None.** The agent row, the two policies, the trip audience (`audience_filter` JSON) and TRP-8811 are data. `create_campaign`'s optional incident (G-1) is code. D-29 still applies to the executors and policies (Prompt 34).

## 6. Seed

- Agent `TRAVEL_AIR` "Travel & Air", level 2, enabled.
- Policies: `NOTIFY_TRAVELLERS` (2, `TRAVEL_DESK|SECURITY_OFFICER`, not undoable, 3600 s), `CANCEL_TRIP` (2, `SECURITY_OFFICER`, not undoable, 3600 s).
- TRP-8811 (G-6).
- `decisions.md` "Phase 1 agent and policy seed" table gains the rows (as the pilot agent).

## 7. Decisions needed from the product owner

None: G-1..G-8 follow from D-12..D-17, D-31..D-34 and the defaults in §23. G-3 (HQ-only approval for proposals without an incident) and G-5 (two new cards in the Nairobi scenario) are worth a look.

## 8. Review of Prompt 35 (the agent's triggers)

Fixed: tests seeded for today (the agent reads the real date); a trip impacted by any active incident gets no "risk now" card; advice for a cancelled flight names the departure city; nothing is proposed that the trip audience would refuse (a citizen traveller, no active traveller); a trip with a flight already in the air gets "notify", not "cancel"; evidence lists the flight's events and the country risk breakdown; TRP-8811's travellers are Berlin staff.

Accepted as specified (TA-08), for the record:
- **One proposal per cause and level, ever.** HOLDING → AIRBORNE → HOLDING gives no second card, and a level that falls and rises again re-uses its key, so a rejected or expired card is not repeated.
- **HIGH then CRITICAL can leave two CANCEL_TRIP cards** pending for one trip; approving one makes the other fail ("not APPROVED"). Prompt 36's card shows both with their levels.
- **Only incident-driven rises are seen.** A change to a country's simulated base level publishes no event, so the agent does not react to it (no feed changes `country_risk` in the pilot).
