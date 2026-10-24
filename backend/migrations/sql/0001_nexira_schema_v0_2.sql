-- =====================================================================
-- NEXIRA · Phase 1 database schema · v0.2
-- PostgreSQL 16 + PostGIS 3
-- Scope: MVP modules — Decision Queue, Global Operations, Incidents,
--        People & Sites, Playbooks, Safety Check-in, Agents, Audit,
--        Scenario engine (simulated data).
--
-- Changes from v0.1 are listed in docs/decisions.md (section "Schema
-- changes"). Decision IDs (D-xx) are referenced in comments below.
--
-- Conventions:
--   * Every business table carries tenant_id, including child tables (D-03).
--   * UUID primary keys, created_at / updated_at on mutable tables.
--   * Locations use geography(Point,4326) so distances are in metres.
--   * Enumerations use CHECK constraints rather than PG ENUMs.
--   * One severity scale everywhere: LOW, MODERATE, HIGH, CRITICAL (D-08).
--
-- Database roles (D-01). Create these BEFORE running this file, e.g. in
-- infra/postgres/init.sql (passwords come from .env, never from here):
--   nexira_owner  LOGIN, owns all objects, runs migrations. Not superuser.
--   nexira_app    NOLOGIN group role that holds the runtime grants.
--   nexira_api    LOGIN, member of nexira_app; the only user the backend uses.
-- Run this file as nexira_owner. Superusers and BYPASSRLS roles skip RLS,
-- so the API must never connect as postgres or as nexira_owner.
--
-- The API sets the tenant at the start of every transaction (D-02):
--   SELECT set_config('app.tenant_id', '<uuid>', true);
-- The app must run in READ COMMITTED (the default) for the audit chain.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid(), digest()

-- ---------------------------------------------------------------------
-- 0. Helpers
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Current tenant from the session; NULL (never an error) when unset.
CREATE OR REPLACE FUNCTION current_tenant_id() RETURNS uuid AS $$
  SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid;
$$ LANGUAGE sql STABLE;

-- Ordering for the single severity scale (D-08).
CREATE OR REPLACE FUNCTION severity_rank(s text) RETURNS smallint AS $$
  SELECT CASE s WHEN 'LOW' THEN 1 WHEN 'MODERATE' THEN 2
                WHEN 'HIGH' THEN 3 WHEN 'CRITICAL' THEN 4 END::smallint;
$$ LANGUAGE sql IMMUTABLE;

-- ---------------------------------------------------------------------
-- 1. Tenancy, identity & access
-- ---------------------------------------------------------------------
CREATE TABLE tenant (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name              text NOT NULL,
  hosting_region    text NOT NULL DEFAULT 'in-country',
  oidc_issuer       text NOT NULL UNIQUE,          -- D-04: token issuer identifies the tenant
  agents_paused     boolean NOT NULL DEFAULT false, -- D-17: kill switch
  agents_paused_at  timestamptz,
  agents_paused_by  uuid,                           -- app_user.id (FK added below)
  created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app_user (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  external_id     text NOT NULL,                     -- OIDC 'sub'
  email           text NOT NULL,
  display_name    text NOT NULL,
  is_active       boolean NOT NULL DEFAULT true,
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, email),
  UNIQUE (tenant_id, external_id)
);

ALTER TABLE tenant ADD CONSTRAINT tenant_paused_by_fk FOREIGN KEY (agents_paused_by) REFERENCES app_user(id);

CREATE TABLE role (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  code            text NOT NULL,     -- ADMIN, DUTY_OFFICER, SECURITY_OFFICER, HEAD_OF_MISSION, HQ_CRISIS_DIRECTOR, TRAVEL_DESK, CONSULAR_OFFICER, VIEWER
  name            text NOT NULL,
  UNIQUE (tenant_id, code)
);

-- ---------------------------------------------------------------------
-- 2. Missions, sites & people
-- ---------------------------------------------------------------------
CREATE TABLE mission (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  code            text NOT NULL,                 -- e.g. NBO
  city            text NOT NULL,
  country_code    char(2) NOT NULL,
  risk_level      text NOT NULL DEFAULT 'LOW'    -- D-08: UI shows LOW as "Normal", MODERATE as "Elevated"
                  CHECK (risk_level IN ('LOW','MODERATE','HIGH','CRITICAL')),
  location        geography(Point,4326) NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, code)
);
CREATE INDEX mission_location_gix ON mission USING gist (location);
CREATE TRIGGER mission_updated BEFORE UPDATE ON mission FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- D-05: surrogate key so one person can hold the same role at several missions.
-- mission_id NULL means the role applies to all missions (e.g. HQ roles).
CREATE TABLE user_role (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  user_id         uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  role_id         uuid NOT NULL REFERENCES role(id) ON DELETE CASCADE,
  mission_id      uuid REFERENCES mission(id),
  UNIQUE NULLS NOT DISTINCT (user_id, role_id, mission_id)
);

