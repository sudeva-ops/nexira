-- Run as nexira_api. Prints PASS/FAIL lines. Each check is independent.
\set QUIET on
\pset tuples_only on
\pset format unaligned

CREATE TEMP TABLE r (n serial, name text, ok boolean, info text);

CREATE FUNCTION pg_temp.expect_error(name text, stmt text) RETURNS void AS $$
BEGIN
  BEGIN
    EXECUTE stmt;
    INSERT INTO r(name, ok, info) VALUES (name, false, 'no error raised');
  EXCEPTION WHEN OTHERS THEN
    INSERT INTO r(name, ok, info) VALUES (name, true, SQLERRM);
  END;
END $$ LANGUAGE plpgsql;

-- 0. connection role is safe
INSERT INTO r(name, ok, info)
SELECT 'api role is not superuser / bypassrls', NOT (rolsuper OR rolbypassrls), current_user
FROM pg_roles WHERE rolname = current_user;

-- 1. no tenant set -> zero rows, no error
INSERT INTO r(name, ok, info) SELECT 'no tenant: 0 rows, no error', count(*) = 0, count(*)::text FROM mission;

-- 2. issuer lookup works before tenant is set
INSERT INTO r(name, ok, info)
SELECT 'resolve_tenant_by_issuer', resolve_tenant_by_issuer('https://kc/realms/a') = 'aaaaaaaa-0000-0000-0000-000000000001', NULL;
INSERT INTO r(name, ok, info) SELECT 'tenant table hidden without tenant', count(*) = 0, count(*)::text FROM tenant;

-- 3. tenant A data
SELECT set_config('app.tenant_id', 'aaaaaaaa-0000-0000-0000-000000000001', false);
INSERT INTO mission (tenant_id, code, city, country_code, location)
VALUES (current_tenant_id(), 'NBO', 'Nairobi', 'KE', 'SRID=4326;POINT(36.8080 -1.2950)');
INSERT INTO site (tenant_id, mission_id, site_type, name, location)
SELECT current_tenant_id(), id, 'HOTEL', 'Hotel', 'SRID=4326;POINT(36.8240 -1.2975)' FROM mission WHERE code = 'NBO';
INSERT INTO person (id, tenant_id, person_type, full_name)
VALUES ('cccccccc-0000-0000-0000-000000000001', current_tenant_id(), 'DELEGATE', 'Test Delegate');
INSERT INTO person_location_current (person_id, tenant_id, location, confidence, primary_source)
VALUES ('cccccccc-0000-0000-0000-000000000001', current_tenant_id(), 'SRID=4326;POINT(36.8240 -1.2975)', 89, 'TRAVEL_BOOKING');
INSERT INTO incident (tenant_id, reference, title, category, severity, signal_severity, location)
VALUES (current_tenant_id(), next_reference('INC', true), 'Unrest', 'CIVIL_UNREST', 'CRITICAL', 'HIGH', 'SRID=4326;POINT(36.8245 -1.2838)');

INSERT INTO r(name, ok, info)
SELECT 'impact-zone view finds hotel guest (~1.5 km)', count(*) = 1, string_agg(distance_m::text, ',')
FROM v_incident_people_in_zone;
SELECT pg_temp.expect_error('incident severity below signal severity rejected',
  $q$INSERT INTO incident (tenant_id, reference, title, category, severity, signal_severity, location)
     VALUES (current_tenant_id(), 'X', 't', 'C', 'LOW', 'HIGH', 'SRID=4326;POINT(0 0)')$q$);

