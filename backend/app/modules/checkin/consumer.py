"""CHECKIN_RESPONSE events (the simulator, D-28): the person answering on a
simulated channel. "campaign": "latest_open_checkin" is resolved here to the
person's newest open CHECKIN campaign (Prompt 5)."""

import uuid

from sqlalchemy.ext.asyncio import AsyncEngine

from app.core import audit
from app.core.db import tenant_session
from app.core.events import Event, Handler, Publisher
from app.modules.checkin import service
from app.modules.notifications.models import NotificationCampaign
from app.modules.tenancy.service import Actor

SIMULATED_PERSON = Actor(type="SYSTEM", id="channel.simulated")


def response_handler(engine: AsyncEngine, publisher: Publisher) -> Handler:
    async def handle(event: Event) -> None:
        payload = event.payload
        async with tenant_session(event.tenant_id, engine) as session:
            try:
                person_id = uuid.UUID(str(payload["person_id"]))
                raw = str(payload["status"])
                if raw not in ("SAFE", "NEED_HELP"):
                    raise service.CheckinError(f"unknown status {raw!r}")
                status: service.Answer = "SAFE" if raw == "SAFE" else "NEED_HELP"
                target = payload.get("campaign", "latest_open_checkin")
                campaign_id = (
                    await service.open_campaign_for(session, person_id)
                    if target == "latest_open_checkin"
                    else uuid.UUID(str(target))
                )
                if campaign_id is None:
                    raise service.CheckinError("no open check-in for this person")
                await service.record_response(
                    session,
                    campaign_id=campaign_id,
                    person_id=person_id,
                    status=status,
                    channel=payload.get("channel"),
                    note=payload.get("note"),
                    actor=SIMULATED_PERSON,
                )
            except (service.CheckinError, KeyError, ValueError) as e:
                await session.rollback()
                await audit.write(
                    session,
                    actor_type=SIMULATED_PERSON.type,
                    actor_id=SIMULATED_PERSON.id,
                    action="CHECKIN.REJECT",
                    entity_type="event",
                    entity_id=str(event.id),
                    details={"reason": str(e), "source": event.source},
                )
                await session.commit()
                return
            await session.commit()
            campaign = await session.get_one(NotificationCampaign, campaign_id)
        await publisher.publish(service.updated_event(campaign))

    return handle
