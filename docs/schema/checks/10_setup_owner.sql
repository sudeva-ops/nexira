-- Run as nexira_owner: create two tenants (tenant table is not FORCE'd, so owner may insert).
INSERT INTO tenant (id, name, oidc_issuer) VALUES
  ('aaaaaaaa-0000-0000-0000-000000000001', 'Tenant A', 'https://kc/realms/a'),
  ('bbbbbbbb-0000-0000-0000-000000000002', 'Tenant B', 'https://kc/realms/b');
