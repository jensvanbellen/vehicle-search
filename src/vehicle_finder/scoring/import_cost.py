"""German-import cost ESTIMATE — a separate, clearly-labelled module.

These are manually-maintained PLACEHOLDERS from ``config/import_costs.yaml``, NOT an
authoritative Dutch BPM/RDW calculation. Every line item is shown and the whole thing is
labelled an estimate. Applies only to vehicles physically located in Germany (country=DE).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

from vehicle_finder.configio import load_yaml_mapping
from vehicle_finder.models.enums import VehicleType
from vehicle_finder.models.listing import VehicleListing


def _empty_items() -> list[tuple[str, int]]:
    return []


@dataclass
class ImportEstimate:
    line_items: list[tuple[str, int]] = field(default_factory=_empty_items)
    added_total: int = 0
    asking_price: int | None = None
    all_in_price: int | None = None
    disclaimer: str = ""
    is_estimate: bool = True


def _cfg() -> dict[str, Any]:
    return load_yaml_mapping("import_costs.yaml")


def applies_to(listing: VehicleListing) -> bool:
    cfg = _cfg()
    return bool(cfg.get("enabled", True)) and (listing.country or "").upper() == "DE"


def estimate_import_cost(listing: VehicleListing) -> ImportEstimate | None:
    """Rough all-in NL cost for a German car. None if not a DE listing / disabled."""
    if not applies_to(listing):
        return None
    cfg = _cfg()
    components: dict[str, Any] = (
        cfg.get("components", {}) if isinstance(cfg.get("components"), dict) else {}
    )

    items: list[tuple[str, int]] = []
    for key in ("transport", "rdw_inspection", "registration_admin"):
        amount = components.get(key)
        if isinstance(amount, int):
            items.append((key.replace("_", " ").title(), amount))

    # BPM: motorcycles per motorcycle_bpm; cars per model override else default placeholder.
    if listing.vehicle_type is VehicleType.MOTORCYCLE:
        bpm = int(cfg.get("motorcycle_bpm", 0) or 0)
    else:
        raw_overrides = cfg.get("bpm_overrides")
        overrides: dict[str, Any] = (
            cast("dict[str, Any]", raw_overrides) if isinstance(raw_overrides, dict) else {}
        )
        default_bpm = components.get("bpm_estimate_default", 0)
        bpm = int(overrides.get(listing.model or "", default_bpm) or 0)
    if bpm:
        items.append(("BPM (placeholder estimate)", bpm))

    added = sum(amount for _label, amount in items)
    all_in = (listing.price + added) if listing.price is not None else None
    return ImportEstimate(
        line_items=items,
        added_total=added,
        asking_price=listing.price,
        all_in_price=all_in,
        disclaimer=str(
            cfg.get("disclaimer", "Rough placeholder estimate — not an official BPM calculation.")
        ),
    )