CREATE TABLE site (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  mission_id      uuid NOT NULL REFERENCES mission(id),
  site_type       text NOT NULL
                  CHECK (site_type IN ('EMBASSY','CONSULATE','RESIDENCE','HOTEL','OFFICE','OTHER')),
  name            text NOT NULL,
  location        geography(Point,4326) NOT NULL,
  readiness_score smallint CHECK (readiness_score BETWEEN 0 AND 100),
  last_drill_on   date,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX site_location_gix ON site USING gist (location);
CREATE TRIGGER site_updated BEFORE UPDATE ON site FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE person (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  mission_id      uuid REFERENCES mission(id),
  person_type     text NOT NULL
                  CHECK (person_type IN ('DIPLOMAT','LOCAL_STAFF','DEPENDANT','DELEGATE','CITIZEN','CONTRACTOR')),
  full_name       text NOT NULL,
  role_title      text,
  phone           text,
  email           text,
  preferred_lang  text DEFAULT 'en',
  hr_external_id  text,
  is_active       boolean NOT NULL DEFAULT true,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX person_mission_idx ON person (tenant_id, mission_id);
CREATE TRIGGER person_updated BEFORE UPDATE ON person FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE location_observation (
  id              bigserial PRIMARY KEY,
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  person_id       uuid NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  source          text NOT NULL
                  CHECK (source IN ('MOBILE_GPS','ACCESS_CONTROL','TRAVEL_BOOKING','CALENDAR_HR','CHECKIN','FLIGHT','MANUAL')),
  location        geography(Point,4326) NOT NULL,
  place_label     text,
  observed_at     timestamptz NOT NULL,
  raw             jsonb
);
CREATE INDEX location_obs_person_time_idx ON location_observation (person_id, observed_at DESC);
CREATE INDEX location_obs_gix ON location_observation USING gist (location);

CREATE TABLE person_location_current (
  person_id       uuid PRIMARY KEY REFERENCES person(id) ON DELETE CASCADE,
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  location        geography(Point,4326) NOT NULL,
  place_label     text,
  confidence      smallint NOT NULL CHECK (confidence BETWEEN 0 AND 100),
  primary_source  text NOT NULL,
  computed_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX person_loc_current_gix ON person_location_current USING gist (location);

-- ---------------------------------------------------------------------
-- 3. Travel (minimal for Phase 1)
-- ---------------------------------------------------------------------
CREATE TABLE trip (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  reference       text NOT NULL,                 -- e.g. TRP-8812
  purpose         text,
  origin          text NOT NULL,
  destination     text NOT NULL,
  destination_country char(2),
  starts_on       date NOT NULL,
  ends_on         date NOT NULL,
  risk_level      text NOT NULL DEFAULT 'LOW' CHECK (risk_level IN ('LOW','MODERATE','HIGH','CRITICAL')),
  approval_status text NOT NULL DEFAULT 'PENDING' CHECK (approval_status IN ('PENDING','APPROVED','REJECTED')),
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, reference),
  CHECK (ends_on >= starts_on)
);

CREATE TABLE trip_traveller (
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  trip_id         uuid NOT NULL REFERENCES trip(id) ON DELETE CASCADE,
  person_id       uuid NOT NULL REFERENCES person(id),
  PRIMARY KEY (trip_id, person_id)
);

-- ---------------------------------------------------------------------
-- 4. Intelligence: sources, raw signals, fused incidents
-- ---------------------------------------------------------------------
CREATE TABLE intel_source (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  code            text NOT NULL,                 -- e.g. DATAMINR, MAX, RISKLINE, OSINT
  name            text NOT NULL,                 -- D-19: shown as "<name> (simulated)" while SIMULATED
  connector_type  text NOT NULL DEFAULT 'SIMULATED' CHECK (connector_type IN ('SIMULATED','API','WEBHOOK','FILE')),
  reliability     numeric(3,2) NOT NULL DEFAULT 0.50 CHECK (reliability > 0 AND reliability < 1), -- D-10
  severity_map    jsonb NOT NULL DEFAULT '{}',   -- provider severity -> LOW|MODERATE|HIGH|CRITICAL
  category_map    jsonb NOT NULL DEFAULT '{}',   -- provider category -> normalised category
  takes_part_in_fusion boolean NOT NULL DEFAULT true, -- D-09: OSINT = false in Phase 1
  is_enabled      boolean NOT NULL DEFAULT true,
  UNIQUE (tenant_id, code)
);

CREATE TABLE raw_signal (
  id              bigserial PRIMARY KEY,
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  source_id       uuid NOT NULL REFERENCES intel_source(id),
  external_id     text NOT NULL,
  title           text NOT NULL,
  body            text,
  language        text DEFAULT 'en',
  provider_category text,
  provider_severity text,
  location        geography(Point,4326),
  place_label     text,
  occurred_at     timestamptz NOT NULL,
  received_at     timestamptz NOT NULL DEFAULT now(),
  norm_category   text,
  norm_severity   text CHECK (norm_severity IN ('LOW','MODERATE','HIGH','CRITICAL')),
  norm_status     text NOT NULL DEFAULT 'NEW' CHECK (norm_status IN ('NEW','NORMALISED','FUSED','DISCARDED')),
  payload         jsonb NOT NULL DEFAULT '{}',
  UNIQUE (source_id, external_id)
);
CREATE INDEX raw_signal_status_idx ON raw_signal (tenant_id, norm_status, received_at DESC);
CREATE INDEX raw_signal_gix ON raw_signal USING gist (location);

CREATE TABLE incident (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  reference       text NOT NULL,                 -- from next_reference('INC', true), e.g. INC-2026-1042
  title           text NOT NULL,
  category        text NOT NULL,                 -- normalised, e.g. CIVIL_UNREST
  severity        text NOT NULL CHECK (severity IN ('LOW','MODERATE','HIGH','CRITICAL')),
  signal_severity text NOT NULL CHECK (signal_severity IN ('LOW','MODERATE','HIGH','CRITICAL')), -- D-11: max of linked signals
  status          text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','MONITORING','CLOSED')),
  confidence      smallint CHECK (confidence BETWEEN 0 AND 100),
  mission_id      uuid REFERENCES mission(id),   -- D-06: nearest exposed mission; scopes approvals
  location        geography(Point,4326) NOT NULL,
  impact_radius_m integer NOT NULL DEFAULT 5000,
  place_label     text,
  opened_at       timestamptz NOT NULL DEFAULT now(),
  last_signal_at  timestamptz NOT NULL DEFAULT now(), -- D-10: fusion time window anchor
  closed_at       timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, reference),
  CHECK (severity_rank(severity) >= severity_rank(signal_severity))
);
CREATE INDEX incident_active_idx ON incident (tenant_id, status, severity);
CREATE INDEX incident_mission_idx ON incident (tenant_id, mission_id);
CREATE INDEX incident_gix ON incident USING gist (location);
CREATE TRIGGER incident_updated BEFORE UPDATE ON incident FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE incident_signal (
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  incident_id     uuid NOT NULL REFERENCES incident(id) ON DELETE CASCADE,
  signal_id       bigint NOT NULL REFERENCES raw_signal(id),
  PRIMARY KEY (incident_id, signal_id)
);

-- subject_id is polymorphic (person / site / trip), so it has no FK; the
-- exposure service is the only writer and validates the subject.
CREATE TABLE incident_exposure (
  id              bigserial PRIMARY KEY,
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  incident_id     uuid NOT NULL REFERENCES incident(id) ON DELETE CASCADE,
  subject_type    text NOT NULL CHECK (subject_type IN ('PERSON','SITE','TRIP')),
  subject_id      uuid NOT NULL,
  distance_m      integer,
  confidence      smallint,
  computed_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (incident_id, subject_type, subject_id)
);

CREATE TABLE incident_event (
  id              bigserial PRIMARY KEY,
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  incident_id     uuid NOT NULL REFERENCES incident(id) ON DELETE CASCADE,
  event_type      text NOT NULL,                 -- SIGNAL, FUSED, ESCALATED, EXPOSURE, PLAYBOOK_STEP, NOTIFICATION, CHECKIN, DECISION, STATUS, NOTE
  summary         text NOT NULL,
  actor_type      text NOT NULL CHECK (actor_type IN ('SYSTEM','AGENT','USER')),
  actor_id        text,
  occurred_at     timestamptz NOT NULL DEFAULT now(),
  data            jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX incident_event_idx ON incident_event (incident_id, occurred_at);

-- ---------------------------------------------------------------------
-- 5. Playbooks
-- ---------------------------------------------------------------------
CREATE TABLE playbook (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  code            text NOT NULL,                 -- e.g. PB-07
  name            text NOT NULL,
  category        text NOT NULL,
  trigger_rules   jsonb NOT NULL DEFAULT '{}',   -- {"category":"CIVIL_UNREST","max_distance_m":5000,"min_severity":"HIGH"}
  version         integer NOT NULL DEFAULT 1,
  is_active       boolean NOT NULL DEFAULT true,
  UNIQUE (tenant_id, code, version)
);

CREATE TABLE playbook_step (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  playbook_id     uuid NOT NULL REFERENCES playbook(id) ON DELETE CASCADE,
  seq             smallint NOT NULL,
  name            text NOT NULL,
  action_type     text NOT NULL,                 -- NOTIFY, CHECKIN, TASK, PARTNER_REQUEST, APPROVAL_GATE, BRIEFING
  action_config   jsonb NOT NULL DEFAULT '{}',
  requires_approval_role text,                   -- role code; NULL = automatic. Mission scope from incident.mission_id (D-06)
  UNIQUE (playbook_id, seq)
);

CREATE TABLE playbook_run (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  playbook_id     uuid NOT NULL REFERENCES playbook(id),
  incident_id     uuid REFERENCES incident(id),
  status          text NOT NULL DEFAULT 'RUNNING' CHECK (status IN ('RUNNING','AWAITING_APPROVAL','COMPLETED','CANCELLED','FAILED')),
  started_by_type text NOT NULL DEFAULT 'USER' CHECK (started_by_type IN ('USER','AGENT')),
  started_by      uuid REFERENCES app_user(id),  -- for AGENT starts: the user who approved the proposal
  proposal_id     uuid,                          -- set when started from an approved proposal (FK below)
  started_at      timestamptz NOT NULL DEFAULT now(),
  completed_at    timestamptz
);
-- At most one live run of a playbook per incident.
CREATE UNIQUE INDEX playbook_run_live_uq ON playbook_run (playbook_id, incident_id)
  WHERE status IN ('RUNNING','AWAITING_APPROVAL');

CREATE TABLE playbook_run_step (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  run_id          uuid NOT NULL REFERENCES playbook_run(id) ON DELETE CASCADE,
  step_id         uuid NOT NULL REFERENCES playbook_step(id),
  status          text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','RUNNING','AWAITING_APPROVAL','DONE','SKIPPED','FAILED')),
  approved_by     uuid REFERENCES app_user(id),
  started_at      timestamptz,
  completed_at    timestamptz,
  result          jsonb NOT NULL DEFAULT '{}',
  UNIQUE (run_id, step_id)
);

-- ---------------------------------------------------------------------
-- 6. Notifications & safety check-in
-- ---------------------------------------------------------------------
CREATE TABLE notification_campaign (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  reference       text NOT NULL,                 -- from next_reference('NTF', false), e.g. NTF-3103
  incident_id     uuid REFERENCES incident(id),
  campaign_type   text NOT NULL CHECK (campaign_type IN ('ALERT','CHECKIN','ADVISORY','TEST')),
  message         text NOT NULL,
  translations    jsonb NOT NULL DEFAULT '{}',   -- {"ar":"...","fr":"...","sw":"..."}; D-15: reviewed templates only
  channels        text[] NOT NULL CHECK (channels <@ ARRAY['APP','SMS','WHATSAPP','VOICE','EMAIL']::text[]),
  audience_filter jsonb NOT NULL DEFAULT '{}',
  status          text NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','SENDING','SENT','CANCELLED')),
  created_by_type text NOT NULL CHECK (created_by_type IN ('USER','AGENT','PLAYBOOK')),
  created_by      text,
  sent_at         timestamptz,
  escalate_after_s integer NOT NULL DEFAULT 600, -- CHECKIN: non-responders escalated after this
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, reference)
);

CREATE TABLE notification_delivery (
  id              bigserial PRIMARY KEY,
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  campaign_id     uuid NOT NULL REFERENCES notification_campaign(id) ON DELETE CASCADE,
  person_id       uuid NOT NULL REFERENCES person(id),
  channel         text NOT NULL,
  status          text NOT NULL DEFAULT 'QUEUED' CHECK (status IN ('QUEUED','SENT','DELIVERED','READ','FAILED')),
  provider_ref    text,
  updated_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (campaign_id, person_id, channel)
);
CREATE INDEX notification_delivery_campaign_idx ON notification_delivery (campaign_id, status);

-- D-07: history table; a person may answer more than once (e.g. SAFE then
-- NEED_HELP). The latest answer counts — see v_checkin_latest.
CREATE TABLE checkin_response (
  id              bigserial PRIMARY KEY,
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  campaign_id     uuid NOT NULL REFERENCES notification_campaign(id) ON DELETE CASCADE,
  person_id       uuid NOT NULL REFERENCES person(id),
  status          text NOT NULL CHECK (status IN ('SAFE','NEED_HELP')),
  note            text,
  location        geography(Point,4326),
  channel         text,
  responded_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX checkin_response_latest_idx ON checkin_response (campaign_id, person_id, responded_at DESC, id DESC);

-- ---------------------------------------------------------------------
-- 7. AI agents & human-in-the-loop decisions
-- ---------------------------------------------------------------------
CREATE TABLE agent (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  code            text NOT NULL,                 -- WATCH_OFFICER, EXPOSURE, RESPONSE_PLANNER, COMMUNICATIONS
  name            text NOT NULL,
  description     text,
  autonomy_level  smallint NOT NULL DEFAULT 2 CHECK (autonomy_level BETWEEN 0 AND 4),
                  -- 0 AUTO · 1 AUTO_WITH_NOTICE · 2 APPROVE · 3 SENIOR_APPROVAL · 4 ADVISE_ONLY
  is_enabled      boolean NOT NULL DEFAULT true,
  model_ref       text,
  UNIQUE (tenant_id, code)
);

-- Policy floors. An action type with NO row here is treated as level 4
-- (advise only, never executable) — fail closed (D-12).
CREATE TABLE action_policy (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  action_type     text NOT NULL,                 -- e.g. LOG_INFO, START_PLAYBOOK, SEND_EXTERNAL_MESSAGE, START_EVACUATION
  min_autonomy_level smallint NOT NULL CHECK (min_autonomy_level BETWEEN 0 AND 4),
  approver_roles  text[] NOT NULL DEFAULT '{}',  -- ordered; one entry per approval step
  is_undoable     boolean NOT NULL DEFAULT false,-- D-13: level 1 is only allowed for undoable actions
  decision_deadline_s integer NOT NULL DEFAULT 900 CHECK (decision_deadline_s > 0),
  UNIQUE (tenant_id, action_type),
  -- Level 3 needs at least two ordered approvers; level 2 needs at least one.
  CHECK (min_autonomy_level <> 3 OR cardinality(approver_roles) >= 2),
  CHECK (min_autonomy_level <> 2 OR cardinality(approver_roles) >= 1)
);

CREATE TABLE agent_proposal (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  agent_id        uuid NOT NULL REFERENCES agent(id),
  incident_id     uuid REFERENCES incident(id),
  proposal_key    text NOT NULL,                 -- idempotency: same event observed twice = one proposal
  action_type     text NOT NULL,
  title           text NOT NULL,
  proposed_action text NOT NULL,
  action_payload  jsonb NOT NULL DEFAULT '{}',
  evidence        jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(evidence) = 'array'),     -- [{"text","source"}]
  alternatives    jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(alternatives) = 'array'), -- D-14: [{"label","action_type","action_payload","rationale"}]
  risk_if_no_action text,
  confidence      smallint CHECK (confidence BETWEEN 0 AND 100),
  is_proactive    boolean NOT NULL DEFAULT false,
  effective_level smallint NOT NULL DEFAULT 4 CHECK (effective_level BETWEEN 0 AND 4), -- set by trigger, never by the app
  status          text NOT NULL DEFAULT 'PENDING'
                  CHECK (status IN ('PENDING','APPROVED','EDITED_APPROVED','REJECTED','AUTO_EXECUTED','UNDONE','EXPIRED','SUPERSEDED','FAILED')),
  superseded_by   uuid REFERENCES agent_proposal(id), -- D-14: chosen alternative becomes a new proposal
  edited_action   text,
  edited_payload  jsonb,
  rejection_reason text,
  deadline_at     timestamptz,
  undo_until      timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  decided_at      timestamptz,
  executed_at     timestamptz,
  UNIQUE (tenant_id, agent_id, proposal_key),
  CHECK (status <> 'REJECTED' OR rejection_reason IS NOT NULL),
  CHECK (status <> 'SUPERSEDED' OR superseded_by IS NOT NULL)
);
CREATE INDEX agent_proposal_queue_idx ON agent_proposal (tenant_id, status, deadline_at);

