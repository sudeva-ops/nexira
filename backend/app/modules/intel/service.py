"""Intelligence services. Prompt 4: source definitions. Ingestion, normalisation
and fusion arrive in Prompt 6."""

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.modules.intel.models import IntelSource
from app.modules.tenancy.service import SYSTEM, Actor


@dataclass(frozen=True)
class SourceIn:
    code: str
    name: str
    reliability: Decimal  # D-10
    severity_map: dict[str, str] = field(default_factory=dict)
    category_map: dict[str, str] = field(default_factory=dict)
    connector_type: str = "SIMULATED"
    takes_part_in_fusion: bool = True  # D-09: OSINT is False in Phase 1
    is_enabled: bool = True


async def ensure_sources(
    session: AsyncSession, sources: list[SourceIn], actor: Actor = SYSTEM
) -> list[str]:
    """Create sources whose code is new; return the codes created (audited once each)."""
    tenant_id = session.info["tenant_id"]
    created = await session.scalars(
        insert(IntelSource)
        .values(
            [
                {
                    "tenant_id": tenant_id,
                    "code": s.code,
                    "name": s.name,
                    "reliability": s.reliability,
                    "severity_map": s.severity_map,
                    "category_map": s.category_map,
                    "connector_type": s.connector_type,
                    "takes_part_in_fusion": s.takes_part_in_fusion,
                    "is_enabled": s.is_enabled,
                }
                for s in sources
            ]
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "code"])
        .returning(IntelSource.code)
    )
    codes = sorted(created.all())
    for code in codes:
        source = next(s for s in sources if s.code == code)
        await audit.write(
            session,
            actor_type=actor.type,
            actor_id=actor.id,
            action="INTEL_SOURCE.CREATE",
            entity_type="intel_source",
            entity_id=code,
            details={
                "reliability": str(source.reliability),
                "takes_part_in_fusion": source.takes_part_in_fusion,
                "is_enabled": source.is_enabled,
            },
        )
    return codes
