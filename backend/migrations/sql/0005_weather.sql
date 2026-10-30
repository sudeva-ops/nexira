-- Pilot module 6, Weather (D-35): PC-20, approved by the product owner on 2026-10-30
-- (PR #43), with the plan's answers (docs/plan-pilot-wx.md, PR #44). Runs as nexira_owner
-- (D-01). RLS and grants: named human sign-off (D-29).

-- PC-20 · current simulated conditions, one row per mission (D-19: shown as simulated).
CREATE TABLE weather_current (
  tenant_id      uuid NOT NULL REFERENCES tenant(id),
  mission_id     uuid NOT NULL REFERENCES mission(id),
  observed_at    timestamptz NOT NULL,
  temperature_c  numeric(4,1) NOT NULL CHECK (temperature_c BETWEEN -60 AND 60),
  condition      text NOT NULL
                 CHECK (condition IN ('CLEAR','CLOUD','RAIN','STORM','DUST','FOG','SNOW')),
  wind_kph       smallint NOT NULL CHECK (wind_kph BETWEEN 0 AND 400),
  gust_kph       smallint NOT NULL CHECK (gust_kph BETWEEN 0 AND 400),
  rain_mm        numeric(5,1) NOT NULL DEFAULT 0 CHECK (rain_mm BETWEEN 0 AND 1000),
  source         text NOT NULL DEFAULT 'xWeather (simulated)' CHECK (length(source) BETWEEN 1 AND 100),
  PRIMARY KEY (tenant_id, mission_id),
  CHECK (gust_kph >= wind_kph)
);
ALTER TABLE weather_current ENABLE ROW LEVEL SECURITY;
ALTER TABLE weather_current FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON weather_current
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
-- Written by the simulated feed as nexira_api (D-01); current values only, never deleted.
GRANT SELECT, INSERT, UPDATE ON weather_current TO nexira_app;

-- A row's mission is in its own tenant (foreign keys ignore RLS: plan-pilot-wx.md §7, the
-- lesson of Prompts 24 and 29), and a row never moves to another mission or tenant. The
-- trigger runs as the caller, so RLS on mission already hides other tenants' missions; the
-- tenant_id condition keeps the rule true for a role that bypasses RLS.
CREATE FUNCTION weather_current_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND (NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
                           OR NEW.mission_id IS DISTINCT FROM OLD.mission_id) THEN
    RAISE EXCEPTION 'weather: a row keeps its mission';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM mission WHERE id = NEW.mission_id AND tenant_id = NEW.tenant_id) THEN
    RAISE EXCEPTION 'weather: no such mission';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER weather_current_guard BEFORE INSERT OR UPDATE ON weather_current
  FOR EACH ROW EXECUTE FUNCTION weather_current_guard();
