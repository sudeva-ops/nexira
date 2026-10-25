"""Channel adapters (CHK-04). Changes need human sign-off (D-29).

Phase 1 has no real channels: every channel (APP, SMS, WHATSAPP, VOICE, EMAIL) is
served by SimulatedChannelAdapter, which makes no network call and sends nothing
outside the platform (AGENTS.md). adapter_for() is the only way to get an adapter,
and it refuses any other configuration, so a real adapter cannot be switched on by
a setting.

Contract for any future adapter (Phase 2):
- send() takes an idempotency key (the notification_delivery id). The dispatcher
  may call send() again with the same key after a crash between the provider call
  and the database update; the provider must not deliver twice for one key.
- receipts() reports delivery progress. Receipts are telemetry: they update
  notification_delivery and are not audited (plan G-20).
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

CHANNELS = ("APP", "SMS", "WHATSAPP", "VOICE", "EMAIL")  # the schema's CHECK
DeliveryStatus = Literal["QUEUED", "SENT", "DELIVERED", "READ", "FAILED"]


@dataclass(frozen=True)
class Recipient:
    person_id: uuid.UUID
    preferred_lang: str | None


@dataclass(frozen=True)
class Sent:
    provider_ref: str
    sent_at: datetime


class ChannelAdapter(Protocol):
    name: str

    async def send(
        self, recipient: Recipient, channel: str, text: str, idempotency_key: str, now: datetime
    ) -> Sent: ...

    def receipt(self, provider_ref: str, sent_at: datetime, now: datetime) -> DeliveryStatus: ...


class SimulatedChannelAdapter:
    """Pretends to deliver. Deterministic: the provider ref comes from the
    idempotency key, so a repeated send returns the same ref, and receipts depend
    only on the time since sending."""

    name = "simulated"
    DELIVERED_AFTER_S = 2.0
    READ_AFTER_S = 6.0

    async def send(
        self, recipient: Recipient, channel: str, text: str, idempotency_key: str, now: datetime
    ) -> Sent:
        digest = hashlib.sha256(f"{channel}:{idempotency_key}".encode()).hexdigest()[:16]
        return Sent(provider_ref=f"SIM-{channel}-{digest}", sent_at=now)

    def receipt(self, provider_ref: str, sent_at: datetime, now: datetime) -> DeliveryStatus:
        elapsed = (now - sent_at).total_seconds()
        if elapsed >= self.READ_AFTER_S:
            return "READ"
        if elapsed >= self.DELIVERED_AFTER_S:
            return "DELIVERED"
        return "SENT"


SUPPORTED = ("simulated",)
_simulated = SimulatedChannelAdapter()


class UnsupportedAdapterError(ValueError):
    pass


def adapter_for(channel: str, configured: str = "simulated") -> ChannelAdapter:
    """The adapter for a channel. Phase 1: only the simulated adapter exists."""
    if configured not in SUPPORTED:
        raise UnsupportedAdapterError(f"channel adapter {configured!r} is not available in Phase 1")
    if channel not in CHANNELS:
        raise UnsupportedAdapterError(f"unknown channel {channel!r}")
    return _simulated
