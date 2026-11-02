-- Pilot module 13, Site Twin (D-43): PC-39..42, approved by the product owner on 2026-11-02
-- (PR #98), with the plan's answers (docs/plan-pilot-twn.md, PR #99; G-1: no site_readiness
-- table, the score is site.readiness_score). Runs as nexira_owner (D-01). RLS and grants: named
-- human sign-off (D-29). Plans, presence and sensors are illustrative and simulated (D-19).
-- Presence is shown on Site Twin only; it is never a location observation (D-43).

-- PC-39 · the floor plan (TWN-01): seeded, then read-only.
CREATE TABLE site_zone (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenant(id),
  site_id     uuid NOT NULL REFERENCES site(id),
  code        text NOT NULL CHECK (code ~ '^[a-z0-9_]{1,20}$'),
  name        text NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
  kind        text NOT NULL CHECK (kind IN ('OFFICE','SUITE','CONFERENCE','COMMS','SAFE_ROOM',
                                            'LOBBY','CONSULAR','MUSTER','GATE')),
  x           integer NOT NULL CHECK (x BETWEEN 0 AND 10000),
  y           integer NOT NULL CHECK (y BETWEEN 0 AND 10000),
  w           integer NOT NULL CHECK (w BETWEEN 1 AND 10000),
  h           integer NOT NULL CHECK (h BETWEEN 1 AND 10000),
  -- Only where people gather in a crisis.
  capacity    integer CHECK (capacity BETWEEN 1 AND 10000),
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (site_id, code),
  -- For site_route's and site_presence's same-site foreign keys.
  UNIQUE (id, site_id),
  CHECK (capacity IS NULL OR kind IN ('SAFE_ROOM','MUSTER'))
);
CREATE INDEX site_zone_site_idx ON site_zone (tenant_id, site_id);
ALTER TABLE site_zone ENABLE ROW LEVEL SECURITY;
ALTER TABLE site_zone FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON site_zone
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT ON site_zone TO nexira_app;

-- Foreign keys ignore RLS, so every reference's tenant is checked here (the lesson of Prompts 24
-- and 29). BEFORE triggers run before CHECK constraints. Seeded tables refuse UPDATE and DELETE
-- for every role.
CREATE FUNCTION site_zone_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION 'site zone: the floor plan is fixed';
  END IF;
  PERFORM 1 FROM site s WHERE s.id = NEW.site_id AND s.tenant_id = NEW.tenant_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'site zone: no such site';
  END IF;
  NEW.created_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER site_zone_guard BEFORE INSERT OR UPDATE OR DELETE ON site_zone
  FOR EACH ROW EXECUTE FUNCTION site_zone_guard();

-- PC-40 · the evacuation routes drawn on the plan (TWN-04).
CREATE TABLE site_route (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenant(id),
  site_id       uuid NOT NULL REFERENCES site(id),
  code          text NOT NULL CHECK (code ~ '^[A-Z]{1,3}$'),
  label         text NOT NULL CHECK (length(label) BETWEEN 1 AND 100),
  kind          text NOT NULL DEFAULT 'EVACUATION' CHECK (kind IN ('EVACUATION')),
  path          jsonb NOT NULL CHECK (jsonb_typeof(path) = 'array'
                                      AND jsonb_array_length(path) BETWEEN 2 AND 20),
  exit_zone_id  uuid NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (site_id, code),
  FOREIGN KEY (exit_zone_id, site_id) REFERENCES site_zone (id, site_id)
);
ALTER TABLE site_route ENABLE ROW LEVEL SECURITY;
ALTER TABLE site_route FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON site_route
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT ON site_route TO nexira_app;

CREATE FUNCTION site_route_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION 'site route: the routes are fixed';
  END IF;
  PERFORM 1 FROM site s WHERE s.id = NEW.site_id AND s.tenant_id = NEW.tenant_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'site route: no such site';
  END IF;
  -- Leaves by a gate of the same site.
  PERFORM 1 FROM site_zone z WHERE z.id = NEW.exit_zone_id AND z.site_id = NEW.site_id
     AND z.tenant_id = NEW.tenant_id AND z.kind = 'GATE';
  IF NOT FOUND THEN
    RAISE EXCEPTION 'site route: the exit is a gate of this site';
  END IF;
  -- Each point is [x, y] with integers on the plan.
  IF jsonb_typeof(NEW.path) <> 'array' OR EXISTS (
       SELECT 1 FROM jsonb_array_elements(NEW.path) p
        WHERE jsonb_typeof(p) <> 'array' OR jsonb_array_length(p) <> 2
           OR jsonb_typeof(p -> 0) <> 'number' OR jsonb_typeof(p -> 1) <> 'number'
           OR (p ->> 0) !~ '^[0-9]{1,5}$' OR (p ->> 1) !~ '^[0-9]{1,5}$') THEN
    RAISE EXCEPTION 'site route: the path is [x, y] points';
  END IF;
  NEW.created_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER site_route_guard BEFORE INSERT OR UPDATE OR DELETE ON site_route
  FOR EACH ROW EXECUTE FUNCTION site_route_guard();

