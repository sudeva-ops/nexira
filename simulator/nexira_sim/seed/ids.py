import uuid

SEED_NS = uuid.UUID("0b7c1e7a-4f4e-4b8e-9f1d-6a0f6c3e2d55")

DEMO_TENANT_ID = uuid.uuid5(SEED_NS, "tenant:mofa-demo")


def seed_id(tenant_id: uuid.UUID, kind: str, key: str) -> uuid.UUID:
    """Deterministic ids, so seeding twice gives identical data (plan G-11).

    The tenant is part of the key: primary keys are global, so two tenants seeded
    from the same data must never share an id.
    """
    return uuid.uuid5(SEED_NS, f"{tenant_id}:{kind}:{key}")
