"""`make seed`: python -m nexira_sim.seed

Needs DATABASE_URL (nexira_api), MIGRATIONS_DATABASE_URL (nexira_owner, used only
to create the tenant row) and OIDC_ISSUER. SCENARIO_DATE (YYYY-MM-DD) is optional
and defaults to today in UTC (plan G-11).
"""

import asyncio
import json
import os
import sys
from datetime import UTC, date, datetime

from app.core.db import create_engine

from nexira_sim.seed.load import seed_all


async def main() -> None:
    try:
        api_dsn = os.environ["DATABASE_URL"]
        owner_dsn = os.environ["MIGRATIONS_DATABASE_URL"]
        issuer = os.environ["OIDC_ISSUER"]
    except KeyError as missing:
        sys.exit(f"seed: {missing.args[0]} is not set (run through `make seed`).")
    raw_date = os.environ.get("SCENARIO_DATE")
    scenario_date = date.fromisoformat(raw_date) if raw_date else datetime.now(UTC).date()

    engine = create_engine(api_dsn)
    try:
        report = await seed_all(
            engine, owner_dsn=owner_dsn, issuer=issuer, scenario_date=scenario_date
        )
    finally:
        await engine.dispose()
    print("seed:", json.dumps(report, default=str))


if __name__ == "__main__":
    asyncio.run(main())
