"""Common source-adapter interface and registry.

Every marketplace adapter implements :class:`SourceAdapter`. Transport (live HTTP) is
separated from parsing (pure, fixture-tested) so the test suite never hits the network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from vehicle_finder.configio import SearchTarget
from vehicle_finder.models.listing import VehicleListing
from vehicle_finder.sources.http import PoliteClient


def _empty_listings() -> list[VehicleListing]:
    return []


def _empty_strs() -> list[str]:
    return []


@dataclass
class FetchResult:
    """Outcome of fetching one search from one source."""

    listings: list[VehicleListing] = field(default_factory=_empty_listings)
    found: int = 0  # raw records seen (pre-parse)
    parse_failures: int = 0
    warnings: list[str] = field(default_factory=_empty_strs)
    layout_changed: bool = False


@runtime_checkable
class SourceAdapter(Protocol):
    """A marketplace adapter. ``id`` is the stable source key used in config + storage."""

    id: str

    def supports(self, target: SearchTarget) -> bool:
        """Whether this source can serve the given search target."""
        ...

    def fetch(self, target: SearchTarget, client: PoliteClient) -> FetchResult:
        """Live-fetch + parse listings for one search target."""
        ...


# --------------------------------------------------------------------------- registry
_REGISTRY: dict[str, SourceAdapter] = {}


def register(adapter: SourceAdapter) -> None:
    _REGISTRY[adapter.id] = adapter


def get_adapter(source_id: str) -> SourceAdapter | None:
    _ensure_loaded()
    return _REGISTRY.get(source_id)


def all_adapters() -> list[SourceAdapter]:
    _ensure_loaded()
    return list(_REGISTRY.values())


_loaded = False


def _ensure_loaded() -> None:
    """Import adapter modules so they self-register. Import-light to avoid cycles."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    from vehicle_finder.sources import bmw_nl

    bmw_nl.register_adapters()