ALTER TABLE playbook_run ADD CONSTRAINT playbook_run_proposal_fk FOREIGN KEY (proposal_id) REFERENCES agent_proposal(id);

-- D-12/D-13/D-17: the database, not the app, decides the effective level.
-- effective = max(agent level, policy floor); missing policy => 4;
-- level 1 on a non-undoable action is raised to 2. Paused or disabled
-- agents cannot create proposals at all.
CREATE OR REPLACE FUNCTION agent_proposal_set_level() RETURNS trigger AS $$
DECLARE
  a_level   smallint;
  a_enabled boolean;
  p_level   smallint;
  p_undo    boolean;
  p_secs    integer;
BEGIN
  IF (SELECT agents_paused FROM tenant WHERE id = NEW.tenant_id) THEN
    RAISE EXCEPTION 'agents are paused (kill switch)';
  END IF;
  SELECT autonomy_level, is_enabled INTO a_level, a_enabled FROM agent WHERE id = NEW.agent_id;
  IF NOT a_enabled THEN
    RAISE EXCEPTION 'agent % is disabled', NEW.agent_id;
  END IF;
  SELECT min_autonomy_level, is_undoable, decision_deadline_s INTO p_level, p_undo, p_secs
    FROM action_policy WHERE tenant_id = NEW.tenant_id AND action_type = NEW.action_type;
  IF p_level IS NULL THEN
    NEW.effective_level := 4;
  ELSE
    NEW.effective_level := GREATEST(a_level, p_level);
    IF NEW.effective_level = 1 AND NOT p_undo THEN
      NEW.effective_level := 2;
    END IF;
  END IF;
  IF NEW.effective_level IN (2, 3) THEN
    NEW.deadline_at := now() + make_interval(secs => p_secs);
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER agent_proposal_level BEFORE INSERT ON agent_proposal
  FOR EACH ROW EXECUTE FUNCTION agent_proposal_set_level();

