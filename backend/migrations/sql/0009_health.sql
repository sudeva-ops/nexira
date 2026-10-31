-- Pilot module 9, Health Intelligence (D-39): PC-26..29, approved by the product owner on
-- 2026-10-31 (PR #70), with the plan's answers (docs/plan-pilot-hl.md, PR #71; G-1 adds
-- health_advisory.topic_code). Runs as nexira_owner (D-01). RLS and grants: named human
-- sign-off (D-29). Every row is simulated or illustrative (D-19); no person-level health
-- data anywhere (D-39).

-- PC-26 · outbreak and health advisories (HL-01, HL-02): a country-level list, not
-- incidents. The simulated feed (as nexira_api) inserts and updates them; never deleted.
CREATE TABLE health_advisory (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenant(id),
  reference     text NOT NULL CHECK (reference ~ '^HA-[0-9]{4,}$'),
  external_id   text NOT NULL CHECK (length(external_id) BETWEEN 1 AND 200),
  topic         text NOT NULL CHECK (length(topic) BETWEEN 1 AND 100),
  -- Picks the topic's message template, HEALTH_<topic_code> (plan G-1).
  topic_code    text NOT NULL CHECK (topic_code ~ '^[A-Z][A-Z0-9_]{1,39}$'),
  -- One-dimensional, no NULLs, so "= ANY" is never unknown (review of Prompt 44, M1).
  countries     char(2)[] NOT NULL CHECK (
                  cardinality(countries) BETWEEN 1 AND 60 AND array_ndims(countries) = 1
                  AND array_position(countries, NULL) IS NULL
                  AND array_to_string(countries, ',') ~ '^[A-Z]{2}(,[A-Z]{2})*$'),
  region_label  text NOT NULL CHECK (length(region_label) BETWEEN 1 AND 200),
  level         text NOT NULL CHECK (level IN ('LOW','MODERATE','HIGH','CRITICAL')),
  guidance      text NOT NULL CHECK (length(guidance) BETWEEN 1 AND 500),
  source        text NOT NULL CHECK (length(source) BETWEEN 1 AND 200),
  status        text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','CLOSED')),
  published_at  timestamptz NOT NULL,
  updated_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, reference),
  UNIQUE (tenant_id, external_id)
);
CREATE INDEX health_advisory_status_idx ON health_advisory (tenant_id, status);
ALTER TABLE health_advisory ENABLE ROW LEVEL SECURITY;
ALTER TABLE health_advisory FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON health_advisory
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
-- A newer bulletin moves only these (PC-26).
GRANT SELECT, INSERT ON health_advisory TO nexira_app;
GRANT UPDATE (level, guidance, status, updated_at) ON health_advisory TO nexira_app;

-- The advisory rules (plan-pilot-hl.md §2, §12): what it is about never changes; a closed
-- advisory is final; the database writes updated_at. The guard holds for every role,
-- including the owner. search_path pinned, pg_temp last (the lesson of Prompt 39).
CREATE FUNCTION health_advisory_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'health advisory: advisories are kept';
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF OLD.status = 'CLOSED' THEN
      RAISE EXCEPTION 'health advisory: a closed advisory is final';
    END IF;
    IF (NEW.id, NEW.tenant_id, NEW.reference, NEW.external_id, NEW.topic, NEW.topic_code,
        NEW.countries, NEW.region_label, NEW.source, NEW.published_at)
       IS DISTINCT FROM
       (OLD.id, OLD.tenant_id, OLD.reference, OLD.external_id, OLD.topic, OLD.topic_code,
        OLD.countries, OLD.region_label, OLD.source, OLD.published_at) THEN
      RAISE EXCEPTION 'health advisory: what it is about is fixed';
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
  END IF;
  -- INSERT: an advisory starts open; published no later than now.
  IF NEW.status <> 'OPEN' THEN
    RAISE EXCEPTION 'health advisory: an advisory starts open';
  END IF;
  IF NEW.published_at > now() + interval '10 minutes' THEN
    RAISE EXCEPTION 'health advisory: published in the future';
  END IF;
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER health_advisory_guard BEFORE INSERT OR UPDATE OR DELETE ON health_advisory
  FOR EACH ROW EXECUTE FUNCTION health_advisory_guard();

