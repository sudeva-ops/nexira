-- Pilot module 16, Predictive Risk (D-46): PC-46 and PC-47, approved by the product owner on
-- 2026-11-03 (PR #126), with the plan's answers (docs/plan-pilot-prd.md, PR #127; G-1 option B:
-- PC-48 is an agent row only, no table). Runs as nexira_owner (D-01). RLS and grants: named
-- human sign-off (D-29). The index is an illustrative, explainable model; the calendar and the
-- first 30 days of history are simulated (D-19). The forecast is worked out on read, not stored.

-- PC-46 · the daily risk index per mission (PRD-01): ILLUSTRATIVE history before today, then one
-- COMPUTED row a day that the snapshot keeps current during that day only.
CREATE TABLE risk_index (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES tenant(id),
  mission_id   uuid NOT NULL REFERENCES mission(id),
  day          date NOT NULL,
  value        smallint NOT NULL CHECK (value BETWEEN 0 AND 100),
  components   jsonb NOT NULL CHECK (jsonb_typeof(components) = 'object'),
  source       text NOT NULL CHECK (source IN ('COMPUTED','ILLUSTRATIVE')),
  computed_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (mission_id, day)
);
ALTER TABLE risk_index ENABLE ROW LEVEL SECURITY;
ALTER TABLE risk_index FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON risk_index
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT ON risk_index TO nexira_app;
GRANT UPDATE (value, components) ON risk_index TO nexira_app;

-- Foreign keys ignore RLS, so the mission's tenant is checked here (the lesson of Prompts 24 and
-- 29). "Today" is the UTC date, as the snapshot's. A DELETE is refused for every role.
CREATE FUNCTION predictive_risk_index_guard() RETURNS trigger AS $$
DECLARE
  today date := (now() AT TIME ZONE 'UTC')::date;
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'risk index: the history is kept';
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF (NEW.id, NEW.tenant_id, NEW.mission_id, NEW.day, NEW.source)
       IS DISTINCT FROM (OLD.id, OLD.tenant_id, OLD.mission_id, OLD.day, OLD.source) THEN
      RAISE EXCEPTION 'risk index: only the value and components change';
    END IF;
    IF OLD.source <> 'COMPUTED' OR OLD.day <> today THEN
      RAISE EXCEPTION 'risk index: only today''s computed row changes';
    END IF;
    NEW.computed_at := now();
    RETURN NEW;
  END IF;
  PERFORM 1 FROM mission m WHERE m.id = NEW.mission_id AND m.tenant_id = NEW.tenant_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'risk index: no such mission';
  END IF;
  -- A computed row is today's snapshot; illustrative history lies before today.
  IF NEW.source = 'COMPUTED' AND NEW.day <> today THEN
    RAISE EXCEPTION 'risk index: a computed row is for today';
  END IF;
  IF NEW.source = 'ILLUSTRATIVE' AND NEW.day >= today THEN
    RAISE EXCEPTION 'risk index: illustrative history lies before today';
  END IF;
  NEW.computed_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER predictive_risk_index_guard BEFORE INSERT OR UPDATE OR DELETE ON risk_index
  FOR EACH ROW EXECUTE FUNCTION predictive_risk_index_guard();

-- PC-47 · the events calendar per mission (PRD-05): seeded and added by the scenario; fixed.
CREATE TABLE mission_event (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES tenant(id),
  mission_id   uuid NOT NULL REFERENCES mission(id),
  kind         text NOT NULL CHECK (kind IN ('RALLY','ELECTION','HOLIDAY','SUMMIT','SPORTS','OTHER')),
  title        text NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
  place_label  text CHECK (length(place_label) BETWEEN 1 AND 200),
  location     geography(Point,4326),
  starts_on    date NOT NULL,
  ends_on      date NOT NULL,
  attendance   integer CHECK (attendance >= 0),
  weight       smallint NOT NULL CHECK (weight BETWEEN 1 AND 30),
  source       text NOT NULL DEFAULT 'Illustrative events calendar (simulated)'
               CHECK (length(source) BETWEEN 1 AND 200),
  created_at   timestamptz NOT NULL DEFAULT now(),
  CHECK (ends_on >= starts_on)
);
CREATE INDEX mission_event_mission_idx ON mission_event (tenant_id, mission_id, starts_on);
ALTER TABLE mission_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE mission_event FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON mission_event
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT ON mission_event TO nexira_app;

CREATE FUNCTION predictive_mission_event_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION 'mission event: the calendar entry is fixed';
  END IF;
  PERFORM 1 FROM mission m WHERE m.id = NEW.mission_id AND m.tenant_id = NEW.tenant_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'mission event: no such mission';
  END IF;
  NEW.created_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER predictive_mission_event_guard BEFORE INSERT OR UPDATE OR DELETE ON mission_event
  FOR EACH ROW EXECUTE FUNCTION predictive_mission_event_guard();
