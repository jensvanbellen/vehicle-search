"""Idempotent persistence: upsert listings, track price history, grace-inactivate stale.

Re-running a fetch with identical data is a no-op (no spurious price rows, no churn).
"""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum

from sqlmodel import Session, col, select

from vehicle_finder.logging import get_logger
from vehicle_finder.models.enums import ListingStatus
from vehicle_finder.models.history import PriceObservation
from vehicle_finder.models.listing import VehicleListing, utcnow

log = get_logger("repository")

# Fields copied from a freshly-parsed listing onto the stored row on update.
# Excludes identity/lifecycle/user fields (id, source, source_listing_id, first_seen,
# group_id, and future notes/shortlist).
_SYNC_FIELDS = (
    "url",
    "title",
    "make",
    "model",
    "variant",
    "model_year",
    "registration_date",
    "build_date",
    "mileage_km",
    "price",
    "currency",
    "seller_type",
    "seller_name",
    "location",
    "country",
    "distance_km",
    "displacement_cc",
    "power_kw",
    "power_hp",
    "colour",
    "owners",
    "warranty",
    "service_history",
    "accident_info",
    "vat_status",
    "vin",
    "kenteken",
    "description",
    "raw_options_text",
    "features",
    "image_urls",
    "image_phashes",
    "data_quality",
    "score",
    "score_breakdown",
    "body_style",
    "doors",
    "seats",
    "transmission",
    "drivetrain",
    "fuel_type",
    "battery_kwh",
    "range_km",
    "co2_g_km",
    "bike_category",
    "raw_payload",
    "search_id",
)


class UpsertOutcome(StrEnum):
    NEW = "new"
    PRICE_CHANGED = "price_changed"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


def _find(session: Session, source: str, source_listing_id: str) -> VehicleListing | None:
    stmt = select(VehicleListing).where(
        VehicleListing.source == source,
        VehicleListing.source_listing_id == source_listing_id,
    )
    return session.exec(stmt).first()


def _record_price(session: Session, listing: VehicleListing) -> None:
    assert listing.id is not None
    session.add(
        PriceObservation(
            listing_id=listing.id,
            source=listing.source,
            source_listing_id=listing.source_listing_id,
            price=listing.price,
            currency=listing.currency,
        )
    )


def upsert_listing(session: Session, parsed: VehicleListing) -> UpsertOutcome:
    """Insert or update one parsed listing; record price changes. Idempotent."""
    existing = _find(session, parsed.source, parsed.source_listing_id)
    now = utcnow()

    if existing is None:
        parsed.first_seen = now
        parsed.last_seen = now
        parsed.status = ListingStatus.ACTIVE
        session.add(parsed)
        session.flush()  # assign id
        _record_price(session, parsed)
        return UpsertOutcome.NEW

    price_changed = parsed.price != existing.price and parsed.price is not None
    # Detect a meaningful content change before we overwrite.
    changed = price_changed or any(
        getattr(existing, f) != getattr(parsed, f)
        for f in ("mileage_km", "title", "description", "features", "image_urls", "score")
    )

    for field in _SYNC_FIELDS:
        setattr(existing, field, getattr(parsed, field))
    existing.last_seen = now
    existing.status = ListingStatus.ACTIVE
    session.add(existing)

    if price_changed:
        session.flush()
        _record_price(session, existing)
        return UpsertOutcome.PRICE_CHANGED
    return UpsertOutcome.UPDATED if changed else UpsertOutcome.UNCHANGED


def mark_stale_inactive(session: Session, sources: set[str], grace_hours: float) -> int:
    """Mark ACTIVE listings of the given sources INACTIVE if unseen beyond the grace period.

    Listings refreshed this run have ``last_seen`` ~now, so they are safe. Returns count.
    """
    if not sources:
        return 0
    cutoff = utcnow() - timedelta(hours=grace_hours)
    stmt = select(VehicleListing).where(
        VehicleListing.status == ListingStatus.ACTIVE,
        col(VehicleListing.source).in_(sources),
        col(VehicleListing.last_seen) < cutoff,
    )
    stale = session.exec(stmt).all()
    for listing in stale:
        listing.status = ListingStatus.INACTIVE
        session.add(listing)
    if stale:
        log.info("marked_inactive", count=len(stale), sources=sorted(sources))
    return len(stale)


def count_active_listings(session: Session) -> int:
    stmt = select(VehicleListing).where(VehicleListing.status == ListingStatus.ACTIVE)
    return len(session.exec(stmt).all())