-- 4. tenant B cannot see or write A's data
SELECT set_config('app.tenant_id', 'bbbbbbbb-0000-0000-0000-000000000002', false);
INSERT INTO r(name, ok, info) SELECT 'tenant B sees 0 missions', count(*) = 0, count(*)::text FROM mission;
INSERT INTO r(name, ok, info) SELECT 'tenant B sees 0 sites (child table)', count(*) = 0, count(*)::text FROM site;
INSERT INTO r(name, ok, info) SELECT 'tenant B sees only its own tenant row', count(*) = 1 AND min(name) = 'Tenant B', min(name) FROM tenant;
SELECT pg_temp.expect_error('tenant B cannot insert rows for tenant A',
  $q$INSERT INTO mission (tenant_id, code, city, country_code, location)
     VALUES ('aaaaaaaa-0000-0000-0000-000000000001', 'X', 'X', 'XX', 'SRID=4326;POINT(0 0)')$q$);
SELECT pg_temp.expect_error('api cannot create tenants',
  $q$INSERT INTO tenant (name, oidc_issuer) VALUES ('evil', 'x')$q$);

-- 5. reference numbers
SELECT set_config('app.tenant_id', 'aaaaaaaa-0000-0000-0000-000000000001', false);
INSERT INTO r(name, ok, info)
SELECT 'next_reference increments', next_reference('INC', true) ~ '^INC-\d{4}-0002$', NULL;

-- 6. audit chain
INSERT INTO audit_log (tenant_id, actor_type, action, entity_type, details) VALUES
  (current_tenant_id(), 'SYSTEM', 'TEST.ONE', 'test', '{"a":1}'),
  (current_tenant_id(), 'USER',   'TEST.TWO', 'test', '{"b":2}'),
  (current_tenant_id(), 'AGENT',  'TEST.THREE', 'test', '{}');
INSERT INTO r(name, ok, info) SELECT 'audit chain_seq 1..3 and linked', array_agg(chain_seq ORDER BY chain_seq) = '{1,2,3}'
  AND bool_and(row_hash IS NOT NULL), NULL FROM audit_log;
INSERT INTO r(name, ok, info) SELECT 'audit_verify_chain() intact', audit_verify_chain() IS NULL, audit_verify_chain()::text;
SELECT pg_temp.expect_error('audit UPDATE blocked', $q$UPDATE audit_log SET action = 'X'$q$);
SELECT pg_temp.expect_error('audit DELETE blocked', $q$DELETE FROM audit_log$q$);
SELECT pg_temp.expect_error('audit TRUNCATE blocked', $q$TRUNCATE audit_log$q$);
INSERT INTO audit_log (tenant_id, chain_seq, actor_type, action, entity_type, prev_hash, row_hash)
VALUES (current_tenant_id(), 1, 'USER', 'FORGE', 'x', 'nope', 'deadbeef');
INSERT INTO r(name, ok, info) SELECT 'app-supplied seq/hash are overwritten by the DB',
  chain_seq = 4 AND row_hash <> 'deadbeef' AND audit_verify_chain() IS NULL, chain_seq::text
  FROM audit_log WHERE action = 'FORGE';

-- 7. agents and policies
INSERT INTO role (tenant_id, code, name) VALUES (current_tenant_id(), 'DUTY_OFFICER', 'Duty');
INSERT INTO app_user (id, tenant_id, external_id, email, display_name) VALUES
  ('dddddddd-0000-0000-0000-000000000001', current_tenant_id(), 's1', 'hom@x', 'HoM'),
  ('dddddddd-0000-0000-0000-000000000002', current_tenant_id(), 's2', 'hq@x', 'HQ');
INSERT INTO agent (id, tenant_id, code, name, autonomy_level) VALUES
  ('eeeeeeee-0000-0000-0000-000000000001', current_tenant_id(), 'COMMS', 'Comms', 0);
INSERT INTO action_policy (tenant_id, action_type, min_autonomy_level, approver_roles, is_undoable) VALUES
  (current_tenant_id(), 'SEND_EXTERNAL_MESSAGE', 2, '{DUTY_OFFICER|CONSULAR_OFFICER}', false),
  (current_tenant_id(), 'START_EVACUATION', 3, '{HEAD_OF_MISSION,HQ_CRISIS_DIRECTOR}', false),
  (current_tenant_id(), 'LOG_INFO', 0, '{}', true);
