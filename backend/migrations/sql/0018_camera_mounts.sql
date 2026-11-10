-- Pilot module 21, Site Twin camera coverage (D-51): PC-53, approved by the product owner on
-- 2026-11-10 (PR #158), with the plan's mounts (docs/plan-pilot-rpl.md §4, PR #159). Runs as
-- nexira_owner (D-01). No grant or RLS change: nexira_app keeps SELECT, INSERT and
-- UPDATE (status, detail) on site_sensor, so a mount is written once, by the seed.

-- PC-53 · where each camera is mounted and points (TWN-08), in plan units. Heading 0 is up the
-- plan, clockwise; the field of view is centred on the heading; the range is in plan units.
ALTER TABLE site_sensor
  ADD COLUMN mount_x      integer CHECK (mount_x BETWEEN 0 AND 10000),
  ADD COLUMN mount_y      integer CHECK (mount_y BETWEEN 0 AND 10000),
  ADD COLUMN heading_deg  integer CHECK (heading_deg BETWEEN 0 AND 359),
  ADD COLUMN fov_deg      integer CHECK (fov_deg BETWEEN 10 AND 180),
  ADD COLUMN range_u      integer CHECK (range_u BETWEEN 1 AND 10000);

-- The cameras seeded before this migration (the Nairobi embassy's CAM-01..16) get the plan's
-- mounts. FORCE RLS hides every row from the owner without a tenant, so it is lifted for this
-- statement, inside this transaction (as in 0003). A camera not in this list fails the CHECK
-- below, and the migration with it.
ALTER TABLE site_sensor NO FORCE ROW LEVEL SECURITY;
UPDATE site_sensor s
   SET mount_x = m.x, mount_y = m.y, heading_deg = m.heading, fov_deg = m.fov, range_u = m.range
  FROM (VALUES
    ('CAM-01',  22, 322, 135,  90, 120),
    ('CAM-02', 113, 383, 315,  90, 120),
    ('CAM-03', 682, 342, 120,  80, 110),
    ('CAM-04', 768, 383, 290,  80, 110),
    ('CAM-05', 132, 267, 135,  90, 200),
    ('CAM-06', 298, 383, 315,  90, 200),
    ('CAM-07', 317, 267, 120,  90, 280),
    ('CAM-08', 573, 383, 300,  90, 280),
    ('CAM-09', 132,  32, 135,  90, 220),
    ('CAM-10', 132, 248,  70,  70, 280),
    ('CAM-11', 417, 157, 125, 100, 190),
    ('CAM-12', 768,  32, 235, 100, 200),
    ('CAM-13', 592, 147, 125, 100, 210),
    ('CAM-14', 592, 267, 105,  90, 190),
    ('CAM-15', 768, 323, 285,  90, 190),
    ('CAM-16', 417,  32, 125, 100, 200)
  ) AS m (code, x, y, heading, fov, range)
 WHERE s.kind = 'CCTV' AND s.code = m.code;
ALTER TABLE site_sensor FORCE ROW LEVEL SECURITY;

ALTER TABLE site_sensor ADD CONSTRAINT site_sensor_mount_check
  CHECK (CASE WHEN kind = 'CCTV'
              THEN num_nonnulls(mount_x, mount_y, heading_deg, fov_deg, range_u) = 5
              ELSE num_nonnulls(mount_x, mount_y, heading_deg, fov_deg, range_u) = 0 END);

-- The guard of 0013, with the mount kept fixed like the code and zone: only the status and
-- detail change.
CREATE OR REPLACE FUNCTION site_sensor_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'site sensor: sensors are kept';
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF (NEW.id, NEW.tenant_id, NEW.site_id, NEW.zone_id, NEW.code, NEW.kind, NEW.label,
        NEW.created_at, NEW.mount_x, NEW.mount_y, NEW.heading_deg, NEW.fov_deg, NEW.range_u)
       IS DISTINCT FROM
       (OLD.id, OLD.tenant_id, OLD.site_id, OLD.zone_id, OLD.code, OLD.kind, OLD.label,
        OLD.created_at, OLD.mount_x, OLD.mount_y, OLD.heading_deg, OLD.fov_deg, OLD.range_u) THEN
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
