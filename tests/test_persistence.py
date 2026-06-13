"""Persistence: idempotent upsert, price history, grace-period inactivation."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import Engine
from sqlmodel import Session, select

from vehicle_finder.models.enums import ListingStatus, SellerType, VehicleType
from vehicle_finder.models.history import PriceObservation
from vehicle_finder.models.listing import VehicleListing, utcnow
from vehicle_finder.persistence.repository import (
    UpsertOutcome,
    mark_stale_inactive,
    upsert_listing,
)


def _listing(price: int, lid: str = "100") -> VehicleListing:
    return VehicleListing(
        vehicle_type=VehicleType.CAR,
        source="bmw-nl",
        source_listing_id=lid,
        url="https://x/100",
        title="BMW X5",
        make="BMW",
        model="X5",
        price=price,
        mileage_km=50000,
        seller_type=SellerType.DEALER,
    )


def test_new_then_idempotent(session: Session) -> None:
    assert upsert_listing(session, _listing(50000)) is UpsertOutcome.NEW
    session.commit()
    # Re-upserting identical data must be a no-op (idempotent pipeline).
    assert upsert_listing(session, _listing(50000)) is UpsertOutcome.UNCHANGED
    session.commit()
    assert len(session.exec(select(VehicleListing)).all()) == 1
    assert len(session.exec(select(PriceObservation)).all()) == 1


def test_price_change_records_history(session: Session) -> None:
    upsert_listing(session, _listing(50000))
    session.commit()
    assert upsert_listing(session, _listing(48000)) is UpsertOutcome.PRICE_CHANGED
    session.commit()
    obs = session.exec(select(PriceObservation)).all()
    assert len(obs) == 2
    assert {o.price for o in obs} == {50000, 48000}


def test_first_seen_preserved_on_update(session: Session) -> None:
    upsert_listing(session, _listing(50000))
    session.commit()
    original = session.exec(select(VehicleListing)).one()
    first_seen = original.first_seen
    upsert_listing(session, _listing(47000))
    session.commit()
    updated = session.exec(select(VehicleListing)).one()
    assert updated.first_seen == first_seen  # provenance preserved
    assert updated.price == 47000


def test_grace_period_inactivation(engine: Engine, session: Session) -> None:
    upsert_listing(session, _listing(50000, "stale"))
    upsert_listing(session, _listing(60000, "fresh"))
    session.commit()
    # Age the "stale" listing beyond the grace window.
    stale = session.exec(
        select(VehicleListing).where(VehicleListing.source_listing_id == "stale")
    ).one()
    stale.last_seen = utcnow() - timedelta(hours=72)
    session.add(stale)
    session.commit()

    n = mark_stale_inactive(session, {"bmw-nl"}, grace_hours=48)
    session.commit()
    assert n == 1
    statuses = {x.source_listing_id: x.status for x in session.exec(select(VehicleListing)).all()}
    assert statuses["stale"] is ListingStatus.INACTIVE
    assert statuses["fresh"] is ListingStatus.ACTIVE
