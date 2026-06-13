"""Read-side helpers: turn ORM rows into plain dicts for templates.

Conversion happens inside the DB session so templates never touch detached ORM objects.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, desc, select

from vehicle_finder.models.enums import ListingStatus
from vehicle_finder.models.history import PriceObservation
from vehicle_finder.models.listing import VehicleListing


def listing_to_view(listing: VehicleListing) -> dict[str, Any]:
    """Flatten a listing into template-friendly primitives (+ top features)."""
    features = listing.get_features()
    reg = listing.registration_date.isoformat() if listing.registration_date else None
    feature_dicts = [
        {"canonical": f.canonical, "label": f.label, "confidence": f.confidence.value}
        for f in features
    ]
    return {
        "id": listing.id,
        "vehicle_type": listing.vehicle_type.value,
        "source": listing.source,
        "url": listing.url,
        "title": listing.title,
        "make": listing.make,
        "model": listing.model,
        "variant": listing.variant,
        "model_year": listing.model_year,
        "registration_date": reg,
        "mileage_km": listing.mileage_km,
        "price": listing.price,
        "currency": listing.currency,
        "seller_name": listing.seller_name,
        "seller_type": listing.seller_type.value,
        "country": listing.country,
        "distance_km": listing.distance_km,
        "power_hp": listing.power_hp,
        "displacement_cc": listing.displacement_cc,
        "colour": listing.colour,
        "fuel_type": listing.fuel_type.value if listing.fuel_type else None,
        "transmission": listing.transmission.value if listing.transmission else None,
        "body_style": listing.body_style,
        "warranty": listing.warranty,
        "kenteken": listing.kenteken,
        "vin": listing.vin,
        "status": listing.status.value,
        "score": listing.score,
        "score_breakdown": listing.score_breakdown,
        "image": listing.image_urls[0] if listing.image_urls else None,
        "images": listing.image_urls,
        "features": feature_dicts,
        "scored_features": [f.label for f in features if f.is_scored],
        "low_conf_features": [f.label for f in features if not f.is_scored],
        "description": listing.description,
        "data_quality": listing.get_data_quality().warnings,
        "first_seen": listing.first_seen.date().isoformat(),
        "search_id": listing.search_id,
    }


def active_listing_views(session: Session) -> list[dict[str, Any]]:
    rows = session.exec(
        select(VehicleListing).where(VehicleListing.status == ListingStatus.ACTIVE)
    ).all()
    return [listing_to_view(r) for r in rows]


def listing_detail_view(session: Session, listing_id: int) -> dict[str, Any] | None:
    listing = session.get(VehicleListing, listing_id)
    if listing is None:
        return None
    view = listing_to_view(listing)
    history = session.exec(
        select(PriceObservation)
        .where(PriceObservation.listing_id == listing_id)
        .order_by(desc(PriceObservation.observed_at))
    ).all()
    view["price_history"] = [
        {"price": h.price, "currency": h.currency, "observed_at": h.observed_at.date().isoformat()}
        for h in history
    ]
    return view
