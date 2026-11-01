-- Pilot module 11, Fleet & Assets (D-41): PC-33..34, approved by the product owner on
-- 2026-11-01 (PR #84), with the plan's answers (docs/plan-pilot-flt.md, PR #85). Runs as
-- nexira_owner (D-01). RLS and grants: named human sign-off (D-29). The register is
-- illustrative and telematics are simulated (D-19). Blocked, in an impact zone and assigned to
-- an evacuation are worked out on every read and not stored (§58 Q3).

-- PC-33 · the asset register (FLT-01). Seeded through the service layer; only the position,
-- fuel and status change (FLT-04, FLT-05).
CREATE TABLE fleet_asset (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  mission_id      uuid NOT NULL REFERENCES mission(id),
  code            text NOT NULL CHECK (code ~ '^(VH-[0-9]{2,3}|[A-Z]{2,4}-[A-Z]{3})$'),
  kind            text NOT NULL CHECK (kind IN ('VEHICLE','EQUIPMENT')),
  type_label      text NOT NULL CHECK (length(type_label) BETWEEN 1 AND 100),
  armoured        boolean NOT NULL DEFAULT false,
  seats           smallint CHECK (seats BETWEEN 1 AND 60),
  driver_id       uuid REFERENCES person(id),
  location        geography(Point,4326) NOT NULL,
  location_label  text NOT NULL CHECK (length(location_label) BETWEEN 1 AND 150),
  fuel_pct        smallint NOT NULL CHECK (fuel_pct BETWEEN 0 AND 100),
  position_at     timestamptz NOT NULL DEFAULT now(),
  status          text NOT NULL DEFAULT 'AVAILABLE'
                  CHECK (status IN ('AVAILABLE','IN_USE','MAINTENANCE')),
  status_reason   text CHECK (length(status_reason) BETWEEN 1 AND 300),
  source          text NOT NULL DEFAULT 'Illustrative asset register (simulated)'
                  CHECK (length(source) BETWEEN 1 AND 200),
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, code),
  -- Vehicles have seats and may have a driver; equipment has neither and is never armoured.
  CHECK ((kind = 'VEHICLE') = (seats IS NOT NULL)),
  CHECK (kind = 'VEHICLE' OR (driver_id IS NULL AND NOT armoured)),
  CHECK ((kind = 'VEHICLE') = (code LIKE 'VH-%')),
  -- A reason only while in maintenance, so none goes stale (review of Prompt 72, L3).
  CHECK ((status = 'MAINTENANCE') = (status_reason IS NOT NULL)),
  CHECK (kind = 'VEHICLE' OR status <> 'IN_USE')
);
CREATE INDEX fleet_asset_mission_idx ON fleet_asset (tenant_id, mission_id);
CREATE INDEX fleet_asset_location_idx ON fleet_asset USING gist (location);
ALTER TABLE fleet_asset ENABLE ROW LEVEL SECURITY;
ALTER TABLE fleet_asset FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON fleet_asset
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT ON fleet_asset TO nexira_app;
GRANT UPDATE (location, location_label, fuel_pct, position_at, status, status_reason)
  ON fleet_asset TO nexira_app;

-- Foreign keys ignore RLS, so the mission's and the driver's tenant are checked here (the
-- lesson of Prompts 24 and 29). A DELETE is refused for every role, the owner included.
CREATE FUNCTION fleet_asset_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'fleet asset: assets are kept';
  END IF;
  IF TG_OP = 'INSERT' THEN
    PERFORM 1 FROM mission m WHERE m.id = NEW.mission_id AND m.tenant_id = NEW.tenant_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'fleet asset: no such mission';
    END IF;
    IF NEW.driver_id IS NOT NULL THEN
      PERFORM 1 FROM person p
       WHERE p.id = NEW.driver_id AND p.tenant_id = NEW.tenant_id AND p.mission_id = NEW.mission_id;
      IF NOT FOUND THEN
        RAISE EXCEPTION 'fleet asset: the driver is a person of this mission';
      END IF;
    END IF;
    IF NEW.position_at > clock_timestamp() THEN
      RAISE EXCEPTION 'fleet asset: a position is not in the future';
    END IF;
    NEW.created_at := now();
    NEW.updated_at := now();
    RETURN NEW;
  END IF;

  -- UPDATE: what the asset is stays fixed; where it is, its fuel and its status move.
  IF (NEW.id, NEW.tenant_id, NEW.mission_id, NEW.code, NEW.kind, NEW.type_label, NEW.armoured,
      NEW.seats, NEW.driver_id, NEW.source, NEW.created_at)
     IS DISTINCT FROM
     (OLD.id, OLD.tenant_id, OLD.mission_id, OLD.code, OLD.kind, OLD.type_label, OLD.armoured,
      OLD.seats, OLD.driver_id, OLD.source, OLD.created_at) THEN
    RAISE EXCEPTION 'fleet asset: what the asset is, its mission and its driver are fixed';
  END IF;
  -- The database writes the position time: the moment a new location is stored, so positions
  -- move forward in time whatever the caller's clock, also for two moves in one transaction
  -- (review of Prompt 72, M1). Without a new location the time stays.
  IF NEW.location IS DISTINCT FROM OLD.location THEN
    NEW.position_at := clock_timestamp();
  ELSE
    NEW.position_at := OLD.position_at;
  END IF;
  IF NEW.status = 'MAINTENANCE' AND NEW.status_reason IS NULL THEN
    RAISE EXCEPTION 'fleet asset: maintenance needs a reason';
  END IF;
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER fleet_asset_guard BEFORE INSERT OR UPDATE OR DELETE ON fleet_asset
  FOR EACH ROW EXECUTE FUNCTION fleet_asset_guard();

