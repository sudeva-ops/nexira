"""Database access. Implemented in Prompt 2.

Rules this module will enforce:
- Connect only as nexira_api (DATABASE_URL), never as the owner or a superuser,
  because those bypass row-level security (D-01). Fail at startup if the role
  is a superuser or has BYPASSRLS.
- Start every transaction with SELECT set_config('app.tenant_id', :tid, true) (D-02).
- READ COMMITTED isolation, the PostgreSQL default (D-20).
"""
