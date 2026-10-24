"""Agent and policy definitions. Prompt 4: seeding. Proposals, the policy engine
and the executor arrive in Prompt 12 (D-29 sign-off required there)."""

from dataclasses import dataclass

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.modules.agents.models import ActionPolicy, Agent
from app.modules.tenancy.service import SYSTEM, Actor


@dataclass(frozen=True)
class AgentIn:
    code: str
    name: str
    description: str
    autonomy_level: int  # 0 AUTO .. 4 ADVISE_ONLY


@dataclass(frozen=True)
class PolicyIn:
    action_type: str
    min_autonomy_level: int
    approver_roles: list[str]  # one entry per step; '|' separates alternatives (D-16)
    is_undoable: bool  # D-13
    decision_deadline_s: int = 900


async def ensure_agents(
    session: AsyncSession, agents: list[AgentIn], actor: Actor = SYSTEM
) -> list[str]:
    tenant_id = session.info["tenant_id"]
    created = await session.scalars(
        insert(Agent)
        .values(
            [
                {
                    "tenant_id": tenant_id,
                    "code": a.code,
                    "name": a.name,
                    "description": a.description,
                    "autonomy_level": a.autonomy_level,
                }
                for a in agents
            ]
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "code"])
        .returning(Agent.code)
    )
    codes = sorted(created.all())
    for code in codes:
        agent = next(a for a in agents if a.code == code)
        await audit.write(
            session,
            actor_type=actor.type,
            actor_id=actor.id,
            action="AGENT.CREATE",
            entity_type="agent",
            entity_id=code,
            details={"autonomy_level": agent.autonomy_level},
        )
    return codes


async def ensure_policies(
    session: AsyncSession, policies: list[PolicyIn], actor: Actor = SYSTEM
) -> list[str]:
    tenant_id = session.info["tenant_id"]
    created = await session.scalars(
        insert(ActionPolicy)
        .values(
            [
                {
                    "tenant_id": tenant_id,
                    "action_type": p.action_type,
                    "min_autonomy_level": p.min_autonomy_level,
                    "approver_roles": p.approver_roles,
                    "is_undoable": p.is_undoable,
                    "decision_deadline_s": p.decision_deadline_s,
                }
                for p in policies
            ]
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "action_type"])
        .returning(ActionPolicy.action_type)
    )
    types = sorted(created.all())
    for action_type in types:
        policy = next(p for p in policies if p.action_type == action_type)
        await audit.write(
            session,
            actor_type=actor.type,
            actor_id=actor.id,
            action="ACTION_POLICY.CREATE",
            entity_type="action_policy",
            entity_id=action_type,
            details={
                "min_autonomy_level": policy.min_autonomy_level,
                "approver_roles": policy.approver_roles,
                "is_undoable": policy.is_undoable,
            },
        )
    return types