-- Effective level, action type and payload are frozen after insert.
-- Edits go into edited_action / edited_payload.
CREATE OR REPLACE FUNCTION agent_proposal_freeze() RETURNS trigger AS $$
BEGIN
  IF NEW.effective_level IS DISTINCT FROM OLD.effective_level
     OR NEW.action_type IS DISTINCT FROM OLD.action_type
     OR NEW.action_payload IS DISTINCT FROM OLD.action_payload
     OR NEW.agent_id IS DISTINCT FROM OLD.agent_id THEN
    RAISE EXCEPTION 'agent_proposal: effective_level, action_type, action_payload and agent_id are immutable';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER agent_proposal_frozen BEFORE UPDATE ON agent_proposal
  FOR EACH ROW EXECUTE FUNCTION agent_proposal_freeze();

CREATE TABLE proposal_approval (
  id              bigserial PRIMARY KEY,
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  proposal_id     uuid NOT NULL REFERENCES agent_proposal(id) ON DELETE CASCADE,
  step_no         smallint NOT NULL CHECK (step_no >= 1),
  required_role   text NOT NULL,
  decided_by      uuid REFERENCES app_user(id),
  decision        text CHECK (decision IN ('APPROVE','REJECT')),
  decided_at      timestamptz,
  UNIQUE (proposal_id, step_no),
  CHECK ((decision IS NULL) = (decided_by IS NULL))
);
-- D-16: one person can never fill two approval steps of the same proposal.
CREATE UNIQUE INDEX proposal_approval_distinct_user_uq ON proposal_approval (proposal_id, decided_by)
  WHERE decided_by IS NOT NULL;