SELECT pg_temp.expect_error('policy level 3 with one approver rejected',
  $q$INSERT INTO action_policy (tenant_id, action_type, min_autonomy_level, approver_roles)
     VALUES (current_tenant_id(), 'BAD', 3, '{HEAD_OF_MISSION}')$q$);

INSERT INTO agent_proposal (id, tenant_id, agent_id, proposal_key, action_type, title, proposed_action) VALUES
  ('ffffffff-0000-0000-0000-000000000001', current_tenant_id(), 'eeeeeeee-0000-0000-0000-000000000001', 'k1', 'SEND_EXTERNAL_MESSAGE', 't', 'p'),
  ('ffffffff-0000-0000-0000-000000000002', current_tenant_id(), 'eeeeeeee-0000-0000-0000-000000000001', 'k2', 'NO_SUCH_ACTION', 't', 'p'),
  ('ffffffff-0000-0000-0000-000000000003', current_tenant_id(), 'eeeeeeee-0000-0000-0000-000000000001', 'k3', 'START_EVACUATION', 't', 'p'),
  ('ffffffff-0000-0000-0000-000000000004', current_tenant_id(), 'eeeeeeee-0000-0000-0000-000000000001', 'k4', 'LOG_INFO', 't', 'p');

INSERT INTO r(name, ok, info) SELECT 'AUTO agent + external message => level 2, 1 approver, deadline set',
  p.effective_level = 2 AND p.deadline_at IS NOT NULL AND (SELECT count(*) FROM proposal_approval a WHERE a.proposal_id = p.id) = 1,
  p.effective_level::text FROM agent_proposal p WHERE id = 'ffffffff-0000-0000-0000-000000000001';
INSERT INTO r(name, ok, info) SELECT 'unknown action => level 4, no approvers',
  p.effective_level = 4 AND NOT EXISTS (SELECT 1 FROM proposal_approval a WHERE a.proposal_id = p.id),
  p.effective_level::text FROM agent_proposal p WHERE id = 'ffffffff-0000-0000-0000-000000000002';
INSERT INTO r(name, ok, info) SELECT 'evacuation => level 3, 2 ordered approvers',
  p.effective_level = 3 AND (SELECT array_agg(required_role ORDER BY step_no) FROM proposal_approval a WHERE a.proposal_id = p.id) = '{HEAD_OF_MISSION,HQ_CRISIS_DIRECTOR}',
  p.effective_level::text FROM agent_proposal p WHERE id = 'ffffffff-0000-0000-0000-000000000003';
INSERT INTO r(name, ok, info) SELECT 'undoable LOG_INFO stays level 0',
  effective_level = 0, effective_level::text FROM agent_proposal WHERE id = 'ffffffff-0000-0000-0000-000000000004';

SELECT pg_temp.expect_error('app cannot change effective_level',
  $q$UPDATE agent_proposal SET effective_level = 0 WHERE id = 'ffffffff-0000-0000-0000-000000000003'$q$);
SELECT pg_temp.expect_error('app cannot change action_payload',
  $q$UPDATE agent_proposal SET action_payload = '{"x":1}' WHERE id = 'ffffffff-0000-0000-0000-000000000001'$q$);
SELECT pg_temp.expect_error('step 2 cannot be decided before step 1',
  $q$UPDATE proposal_approval SET decision = 'APPROVE', decided_by = 'dddddddd-0000-0000-0000-000000000002', decided_at = now()
     WHERE proposal_id = 'ffffffff-0000-0000-0000-000000000003' AND step_no = 2$q$);
UPDATE proposal_approval SET decision = 'APPROVE', decided_by = 'dddddddd-0000-0000-0000-000000000001', decided_at = now()
 WHERE proposal_id = 'ffffffff-0000-0000-0000-000000000003' AND step_no = 1;
