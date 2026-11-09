-- Pilot module 18, Exercise & Training (D-48): PC-51 and PC-52, approved by the product owner on
-- 2026-11-09 (PR #141), with the plan's answers (docs/plan-pilot-exr.md, PR #142). Runs as
-- nexira_owner (D-01). RLS and grants: named human sign-off (D-29). An exercise is a scenario run
-- in EXERCISE mode; the scores are worked out when it ends and stored once, frozen.

-- PC-51 · an exercise (EXR-02, EXR-04, EXR-06): RUNNING, then COMPLETED or ABANDONED once. An
-- ILLUSTRATIVE row is the seeded history (plan §5): no scenario or run, added COMPLETED with its
-- own past dates; every other row is written by the database's clock.
CREATE TABLE exercise (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenant(id),
  mission_id       uuid NOT NULL REFERENCES mission(id),
  scenario_id      uuid REFERENCES scenario(id),
  scenario_run_id  uuid UNIQUE REFERENCES scenario_run(id),
  incident_id      uuid REFERENCES incident(id),
  name             text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
  kind             text NOT NULL CHECK (kind IN ('TABLETOP','FUNCTIONAL','FULL_SCALE')),
  status           text NOT NULL DEFAULT 'RUNNING'
                   CHECK (status IN ('RUNNING','COMPLETED','ABANDONED')),
  overall_score    smallint CHECK (overall_score BETWEEN 0 AND 100),
  participants     integer CHECK (participants >= 0),
  reason           text CHECK (length(reason) BETWEEN 1 AND 500),
  source           text NOT NULL DEFAULT 'EXERCISE' CHECK (source IN ('EXERCISE','ILLUSTRATIVE')),
  started_by       uuid REFERENCES app_user(id),
  started_at       timestamptz NOT NULL DEFAULT now(),
  ended_by         uuid REFERENCES app_user(id),
  ended_at         timestamptz,
  CHECK ((source = 'ILLUSTRATIVE') = (scenario_id IS NULL)),
  CHECK ((source = 'ILLUSTRATIVE') = (scenario_run_id IS NULL)),
  CHECK (source = 'ILLUSTRATIVE' OR started_by IS NOT NULL),
  CHECK (status = 'COMPLETED' OR (overall_score IS NULL AND participants IS NULL)),
  CHECK (status <> 'COMPLETED' OR participants IS NOT NULL),
  CHECK ((status = 'ABANDONED') = (reason IS NOT NULL)),
  CHECK ((status = 'RUNNING') = (ended_at IS NULL)),
  CHECK (status = 'COMPLETED' OR incident_id IS NULL)
);
-- One running exercise per mission (EXR-02).
CREATE UNIQUE INDEX exercise_running_uq ON exercise (tenant_id, mission_id)
  WHERE status = 'RUNNING';
-- One exercise per scored incident (review of Prompt 113, L2).
CREATE UNIQUE INDEX exercise_incident_uq ON exercise (incident_id) WHERE incident_id IS NOT NULL;
CREATE INDEX exercise_mission_idx ON exercise (mission_id, ended_at DESC);
ALTER TABLE exercise ENABLE ROW LEVEL SECURITY;
ALTER TABLE exercise FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON exercise
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT ON exercise TO nexira_app;
GRANT UPDATE (incident_id, status, overall_score, participants, reason, ended_by)
  ON exercise TO nexira_app;

-- Foreign keys ignore RLS, so every reference's tenant is checked here (the lesson of Prompts 24
-- and 29). A DELETE is refused for every role.
CREATE FUNCTION exercise_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'exercise: the exercise is kept';
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF (NEW.id, NEW.tenant_id, NEW.mission_id, NEW.scenario_id, NEW.scenario_run_id, NEW.name,
        NEW.kind, NEW.source, NEW.started_by, NEW.started_at)
       IS DISTINCT FROM
       (OLD.id, OLD.tenant_id, OLD.mission_id, OLD.scenario_id, OLD.scenario_run_id, OLD.name,
        OLD.kind, OLD.source, OLD.started_by, OLD.started_at) THEN
      RAISE EXCEPTION 'exercise: only ending changes it';
    END IF;
    IF OLD.status <> 'RUNNING' OR NEW.status NOT IN ('COMPLETED','ABANDONED') THEN
      RAISE EXCEPTION 'exercise: an exercise ends once';
    END IF;
    PERFORM 1 FROM app_user u WHERE u.id = NEW.ended_by AND u.tenant_id = NEW.tenant_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'exercise: no such user';
    END IF;
    -- The scored incident is at the exercise's mission (plan §2).
    IF NEW.incident_id IS NOT NULL THEN
      PERFORM 1 FROM incident i
       WHERE i.id = NEW.incident_id AND i.tenant_id = NEW.tenant_id
         AND i.mission_id = NEW.mission_id;
      IF NOT FOUND THEN
        RAISE EXCEPTION 'exercise: no such incident at the mission';
      END IF;
    END IF;
    NEW.ended_at := now();
    RETURN NEW;
  END IF;
  PERFORM 1 FROM mission m WHERE m.id = NEW.mission_id AND m.tenant_id = NEW.tenant_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'exercise: no such mission';
  END IF;
  IF NEW.source = 'ILLUSTRATIVE' THEN
    -- The seeded history: completed, scored, in the past, by nobody in particular.
    IF NEW.status <> 'COMPLETED' OR NEW.incident_id IS NOT NULL OR NEW.started_by IS NOT NULL
       OR NEW.ended_by IS NOT NULL THEN
      RAISE EXCEPTION 'exercise: an illustrative exercise is seeded completed';
    END IF;
    IF NEW.ended_at > now() OR NEW.started_at > NEW.ended_at THEN
      RAISE EXCEPTION 'exercise: an illustrative exercise is in the past';
    END IF;
    RETURN NEW;
  END IF;
  -- FOR SHARE holds the run against a concurrent change of its mode or scenario, which
  -- exercise_run_guard refuses once this row exists (review of Prompt 113, M1).
  PERFORM 1 FROM scenario_run r
   WHERE r.id = NEW.scenario_run_id AND r.tenant_id = NEW.tenant_id
     AND r.scenario_id = NEW.scenario_id AND r.mode = 'EXERCISE' FOR SHARE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'exercise: no such exercise run';
  END IF;
  PERFORM 1 FROM app_user u WHERE u.id = NEW.started_by AND u.tenant_id = NEW.tenant_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'exercise: no such user';
  END IF;
  IF NEW.status <> 'RUNNING' OR NEW.ended_by IS NOT NULL OR NEW.incident_id IS NOT NULL THEN
    RAISE EXCEPTION 'exercise: an exercise starts running';
  END IF;
  NEW.started_at := now();
  NEW.ended_at := NULL;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER exercise_guard BEFORE INSERT OR UPDATE OR DELETE ON exercise
  FOR EACH ROW EXECUTE FUNCTION exercise_guard();

