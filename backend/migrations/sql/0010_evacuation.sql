-- Pilot module 10, Evacuation Management (D-40): PC-30..32, approved by the product owner on
-- 2026-11-01 (PR #77), with the plan's answers (docs/plan-pilot-ev.md, PR #78; G-1 adds
-- evacuation.requested_role). Runs as nexira_owner (D-01). RLS and grants: named human
-- sign-off (D-29). Plans are illustrative and every movement is simulated (D-19).

-- PC-30 · an evacuation plan per mission (EV-01). Seeded through the service layer and never
-- changed in the pilot (§53 Q1).
CREATE TABLE evacuation_plan (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  mission_id      uuid NOT NULL REFERENCES mission(id),
  reference       text NOT NULL CHECK (reference ~ '^EVP-[A-Z]{3}$'),
  muster_name     text NOT NULL CHECK (length(muster_name) BETWEEN 1 AND 150),
  muster_location geography(Point,4326) NOT NULL,
  route_label     text NOT NULL CHECK (length(route_label) BETWEEN 1 AND 150),
  destination     text NOT NULL CHECK (length(destination) BETWEEN 1 AND 150),
  -- At most three transport options, PRIMARY first; their shape is checked by the guard.
  options         jsonb NOT NULL CHECK (jsonb_typeof(options) = 'array'),
  source          text NOT NULL DEFAULT 'Illustrative evacuation plan (simulated)'
                  CHECK (length(source) BETWEEN 1 AND 200),
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, mission_id),
  UNIQUE (tenant_id, reference)
);
ALTER TABLE evacuation_plan ENABLE ROW LEVEL SECURITY;
ALTER TABLE evacuation_plan FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON evacuation_plan
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT ON evacuation_plan TO nexira_app;

-- Foreign keys ignore RLS, so the mission's and every partner's tenant are checked here (the
-- lesson of Prompts 24 and 29). BEFORE triggers run before CHECK constraints, so the guard
-- checks each option's types before reading them (the lesson of Prompt 60). An UPDATE or a
-- DELETE is refused for every role, the owner included (review of Prompt 66, L2).
CREATE FUNCTION evacuation_plan_guard() RETURNS trigger AS $$
DECLARE
  option jsonb;
  roles text[] := '{}';
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'evacuation plan: plans are kept';
  END IF;
  IF TG_OP = 'UPDATE' THEN
    RAISE EXCEPTION 'evacuation plan: seeded plans are not changed';
  END IF;
  PERFORM 1 FROM mission m WHERE m.id = NEW.mission_id AND m.tenant_id = NEW.tenant_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'evacuation plan: no such mission';
  END IF;
  IF jsonb_typeof(NEW.options) IS DISTINCT FROM 'array'
     OR jsonb_array_length(NEW.options) NOT BETWEEN 1 AND 3 THEN
    RAISE EXCEPTION 'evacuation plan: one to three options';
  END IF;
  FOR option IN SELECT value FROM jsonb_array_elements(NEW.options) LOOP
    IF jsonb_typeof(option) <> 'object'
       OR NOT (option ?& ARRAY['role', 'kind', 'label'])
       OR EXISTS (SELECT 1 FROM jsonb_object_keys(option) k
                   WHERE k NOT IN ('role', 'kind', 'label', 'seats', 'partner_id'))
       OR jsonb_typeof(option->'role') <> 'string'
       OR jsonb_typeof(option->'kind') <> 'string'
       OR jsonb_typeof(option->'label') <> 'string' THEN
      RAISE EXCEPTION 'evacuation plan: an option has role, kind, label, seats and partner_id only';
    END IF;
    IF option->>'role' NOT IN ('PRIMARY', 'BACKUP', 'CONTINGENCY')
       OR option->>'kind' NOT IN ('CHARTER', 'COMMERCIAL', 'ROAD')
       OR length(option->>'label') NOT BETWEEN 1 AND 200 THEN
      RAISE EXCEPTION 'evacuation plan: bad option role, kind or label';
    END IF;
    IF option->>'role' = ANY(roles) THEN
      RAISE EXCEPTION 'evacuation plan: each role once';
    END IF;
    roles := roles || (option->>'role');
    IF option ? 'seats' AND jsonb_typeof(option->'seats') <> 'null' AND (
         jsonb_typeof(option->'seats') <> 'number'
         OR (option->>'seats') !~ '^[0-9]{1,4}$'
         OR (option->>'seats')::int NOT BETWEEN 1 AND 1000) THEN
      RAISE EXCEPTION 'evacuation plan: seats is a whole number from 1 to 1000';
    END IF;
    IF option ? 'partner_id' AND jsonb_typeof(option->'partner_id') <> 'null' THEN
      IF jsonb_typeof(option->'partner_id') <> 'string'
         OR (option->>'partner_id') !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
        RAISE EXCEPTION 'evacuation plan: partner_id is a partner id';
      END IF;
      PERFORM 1 FROM partner p
       WHERE p.id = (option->>'partner_id')::uuid AND p.tenant_id = NEW.tenant_id;
      IF NOT FOUND THEN
        RAISE EXCEPTION 'evacuation plan: no such partner';
      END IF;
    END IF;
  END LOOP;
  IF NOT ('PRIMARY' = ANY(roles)) OR NEW.options->0->>'role' <> 'PRIMARY' THEN
    RAISE EXCEPTION 'evacuation plan: the primary option comes first';
  END IF;
  NEW.created_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER evacuation_plan_guard BEFORE INSERT OR UPDATE OR DELETE ON evacuation_plan
  FOR EACH ROW EXECUTE FUNCTION evacuation_plan_guard();

