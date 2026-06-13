"""Pre-LCI vs LCI (facelift) detection from build date.

LCI = "Life Cycle Impulse", BMW's mid-cycle facelift. The pre-LCI X5 G05 keeps iDrive 7
and the physical climate panel; the LCI moves to the curved display. We flag it from the
*build* date (more reliable than registration) against per-generation facelift dates in
``config/generations.yaml``. When only the registration date is known, confidence is lower.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from datetime import date
from typing import Any, cast

from vehicle_finder.configio import load_yaml_mapping
from vehicle_finder.normalize.fields import parse_iso_date


@dataclass(frozen=True)
class LciStatus:
    label: str  # "pre-LCI" | "LCI" | "unknown"
    confidence: str  # "high" (from build date) | "low" (from registration) | "none"

    @property
    def is_pre_lci(self) -> bool:
        return self.label == "pre-LCI"


UNKNOWN = LciStatus("unknown", "none")


@functools.lru_cache(maxsize=1)
def _facelift_dates() -> dict[tuple[str, str], date]:
    raw: Any = load_yaml_mapping("generations.yaml").get("generations")
    out: dict[tuple[str, str], date] = {}
    if not isinstance(raw, dict):
        return out
    for make_model, gens in cast("dict[str, Any]", raw).items():
        if not isinstance(gens, dict):
            continue
        for gen, info in cast("dict[str, Any]", gens).items():
            if isinstance(info, dict):
                fb = cast("dict[str, Any]", info).get("facelift_build_date")
                parsed = parse_iso_date(str(fb)) if fb else None
                if parsed:
                    out[(str(make_model).lower(), str(gen).lower())] = parsed
    return out


def clear_cache() -> None:
    _facelift_dates.cache_clear()


def lci_status(
    make: str | None,
    model: str | None,
    generation: str | None,
    build_date: date | None,
    registration_date: date | None = None,
) -> LciStatus:
    """Classify a vehicle as pre-LCI / LCI / unknown."""
    if not (make and model and generation):
        return UNKNOWN
    boundary = _facelift_dates().get((f"{make} {model}".lower(), generation.lower()))
    if boundary is None:
        return UNKNOWN
    if build_date is not None:
        return LciStatus("pre-LCI" if build_date < boundary else "LCI", "high")
    if registration_date is not None:
        # Registration lags build; use a one-month grace so a clearly-late reg still reads LCI.
        return LciStatus("pre-LCI" if registration_date < boundary else "LCI", "low")
    return UNKNOWN
