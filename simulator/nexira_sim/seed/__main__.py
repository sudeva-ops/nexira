"""`make seed`: python -m nexira_sim.seed

Needs DATABASE_URL (nexira_api), MIGRATIONS_DATABASE_URL (nexira_owner, used only
to create the tenant row) and OIDC_ISSUER.
"""

import asyncio
import os
import sys

from app.core.db import create_engine

from nexira_sim.seed.identities import bootstrap_tenant, seed_identities


async def main() -> None:
    try:
        api_dsn = os.environ["DATABASE_URL"]
        owner_dsn = os.environ["MIGRATIONS_DATABASE_URL"]
        issuer = os.environ["OIDC_ISSUER"]
    except KeyError as missing:
        sys.exit(f"seed: {missing.args[0]} is not set (run through `make seed`).")

    tenant_id = await bootstrap_tenant(owner_dsn, issuer)
    engine = create_engine(api_dsn)
    try:
        result = await seed_identities(engine, tenant_id)
    finally:
        await engine.dispose()
    print(
        f"seed: tenant {tenant_id}; {result['users']} demo users, {result['new_grants']} new grants"
    )


if __name__ == "__main__":
    asyncio.run(main())
