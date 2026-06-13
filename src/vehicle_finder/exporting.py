"""CSV / JSON export of normalized listings (with price history) and consolidated groups."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from sqlmodel import select

from vehicle_finder.config import get_settings
from vehicle_finder.models.group import VehicleGroup
from vehicle_finder.models.history import PriceObservation
from vehicle_finder.models.listing import VehicleListing
from vehicle_finder.persistence.db import session_scope

_CSV_COLUMNS = [
    "id",
    "group_id",
    "source",
    "source_listing_id",
    "vehicle_type",
    "make",
    "model",
    "variant",
    "model_year",
    "mileage_km",
    "price",
    "currency",
    "country",
    "distance_km",
    "seller_name",
    "fuel_type",
    "transmission",
    "power_hp",
    "colour",
    "kenteken",
    "vin",
    "score",
    "status",
    "url",
    "first_seen",
    "last_seen",
]


def _listing_row(listing: VehicleListing) -> dict[str, Any]:
    return {
        "id": listing.id,
        "group_id": listing.group_id,
        "source": listing.source,
        "source_listing_id": listing.source_listing_id,
        "vehicle_type": listing.vehicle_type.value,
        "make": listing.make,
        "model": listing.model,
        "variant": listing.variant,
        "model_year": listing.model_year,
        "mileage_km": listing.mileage_km,
        "price": listing.price,
        "currency": listing.currency,
        "country": listing.country,
        "distance_km": listing.distance_km,
        "seller_name": listing.seller_name,
        "fuel_type": listing.fuel_type.value if listing.fuel_type else None,
        "transmission": listing.transmission.value if listing.transmission else None,
        "power_hp": listing.power_hp,
        "colour": listing.colour,
        "kenteken": listing.kenteken,
        "vin": listing.vin,
        "score": listing.score,
        "status": listing.status.value,
        "url": listing.url,
        "first_seen": listing.first_seen.isoformat(),
        "last_seen": listing.last_seen.isoformat(),
    }


def export_listings(fmt: str = "json", out: str = "data/exports/export") -> str:
    """Export all listings (+price history) and groups. Returns the written file path."""
    settings = get_settings()
    with session_scope() as session:
        listings = list(session.exec(select(VehicleListing)).all())
        groups = list(session.exec(select(VehicleGroup)).all())
        history: dict[int, list[dict[str, Any]]] = {}
        for obs in session.exec(select(PriceObservation)).all():
            history.setdefault(obs.listing_id, []).append(
                {
                    "price": obs.price,
                    "currency": obs.currency,
                    "observed_at": obs.observed_at.isoformat(),
                }
            )

        out_path = settings.resolve(Path(out))
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if fmt == "csv":
            target = out_path.with_suffix(".csv")
            with target.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=_CSV_COLUMNS)
                writer.writeheader()
                for listing in listings:
                    writer.writerow(_listing_row(listing))
            return str(target)

        if fmt == "json":
            target = out_path.with_suffix(".json")
            payload = {
                "listings": [
                    {**_listing_row(x), "price_history": history.get(x.id or -1, [])}
                    for x in listings
                ],
                "groups": [
                    {
                        "group_id": g.group_id,
                        "make": g.make,
                        "model": g.model,
                        "model_year": g.model_year,
                        "member_count": g.member_count,
                        "sources": g.sources,
                        "canonical_price": g.canonical_price,
                        "price_spread": g.price_spread,
                        "score": g.score,
                        "merge_explanation": g.merge_explanation,
                    }
                    for g in groups
                ],
            }
            target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            return str(target)

    raise ValueError(f"unsupported export format: {fmt!r} (use 'json' or 'csv')")