-- D-16: steps are decided in order, once. Rows are created undecided.
CREATE OR REPLACE FUNCTION proposal_approval_in_order() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.decision IS NOT NULL THEN
      RAISE EXCEPTION 'proposal_approval: rows must be created undecided';
    END IF;
    RETURN NEW;
  END IF;
  IF OLD.decision IS NOT NULL THEN
    RAISE EXCEPTION 'proposal_approval: step % already decided', OLD.step_no;
  END IF;
  IF NEW.proposal_id <> OLD.proposal_id OR NEW.step_no <> OLD.step_no OR NEW.required_role <> OLD.required_role THEN
    RAISE EXCEPTION 'proposal_approval: proposal_id, step_no and required_role are immutable';
  END IF;
  IF NEW.decision IS NOT NULL AND EXISTS (
       SELECT 1 FROM proposal_approval
        WHERE proposal_id = NEW.proposal_id AND step_no < NEW.step_no
          AND decision IS DISTINCT FROM 'APPROVE') THEN
    RAISE EXCEPTION 'proposal_approval: earlier steps must be approved first';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER proposal_approval_order BEFORE INSERT OR UPDATE ON proposal_approval
  FOR EACH ROW EXECUTE FUNCTION proposal_approval_in_order();

-- D-16: approval steps are generated from the policy when the proposal is
-- created. Each approver_roles element is one step; an element may list
-- alternatives separated by '|' (e.g. 'DUTY_OFFICER|SECURITY_OFFICER').
-- Level 2 uses step 1 only (DUTY_OFFICER if the policy lists no roles). Level 3 uses steps 1 and 2; if the policy
-- defines only one step (agent set above the floor), step 2 is
-- HQ_CRISIS_DIRECTOR.
CREATE OR REPLACE FUNCTION agent_proposal_create_approvals() RETURNS trigger AS $$
DECLARE
  roles text[];
