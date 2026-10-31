"""The seeded travel documents (Document Expiry, D-37, plan-pilot-dx §8).

Pure and deterministic. Dates come from a SHA-256 digest of each document's id, never
from the world's rng, so every other seeded figure stays where it is. They are relative
to the seed date: `make reset-demo` gives the same days left every time.
"""

import hashlib
import uuid
from datetime import timedelta

from app.modules.documents.service import DocumentIn

from nexira_sim.seed import data
from nexira_sim.seed.ids import seed_id
from nexira_sim.seed.world import World, trip_travellers

BASE_DAYS = 200  # nobody else is under the six-month rule
SPREAD_DAYS = 3000


def _digest(document_id: uuid.UUID) -> int:
    return int.from_bytes(hashlib.sha256(document_id.bytes).digest()[:8], "big")


def build(w: World, tenant_id: uuid.UUID) -> tuple[list[DocumentIn], list[uuid.UUID]]:
    """Every document, and those whose renewal is already in progress."""
    missions = {m.id: m for m in w.missions}
    quiet = {m.id for m in w.missions if m.code in data.DOCUMENT_QUIET_MISSIONS}
    ref, warn_days = data.DOCUMENT_TRIP_WARNING
    _ref, _p, home, count, *_ = next(t for t in data.EXTRA_TRIPS if t[0] == ref)
    home_id = next(m.id for m in w.missions if m.code == home)
    travellers = trip_travellers(w, home_id, count)
    warned = travellers[0]

    docs: list[DocumentIn] = []
    for p in w.persons:
        if p.mission_id is None or p.person_type not in data.DOCUMENTS_BY_TYPE:
            continue
        host = missions[p.mission_id].country_code
        for doc_type in data.DOCUMENTS_BY_TYPE[p.person_type]:
            doc_id = seed_id(tenant_id, "travel_document", f"{p.id}:{doc_type}")
            passport = doc_type in ("PASSPORT", "DIPLOMATIC_PASSPORT")
            issuer = data.HOME_COUNTRY if passport and p.person_type != "LOCAL_STAFF" else host
            days = data.NAMED_DOCUMENTS.get(
                (p.full_name, doc_type), BASE_DAYS + _digest(doc_id) % SPREAD_DAYS
            )
            if p.id == warned and passport:
                days = warn_days
            docs.append(
                DocumentIn(doc_id, p.id, doc_type, issuer, w.scenario_date + timedelta(days))
            )

    # Elsewhere: documents picked by digest get the design's short dates. Not the warned
    # trip's travellers: only the first one is short (DX-06), whatever the tenant id.
    mission_of = {p.id: p.mission_id for p in w.persons}
    candidates = sorted(
        (d for d in docs if d.person_id not in travellers and mission_of[d.person_id] not in quiet),
        key=lambda d: _digest(d.id),
    )
    critical = candidates[: data.DOCUMENT_CRITICAL_OTHERS]
    high = candidates[len(critical) : len(critical) + data.DOCUMENT_HIGH_OTHERS]
    picked = {d.id for d in critical + high}
    moderate = [
        d for d in candidates[len(picked) :] if d.doc_type in ("PASSPORT", "DIPLOMATIC_PASSPORT")
    ][: data.DOCUMENT_MODERATE_PASSPORTS]
    days_for = {
        **{d.id: 3 + _digest(d.id) % 26 for d in critical},  # 3..28
        **{d.id: 31 + _digest(d.id) % 58 for d in high},  # 31..88
        **{d.id: 100 + _digest(d.id) % 75 for d in moderate},  # 100..174
    }
    docs = [
        DocumentIn(
            d.id,
            d.person_id,
            d.doc_type,
            d.issuing_country,
            w.scenario_date + timedelta(days_for[d.id]),
        )
        if d.id in days_for
        else d
        for d in docs
    ]
    soon = critical + high
    in_progress = [d.id for n, d in enumerate(soon) if n % 3 != 0][: data.DOCUMENT_IN_PROGRESS]
    return docs, in_progress