-- PC-31 · an evacuation: requested by one person, activated by another (EV-02, D-40), then
-- its sequence (EV-05) until it is complete or stood down (EV-07). The roles are checked in
-- app/core/approvals.py; the database is the backstop for the two people and the order.
CREATE TABLE evacuation (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          uuid NOT NULL REFERENCES tenant(id),
  reference          text NOT NULL CHECK (reference ~ '^EVN-[0-9]{4,}$'),
  plan_id            uuid NOT NULL REFERENCES evacuation_plan(id),
  mission_id         uuid NOT NULL REFERENCES mission(id),
  incident_id        uuid REFERENCES incident(id),
  proposal_id        uuid REFERENCES agent_proposal(id),
  status             text NOT NULL DEFAULT 'PENDING_ACTIVATION'
                     CHECK (status IN ('PENDING_ACTIVATION','ACTIVE','COMPLETED','STOOD_DOWN')),
  requested_by       uuid NOT NULL REFERENCES app_user(id),
  -- The role the requester used; the confirmer holds the other (plan-pilot-ev G-1).
  requested_role     text NOT NULL CHECK (requested_role IN ('HEAD_OF_MISSION','HQ_CRISIS_DIRECTOR')),
  requested_at       timestamptz NOT NULL DEFAULT now(),
  activated_by       uuid REFERENCES app_user(id),
  activated_at       timestamptz,
  step               smallint CHECK (step BETWEEN 1 AND 6),
  step_times         jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(step_times) = 'object'),
  stood_down_by      uuid REFERENCES app_user(id),
  stood_down_reason  text CHECK (length(stood_down_reason) BETWEEN 1 AND 500),
  stood_down_at      timestamptz,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, reference),
  CHECK (activated_by IS NULL OR activated_by <> requested_by),
  CHECK ((activated_by IS NULL) = (activated_at IS NULL)),
  CHECK ((activated_by IS NULL) = (step IS NULL)),
  CHECK (status NOT IN ('ACTIVE','COMPLETED') OR activated_by IS NOT NULL),
  CHECK ((status = 'COMPLETED') = (step IS NOT DISTINCT FROM 6)),
  CHECK ((status = 'STOOD_DOWN') = (stood_down_by IS NOT NULL)),
  CHECK ((stood_down_by IS NULL) = (stood_down_reason IS NULL)),
  CHECK ((stood_down_by IS NULL) = (stood_down_at IS NULL))
);
-- One live evacuation per mission.
CREATE UNIQUE INDEX evacuation_live_uq ON evacuation (tenant_id, mission_id)
  WHERE status IN ('PENDING_ACTIVATION','ACTIVE');
-- One evacuation per proposal (review of Prompt 66, L3).
CREATE UNIQUE INDEX evacuation_proposal_uq ON evacuation (proposal_id) WHERE proposal_id IS NOT NULL;
CREATE INDEX evacuation_mission_idx ON evacuation (tenant_id, mission_id, created_at);
ALTER TABLE evacuation ENABLE ROW LEVEL SECURITY;
ALTER TABLE evacuation FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON evacuation
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT ON evacuation TO nexira_app;
GRANT UPDATE (status, activated_by, step, stood_down_by, stood_down_reason) ON evacuation
  TO nexira_app;

