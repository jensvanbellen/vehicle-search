"""Manual listing entry.

The fallback for sources we must not auto-fetch (e.g. mobile.de, whose listing pages
are robots-disallowed): the user pastes/keys in fields and we map them onto the
normalized model. Idempotent — the same input re-added updates rather than duplicates.
"""

from __future__ import annotations

import hashlib
import urllib.parse
from datetime import date
from pathlib import Path

from pydantic import BaseModel

from vehicle_finder.logging import get_logger
from vehicle_finder.models.enums import SellerType, VehicleType
from vehicle_finder.models.listing import VehicleListing
from vehicle_finder.normalize.equipment import EquipmentNormalizer
from vehicle_finder.normalize.fields import normalize_colour, normalize_fuel, normalize_transmission

log = get_logger("manual")


class ManualListingInput(BaseModel):
    """Hand-entered listing fields. Only ``title`` is required."""

    title: str
    vehicle_type: VehicleType = VehicleType.CAR
    source: str = "manual"
    url: str | None = None
    make: str | None = None
    model: str | None = None
    variant: str | None = None
    model_year: int | None = None
    registration_date: date | None = None
    mileage_km: int | None = None
    price: int | None = None
    currency: str = "EUR"
    seller_type: str | None = None
    seller_name: str | None = None
    location: str | None = None
    country: str | None = None
    power_hp: int | None = None
    power_kw: int | None = None
    displacement_cc: int | None = None
    colour: str | None = None
    fuel_type: str | None = None
    transmission: str | None = None
    body_style: str | None = None
    vin: str | None = None
    kenteken: str | None = None
    warranty: str | None = None
    description: str | None = None
    options: str | None = None  # free-text equipment, normalized to features
    image_urls: list[str] = []


_GENERIC_PATH_TAILS = {"", "details.html", "index.html", "details"}


def _stable_id(data: ManualListingInput) -> str:
    if data.url:
        parts = urllib.parse.urlsplit(data.url)
        query = urllib.parse.parse_qs(parts.query)
        # Many sites carry the listing id in the query (mobile.de ?id=, etc.).
        for key in ("id", "adId", "itemId"):
            if query.get(key):
                return query[key][0]
        tail = parts.path.rstrip("/").rsplit("/", 1)[-1]
        if tail and tail not in _GENERIC_PATH_TAILS:
            return tail
    composite = "|".join(
        str(x) for x in (data.title, data.make, data.model, data.model_year, data.mileage_km)
    )
    return "manual-" + hashlib.sha1(composite.encode("utf-8")).hexdigest()[:12]


def build_manual_listing(data: ManualListingInput) -> VehicleListing:
    """Map hand-entered input onto a normalized listing (pure)."""
    seller_type = SellerType.UNKNOWN
    if data.seller_type:
        try:
            seller_type = SellerType(data.seller_type.lower())
        except ValueError:
            seller_type = SellerType.UNKNOWN

    listing = VehicleListing(
        vehicle_type=data.vehicle_type,
        source=data.source,
        source_listing_id=_stable_id(data),
        url=data.url or "",
        title=data.title,
        make=data.make,
        model=data.model,
        variant=data.variant,
        model_year=data.model_year,
        registration_date=data.registration_date,
        mileage_km=data.mileage_km,
        price=data.price,
        currency=data.currency,
        seller_type=seller_type,
        seller_name=data.seller_name,
        location=data.location,
        country=data.country,
        power_hp=data.power_hp,
        power_kw=data.power_kw,
        displacement_cc=data.displacement_cc,
        colour=normalize_colour(data.colour) or data.colour,
        fuel_type=normalize_fuel(data.fuel_type) if data.fuel_type else None,
        transmission=normalize_transmission(data.transmission) if data.transmission else None,
        body_style=data.body_style,
        vin=data.vin,
        kenteken=data.kenteken,
        warranty=data.warranty,
        description=data.description,
        raw_options_text=data.options or data.description,
        image_urls=data.image_urls,
    )
    text = " ".join(p for p in (data.options, data.description) if p)
    listing.set_features(EquipmentNormalizer().normalize_text(text, source=data.source))
    return listing


def add_manual_listing(data: ManualListingInput) -> VehicleListing:
    """Build and persist a manual listing. Idempotent on its stable id."""
    from vehicle_finder.persistence.db import session_scope
    from vehicle_finder.persistence.repository import upsert_listing

    listing = build_manual_listing(data)
    with session_scope() as session:
        upsert_listing(session, listing)
    log.info("manual_listing_added", source=data.source, title=data.title)
    return listing


def load_manual_input(path: str | Path) -> ManualListingInput:
    return ManualListingInput.model_validate_json(Path(path).read_text(encoding="utf-8"))
