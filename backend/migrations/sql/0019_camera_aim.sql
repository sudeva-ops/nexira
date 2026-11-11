-- Site Twin camera coverage (D-51; docs/plan-pilot-rpl.md §4): four of the seeded cameras
-- re-aimed, so each sees along the wall it is mounted on. Data only: no column, constraint,
-- grant or RLS change. Runs as nexira_owner (D-01). The guard keeps a mount fixed, so it is
-- disabled for these statements, and FORCE RLS lifted, inside this transaction.
ALTER TABLE site_sensor NO FORCE ROW LEVEL SECURITY;
ALTER TABLE site_sensor DISABLE TRIGGER site_sensor_guard;
UPDATE site_sensor s
   SET heading_deg = m.heading, fov_deg = m.fov, range_u = m.range
  FROM (VALUES
    ('CAM-11', 130, 110, 190),
    ('CAM-12', 225, 110, 205),
    ('CAM-13', 130, 110, 210),
    ('CAM-16', 130, 110, 200)
  ) AS m (code, heading, fov, range)
 WHERE s.kind = 'CCTV' AND s.code = m.code;
ALTER TABLE site_sensor ENABLE TRIGGER site_sensor_guard;
ALTER TABLE site_sensor FORCE ROW LEVEL SECURITY;
