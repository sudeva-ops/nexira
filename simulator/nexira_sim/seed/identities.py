"""Seed step 1: demo tenant, roles, the missions roles are scoped to, and the demo
users from the Keycloak realm with their role grants (D-04, D-05, plan G-03, G-05).

The realm export is the single source of user ids: each app_user.external_id is
the Keycloak user id, which becomes the token's `sub`. All names are fictional.
"""

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

import asyncpg
from app.core.db import tenant_session
from app.modules.people.service import ensure_mission
from app.modules.tenancy import service as tenancy
from sqlalchemy.ext.asyncio import AsyncEngine

REPO_DIR = Path(__file__).resolve().parents[3]
REALM_FILE = REPO_DIR / "infra" / "keycloak" / "nexira-demo-realm.json"

SEED_NS = uuid.UUID("0b7c1e7a-4f4e-4b8e-9f1d-6a0f6c3e2d55")
DEMO_TENANT_ID = uuid.uuid5(SEED_NS, "tenant:mofa-demo")
DEMO_TENANT_NAME = "Ministry of Foreign Affairs (demo)"


def seed_id(kind: str, key: str) -> uuid.UUID:
    """Deterministic ids, so seeding twice gives identical data (plan G-11)."""
    return uuid.uuid5(SEED_NS, f"{kind}:{key}")


# Missions that demo roles are scoped to. Coordinates from the demo's MISSIONS
# array; Prompt 4 adds the other 34 missions and all sites.
MISSIONS = {
    "NBO": ("Nairobi", "KE", -1.286, 36.817),
    "CAI": ("Cairo", "EG", 30.04, 31.24),
}

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


async def bootstrap_tenant(owner_dsn: str, issuer: str) -> uuid.UUID:
    """Tenants can only be created by nexira_owner (plan G-03). Nothing else is
    written with the owner role."""
    conn = await asyncpg.connect(owner_dsn.replace("postgresql+asyncpg://", "postgresql://", 1))
    try:
        await conn.execute(
            "INSERT INTO tenant (id, name, oidc_issuer) VALUES ($1, $2, $3) "
            "ON CONFLICT (id) DO NOTHING",
            DEMO_TENANT_ID,
            DEMO_TENANT_NAME,
            issuer,
        )
        stored = await conn.fetchval("SELECT oidc_issuer FROM tenant WHERE id = $1", DEMO_TENANT_ID)
    finally:
        await conn.close()
    if stored != issuer:
        raise RuntimeError(
            f"Demo tenant exists with issuer {stored!r}, not {issuer!r}. "
            "Run `make reset-demo` to recreate the local database."
        )
    return DEMO_TENANT_ID


async def seed_identities(engine: AsyncEngine, tenant_id: uuid.UUID) -> dict[str, int]:
    users = realm_users()
    async with tenant_session(tenant_id, engine) as session:
        role_ids = await tenancy.ensure_roles(session)
        mission_ids = {
            code: await ensure_mission(
                session,
                code=code,
                city=city,
                country_code=cc,
                lat=lat,
                lon=lon,
                mission_id=seed_id("mission", code),
            )
            for code, (city, cc, lat, lon) in MISSIONS.items()
        }
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
        await session.commit()
    return {"users": len(users), "new_grants": grants}
