"""Imports every module's models so Base.metadata is complete."""

from app.core.model_base import Base
from app.modules.agents.models import ActionPolicy, Agent, AgentProposal, ProposalApproval
from app.modules.audit.models import AuditLog
from app.modules.checkin.models import CheckinResponse
from app.modules.intel.models import (
    Incident,
    IncidentEvent,
    IncidentExposure,
    IncidentSignal,
    IntelSource,
    RawSignal,
)
from app.modules.notifications.models import NotificationCampaign, NotificationDelivery
from app.modules.partners.models import Partner, PartnerRequest
from app.modules.people.models import (
    LocationObservation,
    Mission,
    Person,
    PersonLocationCurrent,
    Site,
)
from app.modules.playbooks.models import Playbook, PlaybookRun, PlaybookRunStep, PlaybookStep
from app.modules.scenarios.models import Scenario, ScenarioEvent, ScenarioRun
from app.modules.tenancy.models import AppUser, ReferenceCounter, Role, Tenant, UserRole
from app.modules.travel.models import Trip, TripTraveller
from app.modules.weather.models import WeatherCurrent

__all__ = [
    "ActionPolicy",
    "Agent",
    "AgentProposal",
    "AppUser",
    "AuditLog",
    "Base",
    "CheckinResponse",
    "Incident",
    "IncidentEvent",
    "IncidentExposure",
    "IncidentSignal",
    "IntelSource",
    "LocationObservation",
    "Mission",
    "NotificationCampaign",
    "NotificationDelivery",
    "Partner",
    "PartnerRequest",
    "Person",
    "PersonLocationCurrent",
    "Playbook",
    "PlaybookRun",
    "PlaybookRunStep",
    "PlaybookStep",
    "ProposalApproval",
    "RawSignal",
    "ReferenceCounter",
    "Role",
    "Scenario",
    "ScenarioEvent",
    "ScenarioRun",
    "Site",
    "Tenant",
    "Trip",
    "TripTraveller",
    "UserRole",
    "WeatherCurrent",
]
