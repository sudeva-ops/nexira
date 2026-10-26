# Plan · Pilot module 2: Journey Management (Prompt 23)

For the product owner and the coding agent. It maps JR-01..09 (`docs/requirements-pilot.md` §9–13) and D-32 onto the code after pilot module 1, and lists the gaps found, each with a proposed answer. Items marked **needs a decision** wait for the product owner; the rest follows from approved documents. It follows the Mass Notification composer's pattern (`notifications/compose.py`).

## 1. Requirements against existing code

| JR | Exists today | New work | Prompt |
|---|---|---|---|
| 01 Create/edit a draft trip | `trip`, `trip_traveller`, `travel/service.ensure_trip` (seed only) | `travel/trips.py` (service) and `travel/router.py`; `DRAFT` status (PC-15); `TRP` reference counter | 24, 25 |
| 02 Itinerary | nothing | `trip_segment` (PC-14); segments replaced as a list while DRAFT | 24, 25 |
| 03 Destination risk | `trip.risk_level` (seeded by hand); incidents have **no country** | `country_risk` (PC-16, simulated); risk = max(country level, worst ACTIVE incident whose **mission** is in that country) (G-1) | 24, 25 |
| 04 Approval by risk | `approvals.decide`, `Gate` | Gate per trip: required role from the submitted risk; requester and submitter as deciders of the first step; scope G-2; PC-15 backstop | 24, 25 |
| 05 Checklist | nothing | `trip.checklist` jsonb (PC-15); tick endpoint; HIGH/CRITICAL approval blocked while open | 24, 25 |
| 06 Impacted | `incident_exposure` TRIP rows for trips active today (D-22) | `impacted_by` in the trip API from ACTIVE incidents; exposure counts only trips that will happen (G-3) | 25 |
| 07 Risk changed since approval | nothing | `approved_risk_level` (PC-15) compared with the live risk; shown, never revoked | 25 |
| 08 Screen | nothing | `/journeys` under MONITOR | 26 |
| 09 Audit | `audit.write` | `TRIP.DRAFT`, `.EDIT`, `.CHECK`, `.SUBMIT`, `.AUTO_APPROVE`, `.APPROVE`, `.REJECT`, `.CANCEL` | 25 |

## 2. API (Prompt 25)

| Method and path | Who | What |
|---|---|---|
| `GET /api/trips` | all roles | Filters: `status`, `risk`, `mission_id`, `impacted`. Each row: travellers count, live risk, `impacted_by` (incident references), `risk_changed` |
| `GET /api/trips/{id}` | all roles | Plus travellers (names, types), segments, checklist, the destination's `country_risk` breakdown, requester and approver names |
| `POST /api/trips` | TRAVEL_DESK, DUTY_OFFICER | A DRAFT. Body: `purpose`, `origin`, `destination`, `destination_country`, `starts_on`, `ends_on`, `travellers[]` (person ids), `segments[]` (`kind`, `title`, `place_label`, `starts_at`, `ends_at`). `extra="forbid"` |
| `PATCH /api/trips/{id}` | the requester, still holding a creator role, while DRAFT | Same body; travellers and segments replaced |
| `POST /api/trips/{id}/checklist` | TRAVEL_DESK, DUTY_OFFICER, SECURITY_OFFICER | `{item, done}` for the four user items; audited each time; not after approval |
| `POST /api/trips/{id}/submit` | the requester | Computes the risk; LOW → APPROVED at once (audited, no second person); otherwise PENDING |
| `POST /api/trips/{id}/approve` | MODERATE: TRAVEL_DESK or SECURITY_OFFICER; HIGH/CRITICAL: SECURITY_OFFICER; not the requester (`approvals.decide`) | Checklist must be complete for HIGH/CRITICAL (409 naming the item) |
| `POST /api/trips/{id}/reject` | same as approve | `{reason}`, back to DRAFT |
| `POST /api/trips/{id}/cancel` | the requester, TRAVEL_DESK, or ADMIN | DRAFT, PENDING or APPROVED → CANCELLED |
| `GET /api/me/permissions?entity_type=trip` | all roles | `edit_trip`, `submit_trip`, `approve_trip`, `check_trip`, `cancel_trip` |

