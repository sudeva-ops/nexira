"""Performance check (requirements §5): server-side timings of the newest Nairobi
incident on the demo tenant, as JSON.

- signal_to_incident_s: the first signal's publish time (the scenario player's
  occurred_at) to the incident row being written.
- incident_to_exposure_s: the incident row to its first exposure computation.
- incident_created_at: for the browser to measure the UI update.

    APP_ENV=local uv run python -m nexira_sim.fixtures.timings
"""

import asyncio
import json
import os
import sys

from app.core.db import create_engine, tenant_session
from sqlalchemy import text

from nexira_sim.seed.ids import DEMO_TENANT_ID

_QUERY = text(
    """
    SELECT i.reference, i.created_at,
           (SELECT min(s.occurred_at) FROM incident_signal l JOIN raw_signal s ON s.id = l.signal_id
             WHERE l.incident_id = i.id) AS first_signal_at,
           (SELECT min(e.occurred_at) FROM incident_event e
             WHERE e.incident_id = i.id AND e.event_type = 'EXPOSURE') AS exposure_at
      FROM incident i
     WHERE i.category = 'CIVIL_UNREST'
     ORDER BY i.created_at DESC
     LIMIT 1
    """
)


async def timings() -> dict[str, object]:
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        async with tenant_session(DEMO_TENANT_ID, engine) as session:
            row = (await session.execute(_QUERY)).one_or_none()
    finally:
        await engine.dispose()
    if row is None or row.first_signal_at is None:
        raise SystemExit("no Nairobi incident yet")
    return {
        "reference": row.reference,
        "incident_created_at": row.created_at.isoformat(),
        "signal_to_incident_s": round((row.created_at - row.first_signal_at).total_seconds(), 3),
        "incident_to_exposure_s": (
            round((row.exposure_at - row.created_at).total_seconds(), 3)
            if row.exposure_at
            else None
        ),
    }


def main() -> None:
    if os.environ.get("APP_ENV") not in ("local", "demo"):
        sys.exit("refused: APP_ENV must be local or demo")
    print(json.dumps(asyncio.run(timings())))


if __name__ == "__main__":
    main()