CREATE FUNCTION evacuation_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'evacuation: evacuations are kept';
  END IF;
  IF TG_OP = 'INSERT' THEN
    IF NEW.status <> 'PENDING_ACTIVATION' OR NEW.activated_by IS NOT NULL OR NEW.step IS NOT NULL
       OR NEW.stood_down_by IS NOT NULL OR NEW.stood_down_reason IS NOT NULL THEN
      RAISE EXCEPTION 'evacuation: an evacuation starts as a request';
    END IF;
    PERFORM 1 FROM evacuation_plan p
     WHERE p.id = NEW.plan_id AND p.tenant_id = NEW.tenant_id AND p.mission_id = NEW.mission_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'evacuation: no such plan for this mission';
    END IF;
    IF NEW.incident_id IS NOT NULL THEN
      PERFORM 1 FROM incident i
       WHERE i.id = NEW.incident_id AND i.tenant_id = NEW.tenant_id
         AND i.mission_id = NEW.mission_id;
      IF NOT FOUND THEN
        RAISE EXCEPTION 'evacuation: no such incident at this mission';
      END IF;
    END IF;
    -- Only an evacuation proposal activates an evacuation (review of Prompt 66, L3).
    IF NEW.proposal_id IS NOT NULL THEN
      PERFORM 1 FROM agent_proposal a
       WHERE a.id = NEW.proposal_id AND a.tenant_id = NEW.tenant_id
         AND a.action_type = 'START_EVACUATION';
      IF NOT FOUND THEN
        RAISE EXCEPTION 'evacuation: no such evacuation proposal';
      END IF;
    END IF;
    PERFORM 1 FROM app_user u WHERE u.id = NEW.requested_by AND u.tenant_id = NEW.tenant_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'evacuation: no such user';
    END IF;
    NEW.requested_at := now();
    NEW.activated_at := NULL;
    NEW.stood_down_at := NULL;
    NEW.step_times := '{}'::jsonb;
    NEW.created_at := now();
    NEW.updated_at := now();
    RETURN NEW;
  END IF;

  -- UPDATE
  IF OLD.status IN ('COMPLETED', 'STOOD_DOWN') THEN
    RAISE EXCEPTION 'evacuation: a % evacuation is final', lower(replace(OLD.status, '_', ' '));
  END IF;
  IF (NEW.id, NEW.tenant_id, NEW.reference, NEW.plan_id, NEW.mission_id, NEW.incident_id,
      NEW.proposal_id, NEW.requested_by, NEW.requested_role, NEW.requested_at, NEW.created_at)
     IS DISTINCT FROM
     (OLD.id, OLD.tenant_id, OLD.reference, OLD.plan_id, OLD.mission_id, OLD.incident_id,
      OLD.proposal_id, OLD.requested_by, OLD.requested_role, OLD.requested_at, OLD.created_at) THEN
    RAISE EXCEPTION 'evacuation: what was requested is fixed';
  END IF;
  IF NEW.activated_by IS DISTINCT FROM OLD.activated_by
     AND NOT (OLD.status = 'PENDING_ACTIVATION' AND NEW.status = 'ACTIVE') THEN
    RAISE EXCEPTION 'evacuation: the activator is set once, on activation';
  END IF;
  IF (NEW.stood_down_by, NEW.stood_down_reason) IS DISTINCT FROM (OLD.stood_down_by, OLD.stood_down_reason)
     AND NEW.status <> 'STOOD_DOWN' THEN
    RAISE EXCEPTION 'evacuation: a stand-down sets the status';
  END IF;

  IF NEW.status <> OLD.status THEN
    IF NOT ((OLD.status = 'PENDING_ACTIVATION' AND NEW.status IN ('ACTIVE', 'STOOD_DOWN'))
            OR (OLD.status = 'ACTIVE' AND NEW.status IN ('COMPLETED', 'STOOD_DOWN'))) THEN
      RAISE EXCEPTION 'evacuation: % cannot become %', OLD.status, NEW.status;
    END IF;
  END IF;

  IF OLD.status = 'PENDING_ACTIVATION' AND NEW.status = 'ACTIVE' THEN
    IF NEW.activated_by IS NULL THEN
      RAISE EXCEPTION 'evacuation: activation needs the second person';
    END IF;
    IF NEW.activated_by = OLD.requested_by THEN
      RAISE EXCEPTION 'evacuation: the requester cannot also activate (D-40)';
    END IF;
    PERFORM 1 FROM app_user u WHERE u.id = NEW.activated_by AND u.tenant_id = NEW.tenant_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'evacuation: no such user';
    END IF;
    IF NEW.step IS DISTINCT FROM 2 THEN
      RAISE EXCEPTION 'evacuation: activation decides and confirms the manifest (step 2)';
    END IF;
    NEW.activated_at := now();
    NEW.step_times := jsonb_build_object('1', now(), '2', now());
  ELSIF NEW.status = 'STOOD_DOWN' THEN
    IF OLD.status = 'ACTIVE' AND OLD.step >= 5 THEN
      RAISE EXCEPTION 'evacuation: the flight has departed; it can no longer be stood down';
    END IF;
    IF NEW.stood_down_by IS NULL OR NEW.stood_down_reason IS NULL THEN
      RAISE EXCEPTION 'evacuation: a stand-down needs who and why';
    END IF;
    PERFORM 1 FROM app_user u WHERE u.id = NEW.stood_down_by AND u.tenant_id = NEW.tenant_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'evacuation: no such user';
    END IF;
    IF NEW.step IS DISTINCT FROM OLD.step THEN
      RAISE EXCEPTION 'evacuation: a stand-down does not move the sequence';
    END IF;
    NEW.stood_down_at := now();
    NEW.step_times := OLD.step_times;
    NEW.activated_at := OLD.activated_at;
  ELSE
    -- ACTIVE, staying ACTIVE or becoming COMPLETED: the sequence moves one step at a time.
    IF NEW.status = 'PENDING_ACTIVATION' AND NEW.step IS NOT NULL THEN
      RAISE EXCEPTION 'evacuation: the sequence starts on activation';
    END IF;
    IF NEW.step IS DISTINCT FROM OLD.step THEN
      IF OLD.status <> 'ACTIVE' OR NEW.step IS DISTINCT FROM OLD.step + 1 THEN
        RAISE EXCEPTION 'evacuation: the sequence moves forward one step at a time';
      END IF;
      NEW.step_times := OLD.step_times || jsonb_build_object(NEW.step::text, now());
    ELSE
      NEW.step_times := OLD.step_times;
    END IF;
    IF NEW.status = 'COMPLETED' AND NEW.step IS DISTINCT FROM 6 THEN
      RAISE EXCEPTION 'evacuation: complete only on arrival (step 6)';
    END IF;
    NEW.activated_at := OLD.activated_at;
  END IF;
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER evacuation_guard BEFORE INSERT OR UPDATE OR DELETE ON evacuation
  FOR EACH ROW EXECUTE FUNCTION evacuation_guard();

