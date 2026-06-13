"""Manual-entry tests — offline."""

from __future__ import annotations

from vehicle_finder.models.enums import FuelType, SellerType, Transmission, VehicleType
from vehicle_finder.sources.manual import ManualListingInput, build_manual_listing


def test_build_manual_listing_maps_fields() -> None:
    data = ManualListingInput(
        title="BMW S 1000 XR M-package",
        vehicle_type=VehicleType.MOTORCYCLE,
        source="mobile-de",
        make="BMW",
        model="S 1000 XR",
        model_year=2024,
        mileage_km=3500,
        price=21900,
        country="DE",
        seller_type="dealer",
        colour="zwart",
        fuel_type="Benzine",
        transmission="Handgeschakeld",
        options="M Paket, Dynamic ESA, Heizgriffe",
    )
    listing = build_manual_listing(data)
    assert listing.vehicle_type is VehicleType.MOTORCYCLE
    assert listing.source == "mobile-de"
    assert listing.seller_type is SellerType.DEALER
    assert listing.colour == "black"
    assert listing.fuel_type is FuelType.PETROL
    assert listing.transmission is Transmission.MANUAL
    canon = {f.canonical for f in listing.get_features()}
    assert "m_package" in canon
    assert "dynamic_esa" in canon
    assert "heated_grips" in canon


def test_stable_id_is_deterministic() -> None:
    data = ManualListingInput(
        title="BMW X5", make="BMW", model="X5", model_year=2022, mileage_km=50000
    )
    a = build_manual_listing(data)
    b = build_manual_listing(data)
    assert a.source_listing_id == b.source_listing_id  # idempotent re-entry
    assert a.source_listing_id.startswith("manual-")


def test_url_derived_id() -> None:
    data = ManualListingInput(title="BMW X5", url="https://www.example.com/listing/xyz-987")
    listing = build_manual_listing(data)
    assert listing.source_listing_id == "xyz-987"


def test_query_param_id_preferred() -> None:
    # mobile.de keeps the id in the query, and the path tail is generic ("details.html").
    data = ManualListingInput(
        title="BMW X5",
        url="https://suchen.mobile.de/fahrzeuge/details.html?id=444354628&action=parkItem",
    )
    listing = build_manual_listing(data)
    assert listing.source_listing_id == "444354628"