-- PC-41 · who is in which zone now (TWN-02): moved by the simulated feed, removed on departure.
-- Staff are people of the site's mission; guards and visitors are labels, never names.
CREATE TABLE site_presence (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenant(id),
  site_id     uuid NOT NULL REFERENCES site(id),
  zone_id     uuid NOT NULL,
  kind        text NOT NULL CHECK (kind IN ('STAFF','GUARD','VISITOR')),
  person_id   uuid REFERENCES person(id),
  label       text CHECK (label ~ '^(Guard|Visitor) [0-9]{1,3}$'),
  since       timestamptz NOT NULL DEFAULT now(),
  source      text NOT NULL DEFAULT 'Access control + Wi-Fi presence (simulated)'
              CHECK (length(source) BETWEEN 1 AND 100),
  UNIQUE (site_id, person_id),
  UNIQUE (site_id, label),
  FOREIGN KEY (zone_id, site_id) REFERENCES site_zone (id, site_id),
  CHECK ((kind = 'STAFF') = (person_id IS NOT NULL)),
  CHECK ((kind = 'STAFF') = (label IS NULL)),
  CHECK (kind = 'STAFF' OR label LIKE initcap(lower(kind)) || ' %')
);
CREATE INDEX site_presence_site_idx ON site_presence (tenant_id, site_id);
ALTER TABLE site_presence ENABLE ROW LEVEL SECURITY;
ALTER TABLE site_presence FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON site_presence
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT, DELETE ON site_presence TO nexira_app;
GRANT UPDATE (zone_id) ON site_presence TO nexira_app;

CREATE FUNCTION site_presence_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;  -- a departure
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF (NEW.id, NEW.tenant_id, NEW.site_id, NEW.kind, NEW.person_id, NEW.label, NEW.source)
       IS DISTINCT FROM
       (OLD.id, OLD.tenant_id, OLD.site_id, OLD.kind, OLD.person_id, OLD.label, OLD.source) THEN
      RAISE EXCEPTION 'site presence: only the zone changes';
    END IF;
  ELSE
    PERFORM 1 FROM site s WHERE s.id = NEW.site_id AND s.tenant_id = NEW.tenant_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'site presence: no such site';
    END IF;
    IF NEW.person_id IS NOT NULL THEN
      PERFORM 1 FROM person p JOIN site s ON s.id = NEW.site_id
       WHERE p.id = NEW.person_id AND p.tenant_id = NEW.tenant_id
         AND p.mission_id = s.mission_id;
      IF NOT FOUND THEN
        RAISE EXCEPTION 'site presence: staff are people of the site''s mission';
      END IF;
    END IF;
  END IF;
  PERFORM 1 FROM site_zone z
   WHERE z.id = NEW.zone_id AND z.site_id = NEW.site_id AND z.tenant_id = NEW.tenant_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'site presence: a zone of this site';
  END IF;
  IF TG_OP = 'INSERT' OR NEW.zone_id IS DISTINCT FROM OLD.zone_id THEN
    NEW.since := now();
  ELSE
    NEW.since := OLD.since;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER site_presence_guard BEFORE INSERT OR UPDATE OR DELETE ON site_presence
  FOR EACH ROW EXECUTE FUNCTION site_presence_guard();

