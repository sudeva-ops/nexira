import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvals import roles_of
from app.core.security import CurrentUser, current_user, get_db
from app.modules.agents import proposals
from app.modules.agents.models import AgentProposal
from app.modules.documents import service as documents
from app.modules.evacuations import service as evacuations
from app.modules.fleet import service as fleet
from app.modules.health_intel import service as health
from app.modules.notifications import compose
from app.modules.notifications.models import NotificationCampaign
from app.modules.playbooks import service as playbooks
from app.modules.playbooks.schemas import PermissionsOut
from app.modules.supply import service as supply
from app.modules.tenancy.schemas import MeOut, RoleOut
from app.modules.travel import trips
from app.modules.travel.models import Trip
from app.modules.twin import service as twin
from app.modules.vip import service as vip

router = APIRouter(prefix="/api", tags=["tenancy"])


@router.get("/me")
async def me(
    user: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> MeOut:
    """The caller and their roles from user_role, never from the token (D-04)."""
    grants = await roles_of(session, user.id)
    return MeOut(
        id=user.id,
        display_name=user.display_name,
        email=user.email,
        roles=[
            RoleOut(code=g.code, mission_id=g.mission_id, mission_code=g.mission_code)
            for g in grants
        ],
    )


def _missions(scope: documents.Scope | None) -> list[uuid.UUID] | None:
    """None: every mission (or, with the flag false, none at all)."""
    if scope is None or scope.missions is None:
        return None
    return sorted(scope.missions, key=str)


@router.get("/me/permissions")
async def my_permissions(
    entity_type: Literal[
        "playbook_run",
        "agent_proposal",
        "notification_campaign",
        "trip",
        "documents",
        "hazards",
        "health",
        "evacuation",
        "fleet",
        "vip_visit",
        "site",
        "supplier",
    ],
    user: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    entity_id: uuid.UUID | None = None,
) -> PermissionsOut:
    """Plan G-07: the actions the caller may take on an entity now, computed by
    approvals.can_decide(), the same code that enforces them. "documents" is the
    register as a whole (no entity_id): read and act, and the missions each covers
    (plan-pilot-dx §7)."""
    if entity_type == "documents":
        read = await documents.read_scope(session, user)
        act = await documents.act_scope(session, user)
        return PermissionsOut(
            entity_type=entity_type,
            entity_id="",
            read_documents=read is not None,
            act_documents=act is not None,
            read_document_missions=_missions(read),
            act_document_missions=_missions(act),
        )
    if entity_id is None:
        raise HTTPException(422, f"{entity_type} needs an entity_id")
    if entity_type == "notification_campaign":
        campaign = await session.get(NotificationCampaign, entity_id)
        if campaign is None:
            return PermissionsOut(entity_type=entity_type, entity_id=str(entity_id))
        allowed = await compose.permissions(session, user, campaign)
        return PermissionsOut(
            entity_type=entity_type,
            entity_id=str(entity_id),
            edit_campaign=allowed.edit,
            submit_campaign=allowed.submit,
            approve_campaign=allowed.approve,
            cancel_campaign=allowed.cancel,
        )
    if entity_type == "hazards":
        # HZ-10, G-1: the incident's arming actions, by the same checks as the endpoints.
        arming = await playbooks.arming_permissions(session, user, entity_id)
        return PermissionsOut(
            entity_type=entity_type,
            entity_id=str(entity_id),
            arm_playbook=arming.arm,
            start_armed=arming.start,
            disarm=arming.disarm,
        )
    if entity_type == "health":
        # HL-06, HL-09: entity_id is the mission; the same check as the endpoint.
        return PermissionsOut(
            entity_type=entity_type,
            entity_id=str(entity_id),
            send_advisory=await health.send_permission(session, user, entity_id),
        )
    if entity_type == "evacuation":
        # EV-02, EV-04, EV-05, EV-07: entity_id is the mission; the endpoints' own checks.
        evacuating = await evacuations.permissions(session, user, entity_id)
        return PermissionsOut(
            entity_type=entity_type,
            entity_id=str(entity_id),
            activate_evacuation=evacuating.activate,
            confirm_evacuation=evacuating.confirm,
            check_in_evacuee=evacuating.check_in,
            advance_evacuation=evacuating.advance,
            stand_down_evacuation=evacuating.stand_down,
        )
    if entity_type == "fleet":
        # FLT-04: entity_id is the mission; the endpoints' own check (plan-pilot-flt §7).
        acting = await fleet.permissions(session, user, entity_id)
        return PermissionsOut(
            entity_type=entity_type,
            entity_id=str(entity_id),
            set_asset_status=acting.set_status,
            complete_maintenance=acting.complete,
        )
    if entity_type == "vip_visit":
        # VIP-04, VIP-05: the endpoints' own checks; all false unless the caller sees it.
        visit = await vip.permissions(session, user, entity_id)
        return PermissionsOut(
            entity_type=entity_type,
            entity_id=str(entity_id),
            start_visit=visit.start,
            progress_visit=visit.progress,
            cancel_visit=visit.cancel,
            tick_vip_checklist=visit.tick,
            propose_vip_change=list(visit.propose),
            decide_vip_change=list(visit.decide),
        )
    if entity_type == "site":
        # TWN-05: entity_id is the site; the endpoint's own check.
        return PermissionsOut(
            entity_type=entity_type,
            entity_id=str(entity_id),
            tick_readiness=(await twin.permissions(session, user, entity_id)).tick_readiness,
        )
    if entity_type == "supplier":
        # SUP-04: entity_id is the supplier; the endpoints' own checks.
        mitigating = await supply.permissions(session, user, documents.today_utc(), entity_id)
        return PermissionsOut(
            entity_type=entity_type,
            entity_id=str(entity_id),
            activate_mitigation=mitigating.activate_mitigation,
            stand_down_mitigation=mitigating.stand_down_mitigation,
        )
    if entity_type == "trip":
        trip = await session.get(Trip, entity_id)
        if trip is None:
            return PermissionsOut(entity_type=entity_type, entity_id=str(entity_id))
        may = await trips.permissions(session, user, trip)
        return PermissionsOut(
            entity_type=entity_type,
            entity_id=str(entity_id),
            edit_trip=may.edit,
            submit_trip=may.submit,
            approve_trip=may.approve,
            reject_trip=may.reject,
            check_trip=may.check,
            cancel_trip=may.cancel,
        )
    if entity_type == "agent_proposal":
        proposal = await session.get(AgentProposal, entity_id)
        if proposal is None:
            return PermissionsOut(entity_type=entity_type, entity_id=str(entity_id))
        return PermissionsOut(
            entity_type=entity_type,
            entity_id=str(entity_id),
            decide_proposal=await proposals.can_decide(session, user, proposal),
            edit_proposal=await proposals.can_edit(session, user, proposal),
            dismiss_proposal=await proposals.can_dismiss(session, user, proposal),
            undo_proposal=await proposals.can_undo(session, user, proposal),
        )
    return PermissionsOut(
        entity_type=entity_type,
        entity_id=str(entity_id),
        approve_step=await playbooks.approvable_steps(session, user, entity_id),
    )
