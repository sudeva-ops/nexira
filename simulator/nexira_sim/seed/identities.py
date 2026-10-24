"""Seed: the demo tenant, roles, and the demo users from the Keycloak realm with
their role grants (D-04, D-05, plan G-03, G-05).

The realm export is the single source of user ids: each app_user.external_id is
the Keycloak user id, which becomes the token's `sub`. All names are fictional.
"""

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

import asyncpg
from app.modules.tenancy import service as tenancy
from sqlalchemy.ext.asyncio import AsyncSession

from nexira_sim.seed.ids import DEMO_TENANT_ID

REPO_DIR = Path(__file__).resolve().parents[3]
REALM_FILE = REPO_DIR / "infra" / "keycloak" / "nexira-demo-realm.json"

DEMO_TENANT_NAME = "Ministry of Foreign Affairs (demo)"


# username -> [(role code, mission code or None for unscoped/HQ)]
DEMO_ROLES: dict[str, list[tuple[str, str | None]]] = {
    "admin": [("ADMIN", None)],
    "duty.officer": [("DUTY_OFFICER", None)],
    "security.officer": [("SECURITY_OFFICER", None)],
    "hom.nairobi": [("HEAD_OF_MISSION", "NBO")],
    "hom.cairo": [("HEAD_OF_MISSION", "CAI")],  # tests mission scope (D-05)
    "hq.director": [("HQ_CRISIS_DIRECTOR", None)],
    "travel.desk": [("TRAVEL_DESK", None)],
    "consular.officer": [("CONSULAR_OFFICER", None)],
    "viewer": [("VIEWER", None)],
    # Holds both approval roles of START_EVACUATION; tests the two-person rule (D-16).
    "dual.role": [("HEAD_OF_MISSION", "NBO"), ("HQ_CRISIS_DIRECTOR", None)],
}


@dataclass(frozen=True)
class DemoUser:
    keycloak_id: str
    username: str
    email: str
    display_name: str


def realm_users(path: Path = REALM_FILE) -> list[DemoUser]:
    realm = json.loads(path.read_text(encoding="utf-8"))
    return [
        DemoUser(
            keycloak_id=u["id"],
            username=u["username"],
            email=u["email"],
            display_name=f"{u['firstName']} {u['lastName']}",
        )
        for u in realm["users"]
    ]


async def bootstrap_tenant(
    owner_dsn: str, issuer: str, tenant_id: uuid.UUID | None = None
) -> uuid.UUID:
    """Tenants can only be created by nexira_owner (plan G-03). Nothing else is
    written with the owner role. Tests pass their own tenant_id."""
    tenant_id = tenant_id or DEMO_TENANT_ID
    conn = await asyncpg.connect(owner_dsn.replace("postgresql+asyncpg://", "postgresql://", 1))
    try:
        await conn.execute(
            "INSERT INTO tenant (id, name, oidc_issuer) VALUES ($1, $2, $3) "
            "ON CONFLICT (id) DO NOTHING",
            tenant_id,
            DEMO_TENANT_NAME,
            issuer,
        )
        stored = await conn.fetchval("SELECT oidc_issuer FROM tenant WHERE id = $1", tenant_id)
    finally:
        await conn.close()
    if stored != issuer:
        raise RuntimeError(
            f"Demo tenant exists with issuer {stored!r}, not {issuer!r}. "
            "Run `make reset-demo` to recreate the local database."
        )
    return tenant_id


async def seed_identities(
    session: AsyncSession, mission_ids: dict[str, uuid.UUID]
) -> dict[str, int]:
    """Roles, users and grants, in the caller's tenant session and transaction."""
    users = realm_users()
    role_ids = await tenancy.ensure_roles(session)
    grants = 0
    for user in users:
        user_id = await tenancy.ensure_user(
            session,
            external_id=user.keycloak_id,
            email=user.email,
            display_name=user.display_name,
        )
        for role_code, mission_code in DEMO_ROLES[user.username]:
            if await tenancy.grant_role(
                session,
                user_id=user_id,
                role_id=role_ids[role_code],
                mission_id=mission_ids[mission_code] if mission_code else None,
            ):
                grants += 1
    return {"users": len(users), "new_grants": grants}
