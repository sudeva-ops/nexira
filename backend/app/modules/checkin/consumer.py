"""CHECKIN_RESPONSE events (the simulator, D-28): the person answering on a
simulated channel. "campaign": "latest_open_checkin" is resolved here to the
person's newest open CHECKIN campaign (Prompt 5).

- Accepted only while a demo scenario is running in the tenant. Real answers
  come through the API (and, in Phase 2, real channels); a stray or forged
  stream event must not mark a real person SAFE and stop their escalation.
- Idempotent: the event id is recorded with the answer, so a redelivered event
  is skipped.
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncEngine

from app.core import audit
from app.core.db import tenant_session
from app.core.events import Event, Handler, Publisher
from app.modules.checkin import service
from app.modules.notifications.channels import CHANNELS
from app.modules.notifications.models import NotificationCampaign
from app.modules.notifications.service import demo_running
from app.modules.tenancy.service import Actor

log = logging.getLogger(__name__)

SIMULATED_PERSON = Actor(type="SYSTEM", id="channel.simulated")
NOTE_MAX = 1000


def response_handler(engine: AsyncEngine, publisher: Publisher) -> Handler:
    async def handle(event: Event) -> None:
        payload = event.payload
        async with tenant_session(event.tenant_id, engine) as session:
            if await service.already_recorded(session, str(event.id)):
                return
            try:
                if not await demo_running(session):
                    raise service.CheckinError("simulated answers need a running demo scenario")
                person_id = uuid.UUID(str(payload["person_id"]))
                raw = str(payload["status"])
                if raw not in ("SAFE", "NEED_HELP"):
                    raise service.CheckinError("unknown status")
                status: service.Answer = "SAFE" if raw == "SAFE" else "NEED_HELP"
                channel = payload.get("channel")
                if channel is not None and channel not in CHANNELS:
                    raise service.CheckinError("unknown channel")
                note = payload.get("note")
                if note is not None and (not isinstance(note, str) or len(note) > NOTE_MAX):
                    raise service.CheckinError("invalid note")
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
                    channel=channel,
                    note=note,
                    actor=SIMULATED_PERSON,
                    source_event_id=str(event.id),
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
                    details={"reason": str(e)[:200], "source": event.source[:200]},
                )
                await session.commit()
                return
            await session.commit()
            campaign = await session.get_one(NotificationCampaign, campaign_id)
        try:
            await publisher.publish(service.updated_event(campaign))
        except Exception:
            log.exception("publishing CHECKIN_UPDATED failed after commit")

    return handle