BEGIN
  IF NEW.effective_level NOT IN (2, 3) THEN
    RETURN NULL;
  END IF;
  SELECT approver_roles INTO roles FROM action_policy
   WHERE tenant_id = NEW.tenant_id AND action_type = NEW.action_type;
  INSERT INTO proposal_approval (tenant_id, proposal_id, step_no, required_role)
       VALUES (NEW.tenant_id, NEW.id, 1, COALESCE(roles[1], 'DUTY_OFFICER'));
  IF NEW.effective_level = 3 THEN
    INSERT INTO proposal_approval (tenant_id, proposal_id, step_no, required_role)
         VALUES (NEW.tenant_id, NEW.id, 2, COALESCE(roles[2], 'HQ_CRISIS_DIRECTOR'));
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER agent_proposal_approvals AFTER INSERT ON agent_proposal
  FOR EACH ROW EXECUTE FUNCTION agent_proposal_create_approvals();

-- ---------------------------------------------------------------------
-- 8. Reference numbers (D-18)
-- ---------------------------------------------------------------------
CREATE TABLE reference_counter (
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  prefix          text NOT NULL,                 -- INC, NTF, ...
  year            smallint NOT NULL DEFAULT 0,   -- 0 when the reference has no year
  last_value      integer NOT NULL DEFAULT 0,
  PRIMARY KEY (tenant_id, prefix, year)
);