-- An exercise's run keeps its tenant, scenario and EXERCISE mode: the label and fusion's
-- separation rest on them (plan §4). nexira_app still updates the run's status and scene, as the
-- scenario engine does (review of Prompt 113, M1).
CREATE FUNCTION exercise_run_guard() RETURNS trigger AS $$
BEGIN
  IF (NEW.id, NEW.tenant_id, NEW.scenario_id, NEW.mode)
     IS DISTINCT FROM (OLD.id, OLD.tenant_id, OLD.scenario_id, OLD.mode) THEN
    PERFORM 1 FROM exercise e WHERE e.scenario_run_id = OLD.id;
    IF FOUND THEN
      RAISE EXCEPTION 'scenario run: an exercise''s run keeps its scenario and mode';
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER exercise_run_guard BEFORE UPDATE ON scenario_run
  FOR EACH ROW EXECUTE FUNCTION exercise_run_guard();

-- PC-52 · the five frozen scores of a completed exercise (EXR-05); a null score is "—".
CREATE TABLE exercise_score (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES tenant(id),
  exercise_id  uuid NOT NULL REFERENCES exercise(id),
  dimension    text NOT NULL CHECK (dimension IN ('DETECTION','ACCOUNTABILITY','DECISION_SPEED',
                 'COMMUNICATION','PLAN_ADHERENCE')),
  score        smallint CHECK (score BETWEEN 0 AND 100),
  measured     jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(measured) = 'object'),
  created_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (exercise_id, dimension)
);
ALTER TABLE exercise_score ENABLE ROW LEVEL SECURITY;
ALTER TABLE exercise_score FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON exercise_score
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT ON exercise_score TO nexira_app;

CREATE FUNCTION exercise_score_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION 'exercise score: a score is frozen';
  END IF;
  PERFORM 1 FROM exercise e
   WHERE e.id = NEW.exercise_id AND e.tenant_id = NEW.tenant_id AND e.status = 'COMPLETED';
  IF NOT FOUND THEN
    RAISE EXCEPTION 'exercise score: no such completed exercise';
  END IF;
  NEW.created_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER exercise_score_guard BEFORE INSERT OR UPDATE OR DELETE ON exercise_score
  FOR EACH ROW EXECUTE FUNCTION exercise_score_guard();

-- Checked at commit: a completed exercise has all five scores, and its overall score is their
-- rounded mean ("—" scores left out; none when every score is "—"). With the UNIQUE above, no
-- score can be added later either, so the scores are written in the transaction that completes
-- the exercise or not at all.
CREATE FUNCTION exercise_scored_check() RETURNS trigger AS $$
DECLARE
  dimensions integer;
  mean smallint;
BEGIN
  SELECT count(*), round(avg(s.score)) INTO dimensions, mean
    FROM exercise_score s WHERE s.exercise_id = NEW.id;
  IF dimensions <> 5 THEN
    RAISE EXCEPTION 'exercise: a completed exercise has its five scores';
  END IF;
  IF NEW.overall_score IS DISTINCT FROM mean THEN
    RAISE EXCEPTION 'exercise: the overall score is the mean of the scores';
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE CONSTRAINT TRIGGER exercise_scored_check AFTER INSERT OR UPDATE ON exercise
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW WHEN (NEW.status = 'COMPLETED') EXECUTE FUNCTION exercise_scored_check();

-- Row triggers do not fire on TRUNCATE, which the owner holds; refused too, as audit_log's.
CREATE FUNCTION exercise_no_truncate_guard() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'exercise: exercises and scores are kept';
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER exercise_no_truncate BEFORE TRUNCATE ON exercise
  FOR EACH STATEMENT EXECUTE FUNCTION exercise_no_truncate_guard();
CREATE TRIGGER exercise_score_no_truncate BEFORE TRUNCATE ON exercise_score
  FOR EACH STATEMENT EXECUTE FUNCTION exercise_no_truncate_guard();
