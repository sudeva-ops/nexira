-- Pilot module 14, Supply Chain & Third-Party Risk (D-44): PC-43..45, approved by the product
-- owner on 2026-11-02 (PR #112), with the plan's answers (docs/plan-pilot-sup.md, PR #113). Runs
-- as nexira_owner (D-01). RLS and grants: named human sign-off (D-29). The register and routes
-- are illustrative and their statuses simulated (D-19). ROUTE BLOCKED, ALTERNATE and "impacted"
-- are worked out on every read and not stored (§73 Q2). NEXIRA contacts no supplier.

-- PC-43 · the supplier register (SUP-01): seeded; only the reported status changes (SUP-02).
CREATE TABLE supplier (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id            uuid NOT NULL REFERENCES tenant(id),
  code                 text NOT NULL CHECK (code ~ '^SUP-[0-9]{3}$'),
  name                 text NOT NULL CHECK (length(name) BETWEEN 1 AND 150),
  service              text NOT NULL CHECK (length(service) BETWEEN 1 AND 150),
  -- NULL: a Global supplier, never impacted by a mission's incident.
  mission_id           uuid REFERENCES mission(id),
  tier                 smallint NOT NULL CHECK (tier BETWEEN 1 AND 3),
  backup_supplier_id   uuid REFERENCES supplier(id),
  -- Illustrative until Continuity & Compliance (§70 SUP-01).
  in_bcp               boolean NOT NULL DEFAULT false,
  vetting_valid_until  date NOT NULL,
  performance_score    smallint CHECK (performance_score BETWEEN 0 AND 100),
  status               text NOT NULL DEFAULT 'NORMAL'
                       CHECK (status IN ('NORMAL','WATCH','DELAYED','AT_RISK')),
  status_detail        text CHECK (length(status_detail) BETWEEN 1 AND 300),
  status_at            timestamptz NOT NULL DEFAULT now(),
  source               text NOT NULL DEFAULT 'Illustrative supplier register (simulated)'
                       CHECK (length(source) BETWEEN 1 AND 200),
  created_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, code),
  CHECK (backup_supplier_id IS DISTINCT FROM id)
);
CREATE INDEX supplier_mission_idx ON supplier (tenant_id, mission_id);
ALTER TABLE supplier ENABLE ROW LEVEL SECURITY;
ALTER TABLE supplier FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON supplier
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT ON supplier TO nexira_app;
GRANT UPDATE (status, status_detail) ON supplier TO nexira_app;

-- Foreign keys ignore RLS, so every reference's tenant is checked here (the lesson of Prompts 24
-- and 29). BEFORE triggers run before CHECK constraints. A DELETE is refused for every role.
CREATE FUNCTION supply_supplier_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'supplier: suppliers are kept';
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF (NEW.id, NEW.tenant_id, NEW.code, NEW.name, NEW.service, NEW.mission_id, NEW.tier,
        NEW.backup_supplier_id, NEW.in_bcp, NEW.vetting_valid_until, NEW.performance_score,
        NEW.source, NEW.created_at)
       IS DISTINCT FROM
       (OLD.id, OLD.tenant_id, OLD.code, OLD.name, OLD.service, OLD.mission_id, OLD.tier,
        OLD.backup_supplier_id, OLD.in_bcp, OLD.vetting_valid_until, OLD.performance_score,
        OLD.source, OLD.created_at) THEN
      RAISE EXCEPTION 'supplier: only the reported status changes';
    END IF;
    IF (NEW.status, NEW.status_detail) IS DISTINCT FROM (OLD.status, OLD.status_detail) THEN
      NEW.status_at := now();
    ELSE
      NEW.status_at := OLD.status_at;
    END IF;
    RETURN NEW;
  END IF;
  IF NEW.mission_id IS NOT NULL THEN
    PERFORM 1 FROM mission m WHERE m.id = NEW.mission_id AND m.tenant_id = NEW.tenant_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'supplier: no such mission';
    END IF;
  END IF;
  -- A backup serves the same mission, or is Global (plan-pilot-sup G-2).
  IF NEW.backup_supplier_id IS NOT NULL THEN
    PERFORM 1 FROM supplier b
     WHERE b.id = NEW.backup_supplier_id AND b.tenant_id = NEW.tenant_id
       AND (b.mission_id IS NULL OR b.mission_id = NEW.mission_id);
    IF NOT FOUND THEN
      RAISE EXCEPTION 'supplier: the backup is a supplier of this tenant, for the same mission or Global';
    END IF;
  END IF;
  NEW.status_at := now();
  NEW.created_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER supply_supplier_guard BEFORE INSERT OR UPDATE OR DELETE ON supplier
  FOR EACH ROW EXECUTE FUNCTION supply_supplier_guard();

