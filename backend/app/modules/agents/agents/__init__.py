"""The four Phase 1 agents (D-17 seed table). Deterministic rules and templates."""

from app.modules.agents.agents.base import PhaseOneAgent
from app.modules.agents.agents.communications import Communications
from app.modules.agents.agents.exposure import ExposureAgent
from app.modules.agents.agents.response_planner import ResponsePlanner
from app.modules.agents.agents.watch_officer import WatchOfficer

AGENTS: tuple[PhaseOneAgent, ...] = (
    WatchOfficer(),
    ExposureAgent(),
    ResponsePlanner(),
    Communications(),
)

__all__ = ["AGENTS", "PhaseOneAgent"]
