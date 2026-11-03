"""The four Phase 1 agents and the pilot's Travel & Air (D-34), Compliance (D-37) and Forecast
(D-46, advice only) agents (D-17 seed table). Deterministic rules and templates."""

from app.modules.agents.agents.base import PhaseOneAgent
from app.modules.agents.agents.communications import Communications
from app.modules.agents.agents.compliance import Compliance
from app.modules.agents.agents.exposure import ExposureAgent
from app.modules.agents.agents.forecast import Forecast
from app.modules.agents.agents.response_planner import ResponsePlanner
from app.modules.agents.agents.travel_air import TravelAir
from app.modules.agents.agents.watch_officer import WatchOfficer

AGENTS: tuple[PhaseOneAgent, ...] = (
    WatchOfficer(),
    ExposureAgent(),
    ResponsePlanner(),
    Communications(),
    TravelAir(),
    Compliance(),
    Forecast(),
)

__all__ = ["AGENTS", "PhaseOneAgent"]
