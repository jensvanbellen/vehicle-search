"""Parser tests for the BMW NL adapter — fixtures only, no live HTTP."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from vehicle_finder.models.enums import FuelType, SellerType, Transmission, VehicleType
from vehicle_finder.models.listing import VehicleListing
from vehicle_finder.sources.bmw_nl import parse_response, parse_vehicle

Loader = Callable[..., dict[str, Any]]
ParseOut = tuple[list[VehicleListing], int, int, list[str], bool]


def _parse_cars(data: dict[str, Any]) -> ParseOut:
    return parse_response(
        data,
        source_id="bmw-nl",
        vehicle_type=VehicleType.CAR,
        base_url="https://occasions.bmw.nl",
        details_uri="/bmw/zoeken/resultaten/details",
        search_id="x5-g05",
    )


def _parse_bikes(data: dict[str, Any]) -> ParseOut:
    return parse_response(
        data,
        source_id="bmw-motorrad-nl",
        vehicle_type=VehicleType.MOTORCYCLE,
        base_url="https://occasions.bmw-motorrad.nl",
        details_uri="/motorrad/zoeken/resultaten/details",
        search_id="s1000xr-2024",
    )


def test_parse_cars_fixture(fixture: Loader) -> None:
    listings, found, failures, warnings, layout = _parse_cars(
        fixture("bmw_nl", "x5_cars_page1.json")
    )
    assert found == 5
    assert len(listings) == 5
    assert failures == 0
    assert layout is False
    assert warnings == []

    first = listings[0]
    assert first.make == "BMW"
    assert first.model == "X5"
    assert first.vehicle_type is VehicleType.CAR
    assert first.seller_type is SellerType.DEALER
    assert first.country == "NL"
    assert first.fuel_type is FuelType.PLUGIN_HYBRID
    assert first.transmission is Transmission.AUTOMATIC
    assert first.url.endswith(f"/id/{first.source_listing_id}")
    assert first.price and first.price > 0
    assert first.registration_date is not None
    assert first.kenteken  # BMW NL exposes the plate (decisive for dedup)


def test_equipment_detected_from_description(fixture: Loader) -> None:
    listings, *_ = _parse_cars(fixture("bmw_nl", "x5_cars_page1.json"))
    # The 2nd fixture car's description lists Panodak / Head-Up / Trekhaak / Harman.
    canon = {f.canonical for f in listings[1].get_features()}
    assert "head_up_display" in canon
    assert "towbar" in canon
    assert "harman_kardon" in canon


def test_edge_case_missing_fields_flagged(fixture: Loader) -> None:
    listings, *_ = _parse_cars(fixture("bmw_nl", "x5_cars_page1.json"))
    edge = next(x for x in listings if x.source_listing_id == "999000001")
    assert edge.price is None
    assert edge.mileage_km is None
    warnings = edge.get_data_quality().warnings
    assert "price missing" in warnings
    assert "mileage missing" in warnings


def test_parse_bikes_displacement_normalized(fixture: Loader) -> None:
    listings, found, failures, _warnings, layout = _parse_bikes(
        fixture("bmw_nl", "s1000xr_bikes_page1.json")
    )
    assert found == 3
    assert failures == 0
    assert layout is False
    bike = next(x for x in listings if x.displacement_cc)
    # 99900 (x100 source encoding) must normalize to ~999 cc, with a data-quality note.
    assert bike.displacement_cc == 999
    assert any("displacement" in w for w in bike.get_data_quality().warnings)
    assert bike.body_style is None  # bikes have no body style
    assert bike.bike_category  # serie recorded as category


def test_unparseable_vehicle_counts_as_failure() -> None:
    listing = parse_vehicle(
        {"name": "no id"},  # missing vehicleId
        source_id="bmw-nl",
        vehicle_type=VehicleType.CAR,
        base_url="https://occasions.bmw.nl",
        details_uri="/bmw/zoeken/resultaten/details",
    )
    assert listing is None


def test_layout_change_on_unexpected_structure() -> None:
    listings, found, _failures, _warnings, layout = _parse_cars({"unexpected": True})
    assert listings == []
    assert found == 0
    assert layout is True