-- PC-32 · the manifest (EV-03) and the muster check-in (EV-04). Locked at activation: rows
-- are added only in the transaction that activated the evacuation, and never removed.
CREATE TABLE evacuation_manifest (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id           uuid NOT NULL REFERENCES tenant(id),
  evacuation_id       uuid NOT NULL REFERENCES evacuation(id),
  person_id           uuid NOT NULL REFERENCES person(id),
  category            text NOT NULL CHECK (category IN ('STAFF','DELEGATE','DEPENDANT','CITIZEN')),
  seat                text CHECK (seat ~ '^[0-9]{1,3}[A-Z]$'),
  status              text NOT NULL DEFAULT 'EXPECTED' CHECK (status IN ('EXPECTED','CHECKED_IN')),
  checked_in_by_type  text CHECK (checked_in_by_type IN ('USER','SCANNER')),
  checked_in_by       text CHECK (length(checked_in_by) BETWEEN 1 AND 100),
  checked_in_at       timestamptz,
  created_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE (evacuation_id, person_id),
  UNIQUE (evacuation_id, seat),
  CHECK ((status = 'CHECKED_IN') = (checked_in_by_type IS NOT NULL)),
  CHECK ((checked_in_by_type IS NULL) = (checked_in_by IS NULL)),
  CHECK ((checked_in_by_type IS NULL) = (checked_in_at IS NULL)),
  CHECK (seat IS NULL OR status = 'CHECKED_IN')
);
CREATE INDEX evacuation_manifest_evacuation_idx ON evacuation_manifest (tenant_id, evacuation_id);
ALTER TABLE evacuation_manifest ENABLE ROW LEVEL SECURITY;
ALTER TABLE evacuation_manifest FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON evacuation_manifest
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT ON evacuation_manifest TO nexira_app;
GRANT UPDATE (status, seat, checked_in_by_type, checked_in_by) ON evacuation_manifest
  TO nexira_app;