SELECT pg_temp.expect_error('same person cannot approve step 2',
  $q$UPDATE proposal_approval SET decision = 'APPROVE', decided_by = 'dddddddd-0000-0000-0000-000000000001', decided_at = now()
     WHERE proposal_id = 'ffffffff-0000-0000-0000-000000000003' AND step_no = 2$q$);
SELECT pg_temp.expect_error('a decided step cannot be changed',
  $q$UPDATE proposal_approval SET decision = 'REJECT' WHERE proposal_id = 'ffffffff-0000-0000-0000-000000000003' AND step_no = 1$q$);
UPDATE proposal_approval SET decision = 'APPROVE', decided_by = 'dddddddd-0000-0000-0000-000000000002', decided_at = now()
 WHERE proposal_id = 'ffffffff-0000-0000-0000-000000000003' AND step_no = 2;
INSERT INTO r(name, ok, info) SELECT 'different person approves step 2', count(*) = 2, count(*)::text
  FROM proposal_approval WHERE proposal_id = 'ffffffff-0000-0000-0000-000000000003' AND decision = 'APPROVE';
SELECT pg_temp.expect_error('approval rows cannot be created pre-decided',
  $q$INSERT INTO proposal_approval (tenant_id, proposal_id, step_no, required_role, decision, decided_by)
     VALUES (current_tenant_id(), 'ffffffff-0000-0000-0000-000000000001', 9, 'X', 'APPROVE', 'dddddddd-0000-0000-0000-000000000001')$q$);
SELECT pg_temp.expect_error('rejection needs a reason',
  $q$UPDATE agent_proposal SET status = 'REJECTED' WHERE id = 'ffffffff-0000-0000-0000-000000000001'$q$);

-- 8. kill switch
UPDATE tenant SET agents_paused = true, agents_paused_at = now() WHERE id = current_tenant_id();
SELECT pg_temp.expect_error('kill switch blocks new proposals',
  $q$INSERT INTO agent_proposal (tenant_id, agent_id, proposal_key, action_type, title, proposed_action)
     VALUES (current_tenant_id(), 'eeeeeeee-0000-0000-0000-000000000001', 'k9', 'LOG_INFO', 't', 'p')$q$);
SELECT pg_temp.expect_error('api cannot rename its tenant', $q$UPDATE tenant SET name = 'x'$q$);

-- 9. check-in history keeps latest
INSERT INTO notification_campaign (id, tenant_id, reference, campaign_type, message, channels, created_by_type)
VALUES ('99999999-0000-0000-0000-000000000001', current_tenant_id(), next_reference('NTF', false), 'CHECKIN', 'Are you safe?', '{APP,SMS}', 'PLAYBOOK');
INSERT INTO checkin_response (tenant_id, campaign_id, person_id, status, responded_at) VALUES
  (current_tenant_id(), '99999999-0000-0000-0000-000000000001', 'cccccccc-0000-0000-0000-000000000001', 'SAFE', now() - interval '1 min'),
  (current_tenant_id(), '99999999-0000-0000-0000-000000000001', 'cccccccc-0000-0000-0000-000000000001', 'NEED_HELP', now());
INSERT INTO r(name, ok, info) SELECT 'check-in latest answer counts', status = 'NEED_HELP', status FROM v_checkin_latest;
SELECT pg_temp.expect_error('unknown channel rejected',
  $q$INSERT INTO notification_campaign (tenant_id, reference, campaign_type, message, channels, created_by_type)
     VALUES (current_tenant_id(), 'N', 'ALERT', 'm', '{PIGEON}', 'USER')$q$);

SELECT CASE WHEN ok THEN 'PASS' ELSE 'FAIL' END || '  ' || name || CASE WHEN NOT ok OR name LIKE '%forged%' THEN '  [' || coalesce(info, '') || ']' ELSE '' END FROM r ORDER BY n;
SELECT count(*) FILTER (WHERE ok) || ' passed, ' || count(*) FILTER (WHERE NOT ok) || ' failed' FROM r;
