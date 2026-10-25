# Plan · Pilot module 1: Mass Notification (Prompt 17)

For the product owner and the coding agent. It maps MN-01..12 (`docs/requirements-pilot.md`) and D-31 onto the code as it stands after Phase 1, and lists the gaps found, each with a proposed answer. Items marked **needs a decision** wait for the product owner; everything else follows from approved documents.

## 1. Requirements against existing code

| MN | Exists today | New work | Prompt |
|---|---|---|---|
| 01 Compose (draft) | `notification_campaign` has `DRAFT`; `created_by_type = 'USER'` is allowed | `create_draft`/`update_draft` in `notifications/service.py`; `create_campaign` still queues only on send | 20 |
| 02 Audiences and preview | `resolve_audience` handles `exposed` and `mission: incident` (both need an incident) | Add `missions[]` and `person_types[]` with no incident; a preview with counts per person type | 20 |
| 03 Templates | none; the PB-07 seed carries the advisory text | `message_template` (PC-07), a template service with `resolve(kind, mission_id)` and `{city}` | 18, 19 |
| 04 PB-07 and agent use templates | `communications.py` reads `step.action_config["citizen_advisory"]` | PB-07 **version 2** with `citizen_advisory_template`; the agent resolves it (gap G-4) | 19 |
| 05 Second person | `approvals.decide` and `Gate` | A gate built from the campaign (G-2, G-3); PC-08 columns and trigger | 18, 20 |
| 06 Unreviewed blocked in pilot | translations are stored on the campaign | Each template language is marked reviewed or not; a check at send time when `APP_ENV=pilot` (G-11) | 20 |
| 07 Cancel | `CANCELLED` status exists | An endpoint and audit | 20 |
| 08 Test send | phone preview panel on the Check-in screen (D-28) | A preview-only endpoint: text per channel, SMS segment count; audit `CAMPAIGN.TEST_SEND` (G-7) | 20, 21 |
| 09 Funnel | delivery statuses, and the worker publishes `CAMPAIGN_UPDATED`, which `/ws` forwards | Counts per campaign and channel in `GET /api/campaigns/{id}` | 20, 21 |
| 10 History | `GET /api/campaigns` (incident filter) | Filters for kind, status, mission and incident; show creator and approver | 20, 21 |
| 11 Fallback (Should) | adapter never fails; one delivery per person **per channel** | Needs a delivery mode (G-1, **needs a decision**) and simulated failures (G-6) | 20 |
| 12 Audit | `CAMPAIGN.CREATE`, `CAMPAIGN.SEND`, `CAMPAIGN.DISPATCHED` | `CAMPAIGN.DRAFT`, `.EDIT`, `.SUBMIT`, `.APPROVE`, `.REJECT`, `.CANCEL`, `.TEST_SEND` | 20 |

## 2. API (Prompt 20)

| Method and path | Who | What |
|---|---|---|
| `POST /api/campaigns` | DUTY_OFFICER, SECURITY_OFFICER, CONSULAR_OFFICER, ADMIN | Create a DRAFT. Body: `kind`, `template_id?`, `message`, `translations`, `channels[]`, `audience` {`missions[]?`, `person_types[]?`, `exposed_to_incident?`}, `incident_id?`, `delivery_mode?` (G-1) |
| `PATCH /api/campaigns/{id}` | the author, while DRAFT | Edit a draft |
| `POST /api/campaigns/{id}/preview` | composers | `{recipients, by_person_type, by_mission}`; no side effects |
| `POST /api/campaigns/{id}/test-send` | the author | `{channel: {text, sms_segments?}}`; audit only |
| `POST /api/campaigns/{id}/submit` | the author | Staff only (DUTY_OFFICER or SECURITY_OFFICER author): sends now. Includes citizens: goes to `PENDING_APPROVAL` |
| `POST /api/campaigns/{id}/approve` | DUTY_OFFICER or CONSULAR_OFFICER, not the author (`approvals.decide`) | Sends |
| `POST /api/campaigns/{id}/reject` | same as approve | `{reason}`, back to DRAFT |
| `POST /api/campaigns/{id}/cancel` | the author, or ADMIN | DRAFT or PENDING_APPROVAL → CANCELLED |
| `GET /api/campaigns` | all roles | Adds `kind`, `status`, `mission_id` filters, and `created_by_name`/`approved_by_name` |
| `GET /api/campaigns/{id}` | all roles | Adds `funnel: {channel: {queued, sent, delivered, read, failed}}` |
| `GET /api/templates`, `POST`, `PATCH /api/templates/{id}` | read: composers; write: ADMIN, CONSULAR_OFFICER | Templates, with a reviewed flag per language |
| `GET /api/me/permissions?entity_type=notification_campaign` | all roles | `approve_campaign`, `edit_campaign`, `cancel_campaign` (plan G-07) |

"Send" always goes through the existing outbox: deliveries are queued in the same transaction, and the worker dispatches them. There is no second sending path.

## 3. Gaps and conflicts, with proposed answers

