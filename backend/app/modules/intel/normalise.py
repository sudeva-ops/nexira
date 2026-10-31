"""Signal normaliser (INC-02, D-11).

Each signal is normalised on its own, through its own source's category_map and
severity_map. Nothing here looks at other signals, so a per-source map decides
the result alone: Riskline "Moderate" stays MODERATE even when Dataminr says
"High" about the same event.

Natural hazards (D-38): for a measured category the signal's own measure decides the
severity instead of the map (app/modules/intel/hazards.py).
"""

from dataclasses import dataclass
from typing import Any

from app.modules.intel import hazards

SEVERITIES = ("LOW", "MODERATE", "HIGH", "CRITICAL")  # D-08; same order as severity_rank()


def severity_rank(severity: str) -> int:
    return SEVERITIES.index(severity) + 1


def max_severity(*severities: str) -> str:
    return max(severities, key=severity_rank)


@dataclass(frozen=True)
class Normalised:
    category: str | None
    severity: str | None
    reason: str | None = None  # why the signal is discarded; None when it is usable

    @property
    def discarded(self) -> bool:
        return self.reason is not None


def normalise(
    *,
    category_map: dict[str, str],
    severity_map: dict[str, str],
    provider_category: str | None,
    provider_severity: str | None,
    has_location: bool,
    payload: dict[str, Any] | None = None,
) -> Normalised:
    """Map one signal. Unknown or unmapped values discard it (never guessed)."""
    category = category_map.get(provider_category) if provider_category else None
    severity = severity_map.get(provider_severity) if provider_severity else None
    if severity is not None and severity not in SEVERITIES:
        severity = None  # a map entry outside D-08 is treated as unmapped
    if category is None:
        return Normalised(None, severity, f"unknown category {provider_category!r}")
    try:
        measured = hazards.severity(category, payload)
    except hazards.HazardError as e:
        return Normalised(category, None, str(e))
    if measured is not None:
        severity = measured
    if severity is None:
        return Normalised(category, None, f"unknown severity {provider_severity!r}")
    if not has_location:
        return Normalised(category, severity, "no location")
    return Normalised(category, severity)