## 3. Gaps and conflicts, with proposed answers

**G-1 · Incidents have no country.** D-32 says "the worst ACTIVE incident in that country", but `incident` has only a location and `mission_id`. **Proposal:** an incident counts for the country of its mission (`mission.country_code`). Incidents with no mission nearby (for example Lyon and Nantes in the France scenario) do not raise a country's risk in the pilot. A later proposal could add `incident.country_code` from a country lookup. In the France scenario the Paris incident (mission PAR, FR) raises France to CRITICAL, which already meets JR-03's "HIGH or above".

**G-2 · Approval scope when a country has several missions.** **Proposal:** `trip.mission_id` is set at submission to the single mission in the destination country; if the country has none or several (the US has WAS and NYC), it is NULL and only HQ-level (unscoped) approvers decide (D-06).

**G-3 · Exposure counts trips regardless of status.** `intel/exposure.py` counts any trip active today, so a DRAFT or CANCELLED trip would show as impacted and count in the incident's "trips" figure. **Proposal:** count only PENDING and APPROVED trips. TRP-8812 is APPROVED, so the Nairobi figures (D-23: 1 trip) do not change.

**G-4 · The seeded TRP-8812 has no requester or approver.** It is APPROVED with `approved_by` NULL. **Proposal:** the PC-15 trigger checks approvals only on UPDATE; seeded rows are inserted as-is. `approved_risk_level` is backfilled from `risk_level` for existing APPROVED trips in the migration, so they don't all show "risk changed".

**G-5 · Reference numbers.** **Proposal:** a `TRP` counter (D-18) starting after the highest seeded reference, so new trips are `TRP-8813` onwards.

**G-6 · Approver for a LOW trip.** LOW trips are approved on submission with no second person, so `approved_by` stays NULL and `approved_at` is set; the audit row `TRIP.AUTO_APPROVE` names the requester. PC-15's `(approved_by IS NULL) = (approved_at IS NULL)` style check must allow this: **proposal:** the check is `approved_at IS NOT NULL` when APPROVED, and `approved_by` NULL only for auto-approved LOW trips (`approved_risk_level = 'LOW'`).

**G-7 · Risk at approval time.** The risk can change between submission and approval (an incident starts). **Proposal:** the approver required is recomputed at approval; if the risk rose to HIGH, a Travel Desk approver is refused (403) and the trip shows the new level. `approved_risk_level` is the level at approval.

**G-8 · Segment times and time zones.** Segments are `timestamptz`; the screen shows them in the home zone (GST) like everything else, with the place label. Local destination times are a later improvement.

## 4. Migration 0003 (Prompt 24, 🔒)

- `trip_segment` and `country_risk` with FORCE RLS and `tenant_isolation`; grants as PC-14 and PC-16.
- `trip`: statuses `DRAFT` (default) and `CANCELLED` added to the CHECK; the PC-15 columns; backfill `approved_risk_level` for APPROVED trips (G-4).
- Guard triggers on `trip`, `trip_traveller` and `trip_segment`, as PC-10..12 and G-6; REVOKE DELETE on `trip` and `trip_traveller`.
- `nexira_backup` reads the new tables through the default privileges; the downgrade restores 0002 exactly (as in Prompt 18).
- Seed (simulator): `country_risk` for the seeded missions' countries (simulated levels), the `TRP` counter (G-5), and a few trips in other states for the screen. TRP-8812 is unchanged.

## 5. Decisions from the product owner (2026-10-26, PR #25)
1. **G-1:** approved. Incidents count for their mission's country only; no country lookup in the pilot.
2. **G-3:** approved. Only PENDING and APPROVED trips count in exposure and as impacted.

The other gaps follow from D-32 and the approved PCs.
