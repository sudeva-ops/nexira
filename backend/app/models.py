"""Imports every module's models so Base.metadata is complete."""

from app.core.model_base import Base
from app.modules.aar.models import AarItem, AfterActionReview
from app.modules.agents.models import ActionPolicy, Agent, AgentProposal, ProposalApproval
from app.modules.annotations.models import MapAnnotation
from app.modules.audit.models import AuditLog
from app.modules.checkin.models import CheckinResponse
from app.modules.documents.models import TravelDocument
from app.modules.evacuations.models import Evacuation, EvacuationManifestEntry, EvacuationPlan
from app.modules.exercises.models import Exercise, ExerciseScore
from app.modules.fleet.models import FleetAsset, FleetMaintenance
from app.modules.hazards.models import MissionClimateRisk
from app.modules.health_intel.models import (
    CountryHealthRequirement,
    HealthAdvisory,
    MedicalFacility,
    MissionHealthReadiness,
)
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
from app.modules.predictive.models import MissionEvent, RiskIndex
from app.modules.scenarios.models import Scenario, ScenarioEvent, ScenarioRun
from app.modules.supply.models import LogisticsRoute, Supplier, SupplyMitigation
from app.modules.tenancy.models import AppUser, ReferenceCounter, Role, Tenant, UserRole
from app.modules.travel.models import Trip, TripTraveller
from app.modules.twin.models import (
    SitePresence,
    SiteReadinessItem,
    SiteRoute,
    SiteSensor,
    SiteZone,
)
from app.modules.vip.models import VipChecklistItem, VipSegment, VipSegmentChange, VipVisit
from app.modules.weather.models import WeatherCurrent

__all__ = [
    "AarItem",
    "ActionPolicy",
    "AfterActionReview",
    "Agent",
    "AgentProposal",
    "AppUser",
    "AuditLog",
    "Base",
    "CheckinResponse",
    "CountryHealthRequirement",
    "Evacuation",
    "EvacuationManifestEntry",
    "EvacuationPlan",
    "Exercise",
    "ExerciseScore",
    "FleetAsset",
    "FleetMaintenance",
    "HealthAdvisory",
    "Incident",
    "IncidentEvent",
    "IncidentExposure",
    "IncidentSignal",
    "IntelSource",
    "LocationObservation",
    "LogisticsRoute",
    "MapAnnotation",
    "MedicalFacility",
    "Mission",
    "MissionClimateRisk",
    "MissionEvent",
    "MissionHealthReadiness",
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
    "RiskIndex",
    "Role",
    "Scenario",
    "ScenarioEvent",
    "ScenarioRun",
    "Site",
    "SitePresence",
    "SiteReadinessItem",
    "SiteRoute",
    "SiteSensor",
    "SiteZone",
    "Supplier",
    "SupplyMitigation",
    "Tenant",
    "TravelDocument",
    "Trip",
    "TripTraveller",
    "UserRole",
    "VipChecklistItem",
    "VipSegment",
    "VipSegmentChange",
    "VipVisit",
    "WeatherCurrent",
]