**G-1 · Fallback conflicts with all-channel delivery. Needs a decision.**
- Today a campaign queues one delivery per person on **every** channel, enforced by `UNIQUE (campaign_id, person_id, channel)`. That is right for PB-07, where the alert goes out by APP, SMS and VOICE at once.
- MN-11 ("try the next channel after a failure") only makes sense if the channels are an ordered preference.
- **Proposal (PC-09, a schema change):** `notification_campaign.delivery_mode text NOT NULL DEFAULT 'ALL' CHECK (delivery_mode IN ('ALL', 'FALLBACK'))`.
  - `ALL` is today's behaviour, unchanged for playbooks and agents.
  - `FALLBACK` queues only the first channel, and queues the next one once if a delivery FAILS.
  - The composer offers both; the default is `ALL`.
- **Alternative with no schema change:** drop MN-11 from this module (it is a Should).

**G-2 · "Not the author" through the existing Gate.**
- `Gate.deciders_of_other_steps` already refuses someone who decided another step. Submitting counts as step 1 and approving as step 2, so passing `{author}` there enforces MN-05 with no change to `approvals.py` (🔒).
- The refusal then reads "The same person cannot decide two steps (D-16)". That is accurate, because composing and submitting is the first step.
- The PC-08 trigger is the database backstop.

**G-3 · Mission scope of a campaign approval.** `Gate.mission_id` is:
- the incident's mission, if the campaign is for an incident;
- otherwise the single mission in `audience.missions`;
- otherwise (several missions, or none) `None`, so only unscoped (HQ) approvers can approve. This is the same rule as D-06.

**G-4 · Changing PB-07 needs a new version.**
- `ensure_playbook` only inserts, keyed by `(code, version)`, so editing the v1 config would not reach existing databases.
- **Proposal:** seed **PB-07 version 2**, with `citizen_advisory_template: "CIVIL_UNREST_SHELTER"` in step 4, and mark v1 inactive.
- `active_playbook()` already selects the active row, so the Response Planner picks v2. Prompt 19 checks this, and that a v1 run already in progress finishes on v1.

**G-5 · `created_by` is text.** PC-08's trigger compares `approved_by::text = created_by` when `created_by_type = 'USER'`. That is what PC-08 says.

**G-6 · Simulated failures are a channel-adapter change (🔒, D-29).**
- `SimulatedChannelAdapter.receipt` never returns FAILED. MN-11 needs a deterministic failure share, from a hash of the provider ref against `SIMULATED_FAILURE_RATE`.
- It is refused outside `local` and `demo`. The default is 0, so Phase 1 behaviour is unchanged.
- This sits in Prompt 20, which is already 🔒.

**G-7 · Test send to self.** Users (`app_user`) are not linked to `person` rows, so there is no recipient for a real delivery. **Proposal:**
- test send returns what each channel would show: the push title and body; the SMS text with its 160-character segment count; the email subject and body;
- the phone preview panel shows it;
- it is audited, and no deliveries are created. This matches MN-08.

**G-8 · A CHECKIN without an incident.** Composed check-ins may have no incident. The check-in summary and escalation already handle `incident_id IS NULL`: the escalation writes no incident event, but still writes its audit row. The Check-in screen's campaign picker lists campaigns by incident, so it gains an "all check-ins" option in Prompt 21.

**G-9 · The France scenario (MN-04 acceptance).** The France scenario stops at "PB-07 proposed". The e2e in Prompt 22 approves PB-07 for Paris and checks that the advisory proposal names Paris. The scene 1 hint ("edit before approving") is removed in Prompt 19.

**G-10 · Large sends.** No requirement says to confirm big audiences. **Proposal:** the composer asks for confirmation above 500 recipients (UI only; no new rule).

**G-11 · What counts as "reviewed" (MN-06).**
- A translation is reviewed only if it is the template's reviewed text, unchanged.
- If the user edits a translation, or writes one, it is unreviewed.
- So in a pilot, a campaign can carry English plus reviewed template translations only. Everything else is refused with 409, naming the language.

## 4. Migration for PC-07 and PC-08 (Prompt 18, 🔒)
- **`message_template`** as PC-07:
  - FORCE RLS with the `tenant_isolation` policy;
  - grants SELECT, INSERT and UPDATE to `nexira_app`; no DELETE;
  - `updated_at` trigger.
- **`notification_campaign`** gets the PC-08 columns. The status CHECK is dropped and recreated with `PENDING_APPROVAL`.
- **`notification_campaign_approval_guard` trigger** (BEFORE UPDATE): refuses `approved_by::text = created_by` for user campaigns, and any change to `approved_by` once it is set.
- **PC-09 (`delivery_mode`)**, only if approved (G-1).
- **Backup role:** `nexira_backup` gets SELECT through the default privileges in `backup-grants.sql`; `test_backup_role` confirms it.
- **Downgrade** reverses everything. `test_migrations` round-trips it.

## 5. Decisions needed from the product owner
1. **G-1:** approve PC-09 (`delivery_mode`, so fallback is possible), or drop MN-11 from this module.
2. Confirm G-2: "submitting is the first step", so the D-16 message is shown to an author who tries to approve their own campaign.