CREATE FUNCTION evacuation_manifest_guard() RETURNS trigger AS $$
DECLARE
  evac evacuation%ROWTYPE;
  ptype text;
  expected text;
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'evacuation manifest: the manifest is kept';
  END IF;
  -- FOR SHARE: a check-in waits for a concurrent stand-down or completion and then sees it,
  -- so nothing is checked in once the evacuation is final (review of Prompt 66, M1).
  SELECT * INTO evac FROM evacuation e
   WHERE e.id = NEW.evacuation_id AND e.tenant_id = NEW.tenant_id
   FOR SHARE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'evacuation manifest: no such evacuation';
  END IF;

  IF TG_OP = 'INSERT' THEN
    -- Locked at activation (EV-03): the activating transaction wrote activated_at = now().
    IF evac.status <> 'ACTIVE' OR evac.step <> 2 OR evac.activated_at <> now() THEN
      RAISE EXCEPTION 'evacuation manifest: the manifest is built at activation only';
    END IF;
    SELECT p.person_type INTO ptype FROM person p
     WHERE p.id = NEW.person_id AND p.tenant_id = NEW.tenant_id AND p.mission_id = evac.mission_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'evacuation manifest: no such person at this mission';
    END IF;
    -- Local staff and contractors are not evacuated (§53 Q3).
    expected := CASE ptype WHEN 'DIPLOMAT' THEN 'STAFF' WHEN 'DELEGATE' THEN 'DELEGATE'
                           WHEN 'DEPENDANT' THEN 'DEPENDANT' WHEN 'CITIZEN' THEN 'CITIZEN' END;
    IF NEW.category IS DISTINCT FROM expected THEN
      RAISE EXCEPTION 'evacuation manifest: % is not evacuated as %', ptype, NEW.category;
    END IF;
    IF NEW.status <> 'EXPECTED' OR NEW.seat IS NOT NULL OR NEW.checked_in_by_type IS NOT NULL THEN
      RAISE EXCEPTION 'evacuation manifest: everyone starts expected';
    END IF;
    NEW.checked_in_at := NULL;
    NEW.created_at := now();
    RETURN NEW;
  END IF;

  -- UPDATE: only a check-in, once, while the evacuation is live.
  IF evac.status <> 'ACTIVE' THEN
    RAISE EXCEPTION 'evacuation manifest: the evacuation is not active';
  END IF;
  IF (NEW.id, NEW.tenant_id, NEW.evacuation_id, NEW.person_id, NEW.category, NEW.created_at)
     IS DISTINCT FROM
     (OLD.id, OLD.tenant_id, OLD.evacuation_id, OLD.person_id, OLD.category, OLD.created_at) THEN
    RAISE EXCEPTION 'evacuation manifest: who is on the manifest is fixed';
  END IF;
  IF OLD.status = 'CHECKED_IN' THEN
    RAISE EXCEPTION 'evacuation manifest: a check-in is final';
  END IF;
  IF NEW.status <> 'CHECKED_IN' THEN
    RAISE EXCEPTION 'evacuation manifest: the only change is a check-in';
  END IF;
  IF NEW.checked_in_by_type = 'USER' THEN
    IF NEW.checked_in_by !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
      RAISE EXCEPTION 'evacuation manifest: no such user';
    END IF;
    PERFORM 1 FROM app_user u WHERE u.id = NEW.checked_in_by::uuid AND u.tenant_id = NEW.tenant_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'evacuation manifest: no such user';
    END IF;
  END IF;
  NEW.checked_in_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER evacuation_manifest_guard BEFORE INSERT OR UPDATE OR DELETE ON evacuation_manifest
  FOR EACH ROW EXECUTE FUNCTION evacuation_manifest_guard();