-- PC-42 · sensors and systems (TWN-03): status changed only by the simulated building systems.
CREATE TABLE site_sensor (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenant(id),
  site_id     uuid NOT NULL REFERENCES site(id),
  zone_id     uuid,
  code        text NOT NULL CHECK (code ~ '^[A-Z0-9-]{1,20}$'),
  kind        text NOT NULL CHECK (kind IN ('GATE','BADGE_READER','CCTV','SAFE_ROOM','ACCESS','ALARM')),
  label       text NOT NULL CHECK (length(label) BETWEEN 1 AND 100),
  status      text NOT NULL DEFAULT 'OK' CHECK (status IN ('OK','DEGRADED','FAULT','OFFLINE')),
  detail      text CHECK (length(detail) BETWEEN 1 AND 100),
  status_at   timestamptz NOT NULL DEFAULT now(),
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (site_id, code),
  FOREIGN KEY (zone_id, site_id) REFERENCES site_zone (id, site_id)
);
CREATE INDEX site_sensor_site_idx ON site_sensor (tenant_id, site_id);
ALTER TABLE site_sensor ENABLE ROW LEVEL SECURITY;
ALTER TABLE site_sensor FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON site_sensor
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT ON site_sensor TO nexira_app;
GRANT UPDATE (status, detail) ON site_sensor TO nexira_app;

CREATE FUNCTION site_sensor_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'site sensor: sensors are kept';
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF (NEW.id, NEW.tenant_id, NEW.site_id, NEW.zone_id, NEW.code, NEW.kind, NEW.label,
        NEW.created_at)
       IS DISTINCT FROM
       (OLD.id, OLD.tenant_id, OLD.site_id, OLD.zone_id, OLD.code, OLD.kind, OLD.label,
        OLD.created_at) THEN
      RAISE EXCEPTION 'site sensor: only the status and detail change';
    END IF;
    IF (NEW.status, NEW.detail) IS DISTINCT FROM (OLD.status, OLD.detail) THEN
      NEW.status_at := now();
    ELSE
      NEW.status_at := OLD.status_at;
    END IF;
    RETURN NEW;
  END IF;
  PERFORM 1 FROM site s WHERE s.id = NEW.site_id AND s.tenant_id = NEW.tenant_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'site sensor: no such site';
  END IF;
  IF NEW.zone_id IS NOT NULL THEN
    PERFORM 1 FROM site_zone z
     WHERE z.id = NEW.zone_id AND z.site_id = NEW.site_id AND z.tenant_id = NEW.tenant_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'site sensor: a zone of this site';
    END IF;
  END IF;
  NEW.status_at := now();
  NEW.created_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER site_sensor_guard BEFORE INSERT OR UPDATE OR DELETE ON site_sensor
  FOR EACH ROW EXECUTE FUNCTION site_sensor_guard();

-- PC-42 · emergency readiness items (TWN-05): each done once, by a person of the tenant. The
-- score and last drill are site.readiness_score and site.last_drill_on (plan G-1).
CREATE TABLE site_readiness_item (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenant(id),
  site_id     uuid NOT NULL REFERENCES site(id),
  label       text NOT NULL CHECK (length(label) BETWEEN 1 AND 200),
  done_by     uuid REFERENCES app_user(id),
  done_at     timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (site_id, label),
  CHECK ((done_by IS NULL) = (done_at IS NULL))
);
ALTER TABLE site_readiness_item ENABLE ROW LEVEL SECURITY;
ALTER TABLE site_readiness_item FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON site_readiness_item
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT ON site_readiness_item TO nexira_app;
GRANT UPDATE (done_by) ON site_readiness_item TO nexira_app;

CREATE FUNCTION site_readiness_item_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'site readiness: items are kept';
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF (NEW.id, NEW.tenant_id, NEW.site_id, NEW.label, NEW.created_at)
       IS DISTINCT FROM (OLD.id, OLD.tenant_id, OLD.site_id, OLD.label, OLD.created_at) THEN
      RAISE EXCEPTION 'site readiness: the item stays fixed';
    END IF;
    IF OLD.done_by IS NOT NULL THEN
      RAISE EXCEPTION 'site readiness: done is final';
    END IF;
    IF NEW.done_by IS NULL THEN
      RAISE EXCEPTION 'site readiness: the only change is marking it done, by someone';
    END IF;
  ELSE
    PERFORM 1 FROM site s WHERE s.id = NEW.site_id AND s.tenant_id = NEW.tenant_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'site readiness: no such site';
    END IF;
    NEW.created_at := now();
  END IF;
  -- An item may be seeded already done (plan-pilot-twn G-7); either way by a user of the tenant.
  IF NEW.done_by IS NOT NULL THEN
    PERFORM 1 FROM app_user u WHERE u.id = NEW.done_by AND u.tenant_id = NEW.tenant_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'site readiness: done by someone of this tenant';
    END IF;
    NEW.done_at := now();
  ELSE
    NEW.done_at := NULL;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER site_readiness_item_guard BEFORE INSERT OR UPDATE OR DELETE ON site_readiness_item
  FOR EACH ROW EXECUTE FUNCTION site_readiness_item_guard();