-- PC-34 · maintenance items (FLT-04): each is done once, by a person or the simulated
-- workshop, and kept.
CREATE TABLE fleet_maintenance (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenant(id),
  asset_id      uuid NOT NULL REFERENCES fleet_asset(id),
  task          text NOT NULL CHECK (length(task) BETWEEN 1 AND 200),
  due_on        date NOT NULL,
  done_at       timestamptz,
  done_by_type  text CHECK (done_by_type IN ('USER','WORKSHOP')),
  done_by       text CHECK (length(done_by) BETWEEN 1 AND 100),
  created_at    timestamptz NOT NULL DEFAULT now(),
  CHECK ((done_by_type IS NULL) = (done_by IS NULL)),
  CHECK ((done_by_type IS NULL) = (done_at IS NULL))
);
CREATE INDEX fleet_maintenance_asset_idx ON fleet_maintenance (tenant_id, asset_id);
ALTER TABLE fleet_maintenance ENABLE ROW LEVEL SECURITY;
ALTER TABLE fleet_maintenance FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON fleet_maintenance
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT ON fleet_maintenance TO nexira_app;
GRANT UPDATE (done_by_type, done_by) ON fleet_maintenance TO nexira_app;

CREATE FUNCTION fleet_maintenance_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'fleet maintenance: maintenance items are kept';
  END IF;
  IF TG_OP = 'INSERT' THEN
    PERFORM 1 FROM fleet_asset a WHERE a.id = NEW.asset_id AND a.tenant_id = NEW.tenant_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'fleet maintenance: no such asset';
    END IF;
    IF NEW.done_by_type IS NOT NULL OR NEW.done_by IS NOT NULL THEN
      RAISE EXCEPTION 'fleet maintenance: an item starts not done';
    END IF;
    NEW.done_at := NULL;
    NEW.created_at := now();
    RETURN NEW;
  END IF;

  -- UPDATE: only marking it done, once.
  IF (NEW.id, NEW.tenant_id, NEW.asset_id, NEW.task, NEW.due_on, NEW.created_at)
     IS DISTINCT FROM
     (OLD.id, OLD.tenant_id, OLD.asset_id, OLD.task, OLD.due_on, OLD.created_at) THEN
    RAISE EXCEPTION 'fleet maintenance: the task, its asset and due date are fixed';
  END IF;
  IF OLD.done_by_type IS NOT NULL THEN
    RAISE EXCEPTION 'fleet maintenance: done is final';
  END IF;
  IF NEW.done_by_type IS NULL OR NEW.done_by IS NULL THEN
    RAISE EXCEPTION 'fleet maintenance: the only change is marking it done, by someone';
  END IF;
  IF NEW.done_by_type = 'USER' THEN
    IF NEW.done_by !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
      RAISE EXCEPTION 'fleet maintenance: no such user';
    END IF;
    PERFORM 1 FROM app_user u WHERE u.id = NEW.done_by::uuid AND u.tenant_id = NEW.tenant_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'fleet maintenance: no such user';
    END IF;
  END IF;
  NEW.done_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER fleet_maintenance_guard BEFORE INSERT OR UPDATE OR DELETE ON fleet_maintenance
  FOR EACH ROW EXECUTE FUNCTION fleet_maintenance_guard();