-- PC-27 · sample medical facilities near each mission (HL-04). Fictional names. The
-- "Avoid" flag is computed from ACTIVE incidents on every read, never stored.
CREATE TABLE medical_facility (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenant(id),
  mission_id    uuid NOT NULL REFERENCES mission(id),
  name          text NOT NULL CHECK (length(name) BETWEEN 1 AND 150),
  location      geography(Point,4326) NOT NULL,
  capabilities  text[] NOT NULL CHECK (
                  cardinality(capabilities) BETWEEN 1 AND 10 AND array_ndims(capabilities) = 1
                  AND array_position(capabilities, NULL) IS NULL
                  AND capabilities <@ ARRAY['EMERGENCY','TRAUMA','ICU','SURGERY','HELIPAD',
                                            'PHARMACY','OUTPATIENT','MATERNITY','PAEDIATRIC']),
  trauma_level  smallint CHECK (trauma_level BETWEEN 1 AND 3),
  open_24_7     boolean NOT NULL,
  vetted_by     uuid REFERENCES partner(id),
  source        text NOT NULL DEFAULT 'Sample facility (simulated)'
                CHECK (length(source) BETWEEN 1 AND 200),
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX medical_facility_mission_idx ON medical_facility (tenant_id, mission_id);
CREATE INDEX medical_facility_location_idx ON medical_facility USING gist (location);
ALTER TABLE medical_facility ENABLE ROW LEVEL SECURITY;
ALTER TABLE medical_facility FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON medical_facility
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT ON medical_facility TO nexira_app;

-- Foreign keys ignore RLS, so the mission's and partner's tenant are checked here (the
-- lesson of Prompts 24 and 29). INSERT only, as the grants.
CREATE FUNCTION medical_facility_guard() RETURNS trigger AS $$
BEGIN
  PERFORM 1 FROM mission m WHERE m.id = NEW.mission_id AND m.tenant_id = NEW.tenant_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'medical facility: no such mission';
  END IF;
  IF NEW.vetted_by IS NOT NULL THEN
    PERFORM 1 FROM partner p WHERE p.id = NEW.vetted_by AND p.tenant_id = NEW.tenant_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'medical facility: no such partner';
    END IF;
  END IF;
  NEW.created_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER medical_facility_guard BEFORE INSERT ON medical_facility
  FOR EACH ROW EXECUTE FUNCTION medical_facility_guard();

-- PC-28 · entry and vaccination requirements per country (HL-03). Illustrative (D-19).
CREATE TABLE country_health_requirement (
  tenant_id     uuid NOT NULL REFERENCES tenant(id),
  country_code  char(2) NOT NULL CHECK (country_code ~ '^[A-Z]{2}$'),
  mandatory     text NOT NULL CHECK (length(mandatory) BETWEEN 1 AND 300),
  recommended   text NOT NULL CHECK (length(recommended) BETWEEN 1 AND 300),
  source        text NOT NULL DEFAULT 'Illustrative entry requirements (simulated)'
                CHECK (length(source) BETWEEN 1 AND 200),
  created_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, country_code)
);
ALTER TABLE country_health_requirement ENABLE ROW LEVEL SECURITY;
ALTER TABLE country_health_requirement FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON country_health_requirement
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT ON country_health_requirement TO nexira_app;

-- PC-29 · staff health readiness per mission (HL-05). Counts only (D-39): nothing here
-- names or points to a person.
CREATE TABLE mission_health_readiness (
  tenant_id           uuid NOT NULL REFERENCES tenant(id),
  mission_id          uuid NOT NULL REFERENCES mission(id),
  staff               smallint NOT NULL CHECK (staff BETWEEN 0 AND 10000),
  blood_type_on_file  smallint NOT NULL CHECK (blood_type_on_file BETWEEN 0 AND staff),
  insurance_active    smallint NOT NULL CHECK (insurance_active BETWEEN 0 AND staff),
  trauma_kits         smallint NOT NULL CHECK (trauma_kits BETWEEN 0 AND 1000),
  -- {"CHOLERA": 9}: per topic code, how many staff were offered the vaccine.
  vaccines_offered    jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(vaccines_offered) = 'object'),
  as_of               date NOT NULL CHECK (as_of BETWEEN DATE '2000-01-01' AND DATE '2200-12-31'),
  source              text NOT NULL DEFAULT 'Illustrative readiness counts (simulated)'
                      CHECK (length(source) BETWEEN 1 AND 200),
  created_at          timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, mission_id)
);
ALTER TABLE mission_health_readiness ENABLE ROW LEVEL SECURITY;
ALTER TABLE mission_health_readiness FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON mission_health_readiness
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT ON mission_health_readiness TO nexira_app;

-- The mission's tenant (as above), and each vaccine count a whole number from 0 to staff,
-- keyed by a topic code (plan-pilot-hl.md §5, §12). INSERT only, as the grants.
CREATE FUNCTION mission_health_readiness_guard() RETURNS trigger AS $$
DECLARE
  k  text;
  v  jsonb;
BEGIN
  PERFORM 1 FROM mission m WHERE m.id = NEW.mission_id AND m.tenant_id = NEW.tenant_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'health readiness: no such mission';
  END IF;
  -- Triggers run before CHECKs, so the shape is checked here before it is read.
  IF jsonb_typeof(NEW.vaccines_offered) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'health readiness: vaccines offered is an object of counts';
  END IF;
  IF (SELECT count(*) FROM jsonb_object_keys(NEW.vaccines_offered)) > 20 THEN
    RAISE EXCEPTION 'health readiness: at most 20 vaccines';
  END IF;
  FOR k, v IN SELECT key, value FROM jsonb_each(NEW.vaccines_offered) LOOP
    IF k !~ '^[A-Z][A-Z0-9_]{1,39}$' THEN
      RAISE EXCEPTION 'health readiness: % is not a topic code', k;
    END IF;
    IF jsonb_typeof(v) <> 'number' OR v::text !~ '^[0-9]+$'
       OR v::text::numeric > NEW.staff THEN
      RAISE EXCEPTION 'health readiness: % must be a count from 0 to staff', k;
    END IF;
  END LOOP;
  NEW.created_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER mission_health_readiness_guard BEFORE INSERT ON mission_health_readiness
  FOR EACH ROW EXECUTE FUNCTION mission_health_readiness_guard();
