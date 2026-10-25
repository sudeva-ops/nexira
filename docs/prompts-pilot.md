# NEXIRA · Pilot prompts for the AI coding tool · v0.1

For the coding agent, after the product owner approves `docs/requirements-pilot.md`. They continue the numbering of `docs/prompts.md`, which ended at Prompt 16. The rules are the same:
- one prompt at a time, in order, with one branch and one PR per prompt;
- `make test lint` before declaring a prompt done;
- 🔒 prompts need a named human reviewer's sign-off (D-29);
- the Phase 1 acceptance scenario (`make acceptance`) must still pass after every prompt (D-30).

Sources of truth, in this order: `docs/decisions.md` (D-30, D-31), `docs/requirements-pilot.md` (MN-01..12), `docs/schema/proposed-changes.md` (PC-07, PC-08).

---

## Pilot module 1 · Mass Notification

### Prompt 17 · Read and plan (no code)
```
Read AGENTS.md, docs/decisions.md (D-05, D-15, D-16, D-29, D-30, D-31),
docs/requirements-pilot.md and the notifications, checkin, playbooks and agents modules.
Write docs/plan-pilot-ntf.md:
- how each MN requirement maps to existing code, and what is new;
- the API you will add (paths, request and response shapes, roles);
- gaps or conflicts between the documents, each with a proposed answer;
- the migration you will write for PC-07 and PC-08 (only after they are approved).
No code changes.
```

### Prompt 18 · Templates and campaign approval columns (migration) 🔒
```
PC-07 and PC-08 were approved by the product owner on 2026-10-25 (PR #16).

- New Alembic migration (never edit 0001):
  - message_template (PC-07) with FORCE RLS, the tenant_isolation policy and grants to
    nexira_app;
  - the notification_campaign changes (PC-08), including the trigger that refuses
    approved_by = created_by.
- nexira_backup gets SELECT through the default privileges in infra/postgres/backup-grants.sql.
  Check this, and do not add grants by hand.
- Seed templates for: the generic civil-unrest shelter-in-place advisory (with {city}),
  the Nairobi advisory (today's PB-07 text, unchanged) and a Paris advisory.
  EN plus AR/FR/SW, all marked "not reviewed" (D-15).

Tests (real PostgreSQL, as nexira_api): tenant isolation on message_template; the trigger
refuses self-approval; test_backup_role still passes; the migration round-trips.
```

### Prompt 19 · Per-mission templates in PB-07 and the Communications agent
```
MN-03, MN-04.
- A template service: resolve(kind, mission_id) returns the mission's template, otherwise the
  generic one, with {city} filled in.
- PB-07 step 4 references a template code instead of carrying advisory text in its config.
  Update the seed: the Nairobi template keeps today's text exactly.
- The Communications agent builds its SEND_EXTERNAL_MESSAGE proposal from the resolved
  template. Its policy (level 2, DUTY_OFFICER|CONSULAR_OFFICER) and EDITABLE_FIELD do not change.

Tests: the Nairobi acceptance scenario is unchanged (make acceptance); the France scenario's
advisory contains no "Nairobi", "CBD" or "Upper Hill"; the generic fallback fills in {city}.
```

### Prompt 20 · Composer backend: draft, approve, send 🔒
```
MN-01, MN-02, MN-05 to MN-08, MN-12 (MN-11 deferred, plan G-1). 🔒 because it adds the
second-person approval for external messages. The channel adapters are not changed.
- POST /api/campaigns (create a DRAFT); PATCH /api/campaigns/{id} (edit a DRAFT);
  POST /api/campaigns/{id}/preview (recipient count and split by person type);
  /submit, /approve, /reject (with a reason), /cancel and /test-send.
- Audiences: missions[], person_types[], exposed_to_incident. Reuse resolve_audience,
  extended for "no incident".
- The second-person rule (D-31) goes through approvals.decide with a Gate. Do not write a new
  role check. Staff-only campaigns are sent by the author.
- In APP_ENV=pilot, refuse to send with an unreviewed translation (409, naming the language).
- Sending queues deliveries exactly as playbook campaigns do (outbox, idempotency); there is no
  second sending path.
- Every action is audited through app/core/audit.py.
- No endpoint may write created_by, created_by_type or submitted_by from the request
  (review of Prompt 18): set them in the service only, and test that a PATCH with those
  fields changes nothing. Approve only from PENDING_APPROVAL, with the row locked, and
  set status SENDING in the same UPDATE as approved_by. PATCH only DRAFT campaigns: the
  content is frozen once submitted. The database refuses anything else (PC-10, PC-11).

Tests: author approval → 403; a Viewer → 403; a second Duty Officer → deliveries queued; a
staff-only campaign is sent by its author; cancel and test-send queue nothing; pilot mode
blocks unreviewed translations.
```

### Prompt 21 · Mass Notification screen
```
MN-01 to MN-10 in the UI (Blueprint dark; visual reference only: the demo's Mass Notification
composer).
- Composer: kind, template picker, message, channels, audience builder with a live recipient
  count, and the phone preview panel for test-send.
- Campaign history with filters; the campaign detail page has a delivery funnel per channel
  that updates live (WebSocket CAMPAIGN_UPDATED).
- Approve and reject are shown only to users who can do them. Use GET /api/me/permissions,
  extended for campaigns (plan G-07).
- Add the screen to the navigation under RESPOND.

Tests: Vitest for the composer, the funnel and the permission-driven buttons.
```

### Prompt 22 · Mass Notification acceptance
```
Playwright, real stack, as in Prompt 15 (requirements-pilot.md §6):
- A Duty Officer composes an advisory to the Paris citizens from a template, test-sends it,
  and submits it.
- Self-approval is refused, and a second Duty Officer approves.
- The funnel reaches read for every recipient, and GET /api/audit/verify is intact.
- make acceptance (Nairobi) still passes, and the France scenario's advisory names Paris.
Report the real output.
```

---

## Later pilot modules
The prompts for Journey Management, Air Travel Tracking, the Travel & Air agent and (if the customer wants it) Assistance Partners are written after their requirements are approved (requirements-pilot.md §7).
