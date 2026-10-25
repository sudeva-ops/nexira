# OWASP ASVS Level 2: Phase 1 checklist and gaps

For the security reviewer and the pilot's risk owner (NFR 2: "OWASP ASVS L2 as target").

## Scope and method

- **What is in scope:** the code and configuration in this repository at Prompt 16. That is the Phase 1 screens (D-25), the FastAPI backend and worker, the nginx frontend, the Helm chart and the backup scripts.
- **Who owns the rest:** Keycloak, PostgreSQL, the cluster and the ingress belong to the pilot's operators. Their rows say what NEXIRA requires of them.
- **Numbering:** [ASVS 4.0.3](https://owasp.org/www-project-application-security-verification-standard/). Mapping to ASVS 5.0 is a follow-up (gap G-15).
- **Granularity:** requirements are grouped by section, not listed one by one. Every group with any shortfall is marked Partial or Gap, and the shortfall is listed in [Gaps](#gaps).
- **Who wrote this:** an AI agent, from reading the code and running the tests. **It is not an audit.** Nothing here has been verified by a human; [docs/security-review.md](../security-review.md) lists what a human must check.

**Status values**

| Status | Meaning |
|---|---|
| Met | Implemented, with the evidence named |
| Partial | Some of the group is met; the rest is a gap |
| Gap | Not implemented |
| IdP / Ops | The identity provider or the operators must provide it; NEXIRA documents the requirement |
| N/A | The feature does not exist in Phase 1 |

## Checklist

### V1 Architecture

| Area | Status | Evidence / notes |
|---|---|---|
| 1.1 Secure SDLC, threat model | Partial | Decisions log (`docs/decisions.md`), named-reviewer sign-off for security code (D-29), CI with lint, types and tests. **No written threat model** (G-01). |
| 1.2 Authentication architecture | Met | One trusted issuer and JWKS URL from config, never from the token (`backend/app/core/security.py`). The same validation serves HTTP and WebSocket (`principal_from_token`). |
| 1.4 Access control architecture | Met | Tenant isolation is enforced in the database: FORCE RLS on every tenant table, and `set_config` per transaction (D-01, D-02; `backend/app/core/db.py`). Approval roles and mission scope are checked in one place (`backend/app/core/approvals.py`, D-05). |
| 1.5 Input and output architecture | Met | Pydantic models at every API boundary; SQLAlchemy bound parameters; React escaping. |
| 1.6 Cryptographic architecture | Partial | The audit hash chain is computed by the database (SHA-256, D-20). TLS is at the ingress. There is no application-level encryption of personal fields (G-08). |
| 1.7 Logging architecture | Partial | Every state change is audited in a hash-chained table (`backend/app/core/audit.py`). Process logs are unstructured text with no request ID (G-09). |
| 1.14 Configuration and deployment | Met | One container image per tier; separate database users per purpose (API, owner, backup) and separate Secrets for each; default-deny network policies (`infra/helm/nexira`). |

### V2 Authentication / V3 Session management

NEXIRA delegates login, MFA, passwords and sessions to Keycloak (D-04). The API only accepts short-lived bearer tokens.

| Area | Status | Evidence / notes |
|---|---|---|
| 2.1 Passwords, 2.2 authenticator lifecycle, 2.5 recovery, 2.8 OTP | IdP | The pilot realm must require OTP MFA, a password policy and brute-force detection (`docs/runbooks/pilot-deployment.md` §4). **No pilot realm export is delivered** (G-02). The demo realm has brute-force detection but no MFA and no password policy. That is acceptable for local use only. |
| 2.10 Service authentication | Met | Each service has its own database user; no shared superuser; passwords come from Secrets or a vault. The API refuses to start as a superuser or BYPASSRLS role (`verify_connection_role`). |
| 3.2 Session binding, 3.3 logout and timeout | Partial | Tokens are kept in memory by keycloak-js (no localStorage). The access token lives 5 min and the SSO idle timeout is 30 min (demo realm). Logout goes through Keycloak. An open WebSocket is closed when its token expires (close 4401, `backend/app/core/realtime.py`). Every request checks that the `app_user` is active (`current_user`), so deactivating a user in NEXIRA takes effect at once. **Gap:** a user disabled only in Keycloak keeps access until their access token expires, up to 5 min (G-03). |
| 3.4 Cookie-based sessions | N/A | The app uses no cookies; the API takes bearer tokens only. |
| 3.5 Token-based sessions | Met | RS256 only; issuer, audience, `exp`, `iat` and `sub` required; 30 s clock leeway; `kid` must be in the JWKS (`decode_token`). Tests: `backend/app/tests/test_security.py`. |

### V4 Access control

| Area | Status | Evidence / notes |
|---|---|---|
| 4.1 General (deny by default, least privilege) | Met | Every API operation except `/api/health` requires the bearer token (`test_every_api_operation_but_health_needs_a_bearer_token`). Roles come from `user_role`, never from the token (D-04). `nexira_api` cannot create objects or bypass RLS. |
| 4.2 Operation level (IDOR) | Met | RLS returns nothing from other tenants (`backend/app/tests/test_tenant_isolation.py`, `test_schema_checks.py`). Mission scope is checked for Heads of Mission (D-05). |
| 4.3 Administrative interfaces | Met | Audit and agent controls need the ADMIN role. The scenario API (demo control) is not mounted in a pilot (`create_app`, D-21). |
| Business rules: two-person rule, agent approval | Met | Distinct approvers in order (D-16, database triggers plus `approvals.decide`). Agents act only through proposals (D-12), and the database sets `effective_level`. |

### V5 Validation, sanitisation and encoding

| Area | Status | Evidence / notes |
|---|---|---|
| 5.1 Input validation | Partial | Typed Pydantic models, enums, and limits on paging and notes. **Most free-text fields have no maximum length** (G-04); nginx caps request bodies at 1 MB. |
| 5.2 Sanitisation, 5.3 output encoding | Met | React escapes all text; no `dangerouslySetInnerHTML`, `eval` or `new Function` in `frontend/src`. The API returns JSON only. |
| 5.3.4 SQL injection | Met | Only bound parameters. No string-built SQL outside tests (one test interpolates fixed table names). |
| 5.5 Deserialisation | Met | JSON only, parsed into Pydantic models. No pickle or YAML loading of input. |

### V6 Stored cryptography

| Area | Status | Evidence / notes |
|---|---|---|
| 6.2 Algorithms | Met | SHA-256 (pgcrypto) for the audit chain; RS256 verification for tokens. No home-made cryptography. |
| 6.4 Secret management | Partial | The chart reads Secrets that pilots sync from a vault (`secrets.existing`), and `.env` is git-ignored. **There is no vault integration in the chart itself**, and `secrets.create` puts passwords in values; it is documented as for test clusters only (G-05). |
| Encryption at rest (NFR 2, AES-256) | Ops | It depends on encrypted storage classes for PostgreSQL, Redis and the backup PVC. The backup dumps themselves are not encrypted by NEXIRA (G-06). |

### V7 Errors and logging

| Area | Status | Evidence / notes |
|---|---|---|
| 7.1 Log content | Partial | Tokens are never put in URLs; the WebSocket sends its token in the first message. Realtime payloads carry ids and counts, not personal data. **No review has been done of what uvicorn and worker logs contain** (G-09). |
| 7.2 Log processing | Met for audit | `audit_log` is append-only (UPDATE, DELETE and TRUNCATE are blocked by triggers) and hash-chained; `GET /api/audit/verify` checks it. A broken chain is detected after a restore (`docs/runbooks/backup-restore.md`). |
| 7.3 Log protection | Partial | The audit log is protected as above. Process logs go to stdout; their retention and protection are the cluster's job. Failed logins are logged only in Keycloak (G-10). |
| 7.4 Error handling | Met | Rule refusals are mapped to 403 or 409 (`backend/app/core/errors.py`). Unexpected errors return a generic 500 without a stack trace, and are logged. |

### V8 Data protection

| Area | Status | Evidence / notes |
|---|---|---|
| 8.1 Server-side protection | Partial | Personal data stays in PostgreSQL behind RLS. **No field-level encryption** (G-08). Welfare and medical data do not exist in Phase 1 (NFR 3). |
| 8.2 Client-side | Met | API responses carry `Cache-Control: no-store` (nginx). Tokens are kept in memory only. Nothing is written to localStorage. |
| 8.3 Sensitive private data | Partial | Only simulated data in the repository. **No data retention or deletion process for personal data yet** (G-11). The audit retention default of 7 years (NFR 4) is not enforced by a job. |

### V9 Communications

| Area | Status | Evidence / notes |
|---|---|---|
| 9.1 Client TLS | Ops | TLS terminates at the ingress or route (TLS 1.3, runbook §6). The chart refuses an Ingress without a TLS Secret, and the Route redirects plain HTTP. HSTS is set for one year. |
| 9.2 Server TLS (internal) | Partial | `?ssl=require` on the database DSNs is documented. **Traffic between pods (frontend to backend, backend to Redis) is plain** inside the cluster, limited by network policies (G-07). |

### V10 Malicious code

| Area | Status | Evidence / notes |
|---|---|---|
| 10.2 Malicious code search | Partial | No runtime calls to external services: map tiles, AI and channels are all local or simulated (AGENTS.md). Dependencies are pinned by lockfiles. **No dependency vulnerability scanning in CI** (G-12). |
| 10.3 Integrity of deployed code | Partial | Images are built from this repository. **No image signing or SBOM** (G-13). |

### V11 Business logic

| Area | Status | Evidence / notes |
|---|---|---|
| 11.1 Business logic security | Partial | Ordered approvals, one person per step, decide-once, idempotency keys on proposals and deliveries, and an agent kill switch (D-16, D-17). **No rate limiting or anti-automation** on the API (G-14); the IdP limits login attempts. |

### V12 Files and resources

| Area | Status | Evidence / notes |
|---|---|---|
| 12.1–12.5 Uploads and file execution | N/A | No file upload in Phase 1. Map tiles are static, read-only files. |
| 12.6 SSRF | Met | The only outbound HTTP call the API makes is to the configured JWKS URL (`security.py`). No URL ever comes from a user or a token. Network policies allow egress only to the configured IdP. |

### V13 API and web service

| Area | Status | Evidence / notes |
|---|---|---|
| 13.1 Generic | Met | One JSON API under `/api`. The API docs and OpenAPI document are switched off in a pilot. |
| 13.2 RESTful | Met | Bearer tokens make CSRF not applicable (no cookies). Methods match actions, and state changes are POST or PATCH. |
| WebSocket (`/ws`) | Partial | Authenticated with the first message, within 10 s; tenant-scoped fan-out; re-authentication on token refresh with the same subject. **The `Origin` header is not checked** (low risk without cookies: a cross-site page has no token to send). |

### V14 Configuration

| Area | Status | Evidence / notes |
|---|---|---|
| 14.1 Build and deploy | Met | Reproducible images from lockfiles; CI runs lint, type checks and tests against real PostgreSQL + PostGIS; `make helm-check` validates the chart. |
| 14.2 Dependencies | Partial | Pinned versions; no external CDNs at run time. No automated vulnerability scan (G-12). |
| 14.3 Unintended disclosure | Met | The nginx version is hidden. The API docs are off in a pilot. No debug mode. The demo-only presenter bar is a build-time flag (`VITE_DEMO_MODE=false` for pilots). |
| 14.4 HTTP security headers | Met | CSP (`script-src 'self'`; no inline scripts; `frame-ancestors 'none'`), X-Content-Type-Options, X-Frame-Options, Referrer-Policy and Permissions-Policy, plus HSTS in the chart. Source: `frontend/security-headers.conf.template` and `infra/helm/nexira/templates/frontend-configmap.yaml`. The Phase 1 acceptance e2e suite fails on any CSP violation. Styles allow `'unsafe-inline'` for React and Blueprint style attributes. |
| 14.5 Request header validation | Partial | Only GET, POST and PATCH routes exist (plus the `/ws` WebSocket); FastAPI rejects other methods. No host-header allow-list in nginx (`server_name _`); the ingress host rule restricts it in a pilot. |
| Containers (beyond ASVS) | Met | Non-root, read-only root filesystem, no capabilities, RuntimeDefault seccomp, no service-account token. Meets the restricted PSS and OpenShift `restricted-v2`. |

## Gaps

Ordered by suggested priority for the pilot. None is fixed in this change unless stated.

| ID | Gap | ASVS | Suggested fix |
|---|---|---|---|
| G-02 | No pilot Keycloak realm export with MFA required, a password policy and no password-grant client | V2 | Deliver `infra/keycloak/pilot-realm.json` and test that it refuses a login without OTP |
| G-14 | No rate limiting or anti-automation on the API or WebSocket | 11.1, 13.1 | Rate limits at the ingress (per IP and per token), plus a per-user limit on the decision endpoints |
| G-12 | No dependency vulnerability scanning | 10.2, 14.2 | `pip-audit` and `npm audit` (or an offline scanner for air-gapped builds) in CI |
| G-05 | No built-in vault integration; `secrets.create` puts passwords in values | 6.4 | Ship an ExternalSecret example; refuse `secrets.create` when `APP_ENV=pilot` |
| G-11 | No retention or deletion job for personal data, and audit retention is not enforced | 8.3 | A retention policy and job, decided with the data protection officer |
| G-01 | No written threat model | 1.1 | STRIDE over the data flows in this document, reviewed with the customer |
| G-07 | Plain traffic between pods inside the cluster | 9.2 | A service mesh with mTLS, or TLS on Redis and the backend |
| G-03 | A user disabled only in Keycloak keeps access until their access token expires (≤ 5 min); deactivating the `app_user` is immediate | 3.3 | Accept and document in the leaver process (deactivate in both), or shorten the token lifespan |
| G-06 | Backup dumps are not encrypted by NEXIRA | 6.x, NFR 2 | Encrypt dumps (age or GPG) before they leave the PVC; copy them off-site |
| G-08 | No field-level encryption of personal data | 6.1, 8.1 | Decide which fields need it (for example passport numbers in later phases) |
| G-04 | Free-text fields have no maximum length | 5.1 | Add `max_length` to every string field in the request schemas |
| G-09 | Unstructured process logs with no request ID. Log content has not been reviewed for personal data: for example, `errors.py` logs database error messages, which can include values from the failing row | 7.1 | JSON logs with a request ID; log the SQLSTATE and constraint name, not the message; review what the access logs record |
| G-10 | Failed logins are logged only in Keycloak | 7.3 | Forward Keycloak events to the same log store as the audit trail |
| G-13 | No image signing or SBOM | 10.3 | cosign signatures and a CycloneDX SBOM per release |
| G-15 | This checklist uses ASVS 4.0.3 numbering | n/a | Map it to ASVS 5.0 |
| G-16 | The chart has not been installed on a real cluster | 14.1 | Install it in a staging namespace and run the egress check (runbook §7) |
| G-17 | Pilot tenant and first-admin onboarding needs hand-written SQL; there is no tool | 4.3 | A small, audited admin CLI that runs as `nexira_owner` |

## Hardening done in Prompt 16

- `APP_ENV=pilot` removes the scenario API and the API docs (`backend/app/main.py`). Tested in `backend/app/tests/test_health.py`.
- The demo seed refuses to run outside local or demo (`simulator/nexira_sim/seed/__main__.py`).
- Security headers and `Cache-Control: no-store` on the API in nginx. The frontend now runs on unprivileged nginx (port 8080).
- A test that every API operation requires authentication.
- The read-only `nexira_backup` role for backups, so neither application role needs to bypass RLS (`infra/postgres/backup-role.sql`, `backend/app/tests/test_backup_role.py`).
- The migrate Job gets only the owner DSN (`backend/migrations/env.py` reads `MIGRATIONS_DATABASE_URL` directly).
