-- Pilot module 22, map annotations (D-52): PC-54, approved by the product owner on 2026-11-11
-- (PR #167), with the plan's answers (docs/plan-pilot-map.md, PR #168). Runs as nexira_owner
-- (D-01). RLS and grants: named human sign-off (D-29).

-- PC-54 · marks, lines and areas people draw on the world map (ANN-01..ANN-06). Added ACTIVE;
-- the label, note, shape and end time change; withdrawn once with a reason; never deleted.
-- The author is kept here and in the audit log; the API shows only their role (ANN-04).
CREATE TABLE map_annotation (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenant(id),
  mission_id    uuid REFERENCES mission(id),   -- plan G-2: the Head of Mission's scope
  incident_id   uuid REFERENCES incident(id),
  kind          text NOT NULL CHECK (kind IN ('MARK','LINE','AREA')),
  symbol        text CHECK (symbol IN ('CHECKPOINT','CLOSED_ROAD','RALLY_POINT','HAZARD','NOTE')),
  shape         geography(Geometry,4326) NOT NULL,
  label         text NOT NULL CHECK (length(label) BETWEEN 1 AND 80),
  note          text CHECK (length(note) BETWEEN 1 AND 280),
  ends_at       timestamptz,
  status        text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','WITHDRAWN')),
  reason        text CHECK (length(reason) BETWEEN 1 AND 280),
  created_by    uuid NOT NULL REFERENCES app_user(id),
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_by    uuid REFERENCES app_user(id),
  updated_at    timestamptz,
  withdrawn_by  uuid REFERENCES app_user(id),
  withdrawn_at  timestamptz,
  -- A mark has a symbol; a line and an area do not.
  CHECK ((kind = 'MARK') = (symbol IS NOT NULL)),
  -- The shape is the kind's: a point, a line or a polygon, and not a huge one.
  CHECK (GeometryType(shape::geometry) = CASE kind WHEN 'MARK' THEN 'POINT'
                                                   WHEN 'LINE' THEN 'LINESTRING'
                                                   ELSE 'POLYGON' END),
  CHECK (ST_NPoints(shape::geometry) <= 500),
  CHECK ((status = 'WITHDRAWN') = (reason IS NOT NULL)),
  CHECK ((status = 'WITHDRAWN') = (withdrawn_by IS NOT NULL))
);
CREATE INDEX map_annotation_shape_idx ON map_annotation USING gist (shape);
CREATE INDEX map_annotation_incident_idx ON map_annotation (incident_id) WHERE incident_id IS NOT NULL;
ALTER TABLE map_annotation ENABLE ROW LEVEL SECURITY;
ALTER TABLE map_annotation FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON map_annotation
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT ON map_annotation TO nexira_app;
GRANT UPDATE (shape, label, note, ends_at, status, reason, updated_by, withdrawn_by)
  ON map_annotation TO nexira_app;

-- Foreign keys ignore RLS, so every reference's tenant is checked here (the lesson of Prompts 24
-- and 29). A linked incident's mission is the annotation's (plan G-2). The database writes the
-- times. A DELETE is refused for every role.
CREATE FUNCTION map_annotation_guard() RETURNS trigger AS $$
DECLARE
  incident_mission uuid;
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'map annotation: annotations are kept';
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF (NEW.id, NEW.tenant_id, NEW.mission_id, NEW.incident_id, NEW.kind, NEW.symbol,
        NEW.created_by, NEW.created_at)
       IS DISTINCT FROM
       (OLD.id, OLD.tenant_id, OLD.mission_id, OLD.incident_id, OLD.kind, OLD.symbol,
        OLD.created_by, OLD.created_at) THEN
      RAISE EXCEPTION 'map annotation: its kind, author, incident and mission are fixed';
    END IF;
    IF OLD.status <> 'ACTIVE' THEN
      RAISE EXCEPTION 'map annotation: a withdrawn annotation is kept as it is';
    END IF;
    IF NEW.status = 'WITHDRAWN' THEN
      -- Withdrawing changes nothing else.
      IF (NEW.shape::geometry, NEW.label, NEW.note, NEW.ends_at, NEW.updated_by)
         IS DISTINCT FROM
         (OLD.shape::geometry, OLD.label, OLD.note, OLD.ends_at, OLD.updated_by) THEN
        RAISE EXCEPTION 'map annotation: withdrawing changes nothing else';
      END IF;
      PERFORM 1 FROM app_user u WHERE u.id = NEW.withdrawn_by AND u.tenant_id = NEW.tenant_id;
      IF NOT FOUND THEN
        RAISE EXCEPTION 'map annotation: no such user';
      END IF;
      NEW.updated_at := OLD.updated_at;
      NEW.withdrawn_at := now();
      RETURN NEW;
    END IF;
    PERFORM 1 FROM app_user u WHERE u.id = NEW.updated_by AND u.tenant_id = NEW.tenant_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'map annotation: an edit names its user';
    END IF;
    IF NEW.ends_at IS NOT NULL AND NEW.ends_at <= OLD.created_at THEN
      RAISE EXCEPTION 'map annotation: it ends after it was added';
    END IF;
    NEW.updated_at := now();
    NEW.withdrawn_at := NULL;
    RETURN NEW;
  END IF;
  PERFORM 1 FROM app_user u WHERE u.id = NEW.created_by AND u.tenant_id = NEW.tenant_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'map annotation: no such user';
  END IF;
  IF NEW.mission_id IS NOT NULL THEN
    PERFORM 1 FROM mission m WHERE m.id = NEW.mission_id AND m.tenant_id = NEW.tenant_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'map annotation: no such mission';
    END IF;
  END IF;
  IF NEW.incident_id IS NOT NULL THEN
    SELECT i.mission_id INTO incident_mission
      FROM incident i WHERE i.id = NEW.incident_id AND i.tenant_id = NEW.tenant_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'map annotation: no such incident';
    END IF;
    IF incident_mission IS NOT NULL AND NEW.mission_id IS DISTINCT FROM incident_mission THEN
      RAISE EXCEPTION 'map annotation: an incident''s annotation is its mission''s';
    END IF;
  END IF;
  IF NEW.status <> 'ACTIVE' OR NEW.updated_by IS NOT NULL THEN
    RAISE EXCEPTION 'map annotation: an annotation is added active';
  END IF;
  NEW.created_at := now();
  NEW.updated_at := NULL;
  NEW.withdrawn_at := NULL;
  IF NEW.ends_at IS NOT NULL AND NEW.ends_at <= NEW.created_at THEN
    RAISE EXCEPTION 'map annotation: it ends after it was added';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER map_annotation_guard BEFORE INSERT OR UPDATE OR DELETE ON map_annotation
  FOR EACH ROW EXECUTE FUNCTION map_annotation_guard();

-- Row triggers do not fire on TRUNCATE, which the owner holds; refused too, as audit_log's.
CREATE FUNCTION map_annotation_no_truncate_guard() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'map annotation: annotations are kept';
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER map_annotation_no_truncate BEFORE TRUNCATE ON map_annotation
  FOR EACH STATEMENT EXECUTE FUNCTION map_annotation_no_truncate_guard();
