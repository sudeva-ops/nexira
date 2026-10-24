"""Authentication. Implemented in Prompt 3. Changes need human sign-off (D-29).

- Validate Keycloak OIDC JWTs: signature, issuer, audience, expiry.
- Tenant from resolve_tenant_by_issuer(iss); app_user by (tenant, sub) (D-04).
- Role claims in the token are ignored; roles come from user_role (D-04).
"""