-- PC-44 · logistics routes (SUP-02, SUP-03): a path on the map, not a location, so a line
-- (§73 Q5). Seeded; only the reported status changes.
CREATE TABLE logistics_route (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenant(id),
  mission_id       uuid NOT NULL REFERENCES mission(id),
  code             text NOT NULL CHECK (code ~ '^R-[A-Z]{3}-[0-9]{1,2}$'),
  label            text NOT NULL CHECK (length(label) BETWEEN 1 AND 150),
  kind             text NOT NULL CHECK (kind IN ('POUCH','FUEL','STAFF_TRANSPORT','FREIGHT')),
  supplier_id      uuid REFERENCES supplier(id),
  alternate_of_id  uuid REFERENCES logistics_route(id),
  path             geography(LineString,4326) NOT NULL
                   CHECK (ST_NPoints(path::geometry) BETWEEN 2 AND 50),
  status           text NOT NULL DEFAULT 'OPEN'
                   CHECK (status IN ('OPEN','RESTRICTED','DELAYED','BLOCKED')),
  detail           text CHECK (length(detail) BETWEEN 1 AND 300),
  status_at        timestamptz NOT NULL DEFAULT now(),
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, code),
  CHECK (alternate_of_id IS DISTINCT FROM id)
);
CREATE INDEX logistics_route_mission_idx ON logistics_route (tenant_id, mission_id);
CREATE INDEX logistics_route_path_idx ON logistics_route USING gist (path);
ALTER TABLE logistics_route ENABLE ROW LEVEL SECURITY;
ALTER TABLE logistics_route FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON logistics_route
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT ON logistics_route TO nexira_app;
GRANT UPDATE (status, detail) ON logistics_route TO nexira_app;

CREATE FUNCTION supply_route_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'logistics route: routes are kept';
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF (NEW.id, NEW.tenant_id, NEW.mission_id, NEW.code, NEW.label, NEW.kind, NEW.supplier_id,
        NEW.alternate_of_id, NEW.created_at)
       IS DISTINCT FROM
       (OLD.id, OLD.tenant_id, OLD.mission_id, OLD.code, OLD.label, OLD.kind, OLD.supplier_id,
        OLD.alternate_of_id, OLD.created_at)
       -- geography has no equality operator for IS DISTINCT FROM; compare the binary form.
       OR ST_AsEWKB(NEW.path::geometry) <> ST_AsEWKB(OLD.path::geometry) THEN
      RAISE EXCEPTION 'logistics route: only the reported status changes';
    END IF;
    IF (NEW.status, NEW.detail) IS DISTINCT FROM (OLD.status, OLD.detail) THEN
      NEW.status_at := now();
    ELSE
      NEW.status_at := OLD.status_at;
    END IF;
    RETURN NEW;
  END IF;
  PERFORM 1 FROM mission m WHERE m.id = NEW.mission_id AND m.tenant_id = NEW.tenant_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'logistics route: no such mission';
  END IF;
  -- Run by a supplier of the route's mission, or a Global one.
  IF NEW.supplier_id IS NOT NULL THEN
    PERFORM 1 FROM supplier s
     WHERE s.id = NEW.supplier_id AND s.tenant_id = NEW.tenant_id
       AND (s.mission_id IS NULL OR s.mission_id = NEW.mission_id);
    IF NOT FOUND THEN
      RAISE EXCEPTION 'logistics route: run by a supplier of this mission or a Global one';
    END IF;
  END IF;
  IF NEW.alternate_of_id IS NOT NULL THEN
    PERFORM 1 FROM logistics_route r
     WHERE r.id = NEW.alternate_of_id AND r.tenant_id = NEW.tenant_id
       AND r.mission_id = NEW.mission_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'logistics route: an alternate for a route of the same mission';
    END IF;
  END IF;
  NEW.status_at := now();
  NEW.created_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER supply_route_guard BEFORE INSERT OR UPDATE OR DELETE ON logistics_route
  FOR EACH ROW EXECUTE FUNCTION supply_route_guard();