-- next_reference('INC', true)  -> 'INC-2026-1042'
-- next_reference('NTF', false) -> 'NTF-3103'
CREATE OR REPLACE FUNCTION next_reference(p_prefix text, p_with_year boolean) RETURNS text AS $$
DECLARE
  t uuid := current_tenant_id();
  y smallint := CASE WHEN p_with_year THEN extract(year FROM now() AT TIME ZONE 'UTC')::smallint ELSE 0 END;
  v integer;
BEGIN
  IF t IS NULL THEN RAISE EXCEPTION 'next_reference: app.tenant_id is not set'; END IF;
  INSERT INTO reference_counter AS rc (tenant_id, prefix, year, last_value)
       VALUES (t, p_prefix, y, 1)
  ON CONFLICT (tenant_id, prefix, year) DO UPDATE SET last_value = rc.last_value + 1
  RETURNING last_value INTO v;
  RETURN p_prefix || '-' || CASE WHEN p_with_year THEN y::text || '-' ELSE '' END || lpad(v::text, 4, '0');
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------
-- 9. Audit (append-only, hash-chained in the database — D-20)
-- ---------------------------------------------------------------------
CREATE TABLE audit_log (
  id              bigserial PRIMARY KEY,
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  chain_seq       bigint NOT NULL,               -- set by trigger; gap-free per tenant
  occurred_at     timestamptz NOT NULL DEFAULT now(),
  actor_type      text NOT NULL CHECK (actor_type IN ('USER','AGENT','SYSTEM')),
  actor_id        text,
  action          text NOT NULL,                 -- e.g. PROPOSAL.APPROVE, PLAYBOOK.START, CAMPAIGN.SEND
  entity_type     text NOT NULL,
  entity_id       text,
  details         jsonb NOT NULL DEFAULT '{}',
  prev_hash       text,                          -- set by trigger
  row_hash        text NOT NULL,                 -- set by trigger
  UNIQUE (tenant_id, chain_seq)
);
CREATE INDEX audit_log_entity_idx ON audit_log (tenant_id, entity_type, entity_id, occurred_at);

-- Canonical content of one audit row (everything except the hashes).
-- jsonb sorts keys, and the function pins the time zone, so output is stable.
CREATE OR REPLACE FUNCTION audit_row_content(r audit_log) RETURNS text AS $$
  SELECT jsonb_build_object(
    'tenant_id', r.tenant_id, 'chain_seq', r.chain_seq, 'occurred_at', r.occurred_at,
    'actor_type', r.actor_type, 'actor_id', r.actor_id, 'action', r.action,
    'entity_type', r.entity_type, 'entity_id', r.entity_id, 'details', r.details)::text;
$$ LANGUAGE sql STABLE SET timezone = 'UTC';

CREATE OR REPLACE FUNCTION audit_log_chain() RETURNS trigger AS $$
DECLARE
  last_seq  bigint;
  last_hash text;
BEGIN
  -- Serialise writers per tenant so the chain cannot fork.
  PERFORM pg_advisory_xact_lock(hashtextextended('audit:' || NEW.tenant_id::text, 0));
  SELECT chain_seq, row_hash INTO last_seq, last_hash
    FROM audit_log WHERE tenant_id = NEW.tenant_id
    ORDER BY chain_seq DESC LIMIT 1;
  NEW.chain_seq := COALESCE(last_seq, 0) + 1;
  NEW.prev_hash := last_hash;
  NEW.row_hash  := encode(digest(COALESCE(last_hash, '') || audit_row_content(NEW), 'sha256'), 'hex');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET timezone = 'UTC';
CREATE TRIGGER audit_log_chain BEFORE INSERT ON audit_log
  FOR EACH ROW EXECUTE FUNCTION audit_log_chain();

CREATE OR REPLACE FUNCTION audit_log_block_mutation() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'audit_log is append-only';
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER audit_log_no_update BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION audit_log_block_mutation();
CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log
  FOR EACH STATEMENT EXECUTE FUNCTION audit_log_block_mutation();

-- Returns the first chain_seq that fails verification, or NULL if the
-- current tenant's chain is intact.
CREATE OR REPLACE FUNCTION audit_verify_chain() RETURNS bigint AS $$
DECLARE
  r audit_log;
  expected_prev text := NULL;
  expected_seq bigint := 1;
BEGIN
  FOR r IN SELECT * FROM audit_log WHERE tenant_id = current_tenant_id() ORDER BY chain_seq LOOP
    IF r.chain_seq <> expected_seq
       OR r.prev_hash IS DISTINCT FROM expected_prev
       OR r.row_hash <> encode(digest(COALESCE(r.prev_hash, '') || audit_row_content(r), 'sha256'), 'hex') THEN
      RETURN r.chain_seq;
    END IF;
    expected_prev := r.row_hash;
    expected_seq := expected_seq + 1;
  END LOOP;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE SET timezone = 'UTC';

