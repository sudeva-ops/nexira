-- Pilot module 8, Natural Hazards & Climate (D-38): PC-24 and PC-25, approved by the
-- product owner on 2026-10-31 (PR #63), with the plan's answers (docs/plan-pilot-hz.md,
-- PR #64; G-2 and G-8 amend PC-24). Runs as nexira_owner (D-01). RLS, grants and the
-- playbook-run rules: named human sign-off (D-29).

-- PC-24 · armed playbook runs (HZ-05). A run armed ahead of a forecast landfall waits as
-- SCHEDULED until scheduled_for, then becomes RUNNING (started by the worker, or "start
-- now" by a person) or DISARMED. Grants unchanged.
ALTER TABLE playbook_run ADD COLUMN scheduled_for timestamptz;
ALTER TABLE playbook_run DROP CONSTRAINT playbook_run_status_check;
ALTER TABLE playbook_run ADD CONSTRAINT playbook_run_status_check CHECK (status IN (
  'SCHEDULED','RUNNING','AWAITING_APPROVAL','COMPLETED','CANCELLED','FAILED','DISARMED'));
-- G-8: an armed run is live too, so a playbook is armed or running at most once per incident.
DROP INDEX playbook_run_live_uq;
CREATE UNIQUE INDEX playbook_run_live_uq ON playbook_run (playbook_id, incident_id)
  WHERE status IN ('SCHEDULED','RUNNING','AWAITING_APPROVAL');

-- The arming rules (plan-pilot-hz.md §4, G-2). The trigger runs as the caller; it reads
-- nothing but the row, so RLS does not matter here. search_path pinned, pg_temp last (the
-- lesson of Prompt 39).
CREATE FUNCTION playbook_run_guard() RETURNS trigger AS $$
BEGIN
  -- An armed or disarmed run is the record of a decision: kept (review of Prompt 54, L3).
  IF TG_OP = 'DELETE' THEN
    IF OLD.status IN ('SCHEDULED','DISARMED') THEN
      RAISE EXCEPTION 'playbook run: an armed or disarmed run is kept';
    END IF;
    RETURN OLD;
  END IF;

  IF TG_OP = 'INSERT' THEN
    IF NEW.status = 'SCHEDULED' THEN
      -- The real time, not the transaction's start (review of Prompt 54, L2).
      IF NEW.scheduled_for IS NULL OR NEW.scheduled_for <= clock_timestamp() THEN
        RAISE EXCEPTION 'playbook run: an armed run starts at a time in the future';
      END IF;
    ELSIF NEW.scheduled_for IS NOT NULL THEN
      RAISE EXCEPTION 'playbook run: only an armed run has a start time';
    ELSIF NEW.status = 'DISARMED' THEN
      RAISE EXCEPTION 'playbook run: only an armed run can be disarmed';
    END IF;
    RETURN NEW;
  END IF;

  -- UPDATE
  IF NEW.scheduled_for IS DISTINCT FROM OLD.scheduled_for THEN
    RAISE EXCEPTION 'playbook run: the start time is fixed once armed';
  END IF;
  IF OLD.status = 'DISARMED' AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'playbook run: a disarmed run is final';
  END IF;
  IF OLD.status = 'SCHEDULED' AND NEW.status NOT IN ('SCHEDULED','RUNNING','DISARMED') THEN
    RAISE EXCEPTION 'playbook run: an armed run can only start or be disarmed, not become %',
      NEW.status;
  END IF;
  IF OLD.status <> 'SCHEDULED' AND NEW.status IN ('SCHEDULED','DISARMED')
     AND NEW.status IS DISTINCT FROM OLD.status THEN
    RAISE EXCEPTION 'playbook run: a % run cannot become %', OLD.status, NEW.status;
  END IF;
  -- G-2: an armed run's start is when it starts, written by the database.
  IF OLD.status = 'SCHEDULED' AND NEW.status = 'RUNNING' THEN
    NEW.started_at := now();
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER playbook_run_guard BEFORE INSERT OR UPDATE OR DELETE ON playbook_run
  FOR EACH ROW EXECUTE FUNCTION playbook_run_guard();

-- PC-25 · long-term climate exposure per mission (HZ-08). Illustrative, fictional scores
-- (D-19). Reference data: no UPDATE or DELETE in the pilot.
CREATE TABLE mission_climate_risk (
  tenant_id   uuid NOT NULL REFERENCES tenant(id),
  mission_id  uuid NOT NULL REFERENCES mission(id),
  hazards     text[] NOT NULL
              CHECK (cardinality(hazards) BETWEEN 1 AND 10 AND array_position(hazards, NULL) IS NULL
                     AND array_position(hazards, '') IS NULL
                     AND length(array_to_string(hazards, '|')) <= 300),
  score_today smallint NOT NULL CHECK (score_today BETWEEN 0 AND 100),
  score_2050  smallint NOT NULL CHECK (score_2050 BETWEEN 0 AND 100),
  scenario    text NOT NULL CHECK (length(scenario) BETWEEN 1 AND 100),
  source      text NOT NULL DEFAULT 'Illustrative climate model (simulated)'
              CHECK (length(source) BETWEEN 1 AND 200),
  created_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, mission_id)
);
ALTER TABLE mission_climate_risk ENABLE ROW LEVEL SECURITY;
ALTER TABLE mission_climate_risk FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON mission_climate_risk
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT ON mission_climate_risk TO nexira_app;

-- Foreign keys ignore RLS, so the mission's tenant is checked here (the lesson of Prompts
-- 24 and 29). The tenant_id condition keeps the rule true for a role that bypasses RLS.
-- INSERT only, as the grants: a later UPDATE grant needs an UPDATE branch that keeps the
-- mission and tenant (as weather_current_guard).
CREATE FUNCTION mission_climate_risk_guard() RETURNS trigger AS $$
BEGIN
  PERFORM 1 FROM mission m WHERE m.id = NEW.mission_id AND m.tenant_id = NEW.tenant_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'climate risk: no such mission';
  END IF;
  NEW.created_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER mission_climate_risk_guard BEFORE INSERT ON mission_climate_risk
  FOR EACH ROW EXECUTE FUNCTION mission_climate_risk_guard();
