"""Load and validate the human-editable YAML configuration.

All tunable knobs — search targets, per-source model codes, scoring weights, rare-option
definitions, equipment synonyms, import-cost assumptions — live in ``config/*.yaml`` and
are validated here. Nothing in this file is hard-coded business data.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel

from vehicle_finder.config import get_settings
from vehicle_finder.models.enums import VehicleType


class SourceConfig(BaseModel):
    """Static configuration for one source adapter."""

    enabled: bool = True
    adapter: str | None = None  # adapter implementation key, e.g. "bmw_ps", "dasimport"
    vehicle_types: list[VehicleType] = []
    base_url: str
    request_uri: str = ""
    rate_limit_seconds: float | None = None
    notes: str | None = None


class SearchTarget(BaseModel):
    """One configured search. Drives queries and acts as the scoring 'ideal'."""

    id: str
    vehicle_type: VehicleType
    make: str
    model: str
    enabled: bool = True
    aliases: list[str] = []
    variant_generation: str | None = None

    min_year: int | None = None
    max_year: int | None = None
    max_mileage: int | None = None
    min_price: int | None = None
    max_price: int | None = None

    countries: list[str] = ["NL"]
    max_distance_km: float | None = None
    seller_type: str | None = None  # "dealer" | "private" | None=any

    required_equipment: list[str] = []
    preferred_equipment: list[str] = []
    excluded_equipment: list[str] = []
    excluded_terms: list[str] = []
    preferred_colours: list[str] = []
    excluded_colours: list[str] = []

    # Car-oriented optional filters
    body_style: str | None = None
    fuel_type: str | None = None
    transmission: str | None = None
    drivetrain: str | None = None
    min_power_hp: int | None = None
    max_power_hp: int | None = None

    # Per-source code maps, e.g. {"bmw-nl": {"serie": "BMW X Serie", "model": "X5"}}
    source_codes: dict[str, dict[str, Any]] = {}

    def codes_for(self, source: str) -> dict[str, Any]:
        return self.source_codes.get(source, {})


class SearchesFile(BaseModel):
    home_postcode: str | None = None
    searches: list[SearchTarget] = []


class SourcesFile(BaseModel):
    sources: dict[str, SourceConfig] = {}


# --------------------------------------------------------------------------- IO
def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return cast("dict[str, Any]", data) if isinstance(data, dict) else {}


def _config_dir() -> Path:
    return get_settings().config_path


@functools.lru_cache(maxsize=1)
def load_sources() -> dict[str, SourceConfig]:
    return SourcesFile.model_validate(_load_yaml(_config_dir() / "sources.yaml")).sources


@functools.lru_cache(maxsize=1)
def load_searches() -> list[SearchTarget]:
    return SearchesFile.model_validate(_load_yaml(_config_dir() / "searches.yaml")).searches


def get_search(search_id: str) -> SearchTarget | None:
    return next((s for s in load_searches() if s.id == search_id), None)


def load_yaml_mapping(name: str) -> dict[str, Any]:
    """Load a raw YAML mapping file from the config dir (synonyms, weights, features)."""
    return _load_yaml(_config_dir() / name)


def clear_cache() -> None:
    """Reset cached config (used in tests after pointing at a fixture config dir)."""
    load_sources.cache_clear()
    load_searches.cache_clear()