-- PC-45 · mitigations (SUP-04): recorded by a person, stood down once, kept. Nothing is sent.
CREATE TABLE supply_mitigation (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id           uuid NOT NULL REFERENCES tenant(id),
  supplier_id         uuid NOT NULL REFERENCES supplier(id),
  incident_id         uuid REFERENCES incident(id),
  backup_supplier_id  uuid REFERENCES supplier(id),
  route_id            uuid REFERENCES logistics_route(id),
  note                text CHECK (length(note) BETWEEN 1 AND 500),
  activated_by        uuid NOT NULL REFERENCES app_user(id),
  activated_at        timestamptz NOT NULL DEFAULT now(),
  stood_down_by       uuid REFERENCES app_user(id),
  stood_down_at       timestamptz,
  CHECK ((stood_down_by IS NULL) = (stood_down_at IS NULL))
);
-- One active mitigation per supplier (PC-45).
CREATE UNIQUE INDEX supply_mitigation_active_uq ON supply_mitigation (supplier_id)
  WHERE stood_down_at IS NULL;
CREATE INDEX supply_mitigation_incident_idx ON supply_mitigation (tenant_id, incident_id);
ALTER TABLE supply_mitigation ENABLE ROW LEVEL SECURITY;
ALTER TABLE supply_mitigation FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON supply_mitigation
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT ON supply_mitigation TO nexira_app;
GRANT UPDATE (stood_down_by) ON supply_mitigation TO nexira_app;

CREATE FUNCTION supply_mitigation_guard() RETURNS trigger AS $$
DECLARE
  s supplier%ROWTYPE;
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'supply mitigation: mitigations are kept';
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF (NEW.id, NEW.tenant_id, NEW.supplier_id, NEW.incident_id, NEW.backup_supplier_id,
        NEW.route_id, NEW.note, NEW.activated_by, NEW.activated_at)
       IS DISTINCT FROM
       (OLD.id, OLD.tenant_id, OLD.supplier_id, OLD.incident_id, OLD.backup_supplier_id,
        OLD.route_id, OLD.note, OLD.activated_by, OLD.activated_at) THEN
      RAISE EXCEPTION 'supply mitigation: the only change is standing it down';
    END IF;
    IF OLD.stood_down_by IS NOT NULL THEN
      RAISE EXCEPTION 'supply mitigation: stood down is final';
    END IF;
    IF NEW.stood_down_by IS NULL THEN
      RAISE EXCEPTION 'supply mitigation: the only change is standing it down, by someone';
    END IF;
    PERFORM 1 FROM app_user u WHERE u.id = NEW.stood_down_by AND u.tenant_id = NEW.tenant_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'supply mitigation: stood down by someone of this tenant';
    END IF;
    NEW.stood_down_at := now();
    RETURN NEW;
  END IF;

  SELECT * INTO s FROM supplier WHERE id = NEW.supplier_id AND tenant_id = NEW.tenant_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'supply mitigation: no such supplier';
  END IF;
  PERFORM 1 FROM app_user u WHERE u.id = NEW.activated_by AND u.tenant_id = NEW.tenant_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'supply mitigation: activated by someone of this tenant';
  END IF;
  IF NEW.stood_down_by IS NOT NULL THEN
    RAISE EXCEPTION 'supply mitigation: a mitigation starts active';
  END IF;
  -- An incident at the supplier's mission (SUP-03).
  IF NEW.incident_id IS NOT NULL THEN
    PERFORM 1 FROM incident i
     WHERE i.id = NEW.incident_id AND i.tenant_id = NEW.tenant_id
       AND i.mission_id = s.mission_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'supply mitigation: an incident at the supplier''s mission';
    END IF;
  END IF;
  -- The supplier's own backup.
  IF NEW.backup_supplier_id IS NOT NULL
     AND NEW.backup_supplier_id IS DISTINCT FROM s.backup_supplier_id THEN
    RAISE EXCEPTION 'supply mitigation: the backup is the supplier''s own backup';
  END IF;
  -- An alternate for one of the supplier's routes.
  IF NEW.route_id IS NOT NULL THEN
    PERFORM 1 FROM logistics_route a JOIN logistics_route p ON p.id = a.alternate_of_id
     WHERE a.id = NEW.route_id AND a.tenant_id = NEW.tenant_id
       AND p.tenant_id = NEW.tenant_id AND p.supplier_id = NEW.supplier_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'supply mitigation: the route is an alternate for one of the supplier''s routes';
    END IF;
  END IF;
  NEW.activated_at := now();
  NEW.stood_down_at := NULL;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER supply_mitigation_guard BEFORE INSERT OR UPDATE OR DELETE ON supply_mitigation
  FOR EACH ROW EXECUTE FUNCTION supply_mitigation_guard();