-- ---------------------------------------------------------------------
-- 10. Scenario engine (simulated data & exercises)
-- ---------------------------------------------------------------------
CREATE TABLE scenario (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  code            text NOT NULL,                 -- e.g. NBO-CIVIL-UNREST
  name            text NOT NULL,
  description     text,
  UNIQUE (tenant_id, code)
);

CREATE TABLE scenario_event (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  scenario_id     uuid NOT NULL REFERENCES scenario(id) ON DELETE CASCADE,
  scene_no        smallint NOT NULL,
  offset_ms       integer NOT NULL CHECK (offset_ms >= 0),
  event_type      text NOT NULL,                 -- RAW_SIGNAL, CHECKIN_RESPONSE, LOCATION_UPDATE, ...
  payload         jsonb NOT NULL
);
CREATE INDEX scenario_event_order_idx ON scenario_event (scenario_id, scene_no, offset_ms);

CREATE TABLE scenario_run (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  scenario_id     uuid NOT NULL REFERENCES scenario(id),
  mode            text NOT NULL DEFAULT 'DEMO' CHECK (mode IN ('DEMO','EXERCISE')),
  current_scene   smallint NOT NULL DEFAULT 0,
  status          text NOT NULL DEFAULT 'IDLE' CHECK (status IN ('IDLE','PLAYING','PAUSED','FINISHED')),
  started_at      timestamptz,
  started_by      uuid REFERENCES app_user(id)
);

-- ---------------------------------------------------------------------
-- 11. Row-level security (tenant isolation — D-01, D-02, D-03)
-- ---------------------------------------------------------------------
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'app_user','role','user_role','mission','site','person','location_observation','person_location_current',
    'trip','trip_traveller','intel_source','raw_signal','incident','incident_signal','incident_exposure','incident_event',
    'playbook','playbook_step','playbook_run','playbook_run_step',
    'notification_campaign','notification_delivery','checkin_response',
    'agent','action_policy','agent_proposal','proposal_approval',
    'reference_counter','audit_log','scenario','scenario_event','scenario_run'
  ] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON %I USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id())', t);
  END LOOP;
END $$;

-- tenant: RLS on but NOT forced, so the owner-defined lookup function below
-- can resolve the issuer before any tenant is set (D-04).
ALTER TABLE tenant ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_self ON tenant USING (id = current_tenant_id()) WITH CHECK (id = current_tenant_id());

-- The only cross-tenant read the API may perform: issuer -> tenant id.
CREATE OR REPLACE FUNCTION resolve_tenant_by_issuer(p_issuer text) RETURNS uuid AS $$
  SELECT id FROM public.tenant WHERE oidc_issuer = p_issuer;
$$ LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public;
REVOKE ALL ON FUNCTION resolve_tenant_by_issuer(text) FROM PUBLIC;

-- ---------------------------------------------------------------------
-- 12. Views
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_incident_people_in_zone WITH (security_invoker = true) AS
SELECT i.id            AS incident_id,
       p.id            AS person_id,
       p.full_name,
       p.person_type,
       plc.place_label,
       plc.confidence,
       plc.primary_source,
       ST_Distance(i.location, plc.location)::int AS distance_m
FROM incident i
JOIN person_location_current plc
  ON plc.tenant_id = i.tenant_id
 AND ST_DWithin(i.location, plc.location, i.impact_radius_m)
JOIN person p ON p.id = plc.person_id AND p.is_active
WHERE i.status = 'ACTIVE';

-- D-07: the latest answer per person per check-in campaign.
CREATE OR REPLACE VIEW v_checkin_latest WITH (security_invoker = true) AS
SELECT DISTINCT ON (campaign_id, person_id)
       campaign_id, person_id, tenant_id, status, channel, note, responded_at
FROM checkin_response
ORDER BY campaign_id, person_id, responded_at DESC, id DESC;

-- ---------------------------------------------------------------------
-- 13. Grants for the runtime role (D-01)
-- ---------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nexira_app') THEN
    CREATE ROLE nexira_app NOLOGIN;
  END IF;
END $$;

GRANT USAGE ON SCHEMA public TO nexira_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO nexira_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO nexira_app;
GRANT EXECUTE ON FUNCTION resolve_tenant_by_issuer(text), next_reference(text, boolean),
                          audit_verify_chain(), current_tenant_id(), severity_rank(text) TO nexira_app;

-- Audit log: insert and read only.
REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM nexira_app;
-- Tenants: read own row; only the kill-switch columns are writable.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON tenant FROM nexira_app;
GRANT UPDATE (agents_paused, agents_paused_at, agents_paused_by) ON tenant TO nexira_app;
-- Note: PostGIS must be installed by a superuser in infra/postgres/init.sql
-- (CREATE EXTENSION above is then a no-op). spatial_ref_sys is owned by
-- that superuser, so the table grant above does not reach it.
