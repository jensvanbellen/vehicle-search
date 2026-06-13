"""bmw.de adapter tests — filter encoding, offers parsing, challenge detection.

All offline: the filter encoder is verified against the documented live format, the
parser runs on a representative fixture, and challenge detection is a pure string check.
Live Playwright transport is verified separately on an NL network.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from vehicle_finder.models.enums import FuelType, SellerType, Transmission, VehicleType
from vehicle_finder.sources.bmw_de import (
    build_filter_param,
    build_results_url,
    looks_like_challenge,
    parse_offers,
    with_start_index,
)

Loader = Callable[..., dict[str, Any]]

# The exact double-URL-encoded filter from the documented live bmw.de example URL.
DOCUMENTED_FILTER = (
    "%257B%2522MARKETING_MODEL_RANGE%2522%253A%255B%2522X5_G05%2522%255D%252C"
    "%2522IS_INSTALLMENT%2522%253Afalse%252C%2522REGISTRATION_YEAR%2522%253A"
    "%255B2021%252C2023%255D%257D"
)


def test_filter_param_matches_documented_format() -> None:
    assert build_filter_param("X5_G05", 2021, 2023) == DOCUMENTED_FILTER


def test_filter_param_includes_engine_and_mileage() -> None:
    param = build_filter_param(
        "X5_G05",
        2021,
        2023,
        engine_type="DIESEL",
        max_mileage=80000,
        equipment_groups={"drivingAssistance": ["Adaptive 2-Achs-Luftfederung"]},
    )
    assert "%2522ENGINE_TYPE%2522%253A%255B%2522DIESEL%2522%255D" in param
    assert "%2522USED_CAR_MILEAGE%2522%253A%255B0%252C80000%255D" in param
    assert "Adaptive%25202-Achs-Luftfederung" in param


def test_results_url_built() -> None:
    url = build_results_url("https://www.bmw.de", "/de-de/sl/gebrauchtwagen/results", "ABC")
    assert url.startswith("https://www.bmw.de/de-de/sl/gebrauchtwagen/results?filters=ABC")


def test_pagination_url_replaces_start_index() -> None:
    url = "https://stolo.example/search?maxResults=12&startIndex=0&brand=BMW"
    assert with_start_index(url, 24).endswith("maxResults=12&startIndex=24&brand=BMW")


def test_parse_offers_fixture(fixture: Loader) -> None:
    data = fixture("bmw_de", "offers.json")
    listings, found, failures, _warnings, layout = parse_offers(
        data, "https://www.bmw.de", "x5-g05"
    )
    assert found == 2
    assert len(listings) == 2
    assert failures == 0
    assert layout is False

    first = next(x for x in listings if x.source_listing_id == "DE-1001")
    assert first.source == "bmw-de"
    assert first.make == "BMW"
    assert first.country == "DE"  # physically in Germany -> import-cost module applies
    assert first.seller_type is SellerType.DEALER
    assert first.price == 61900  # extracted from nested {amount}
    assert first.mileage_km == 42000
    assert first.model_year == 2022
    assert first.power_hp == 394
    assert first.fuel_type is FuelType.PLUGIN_HYBRID
    assert first.transmission is Transmission.AUTOMATIC
    assert first.colour == "black"
    assert len(first.image_urls) == 2
    assert first.vehicle_type is VehicleType.CAR


def test_parse_offers_equipment_from_description(fixture: Loader) -> None:
    data = fixture("bmw_de", "offers.json")
    listings, *_ = parse_offers(data, "https://www.bmw.de", "x5-g05")
    first = next(x for x in listings if x.source_listing_id == "DE-1001")
    canon = {f.canonical for f in first.get_features()}
    assert "head_up_display" in canon
    assert "towbar" in canon
    assert "harman_kardon" in canon


def test_parse_offers_edge_case_missing_fields(fixture: Loader) -> None:
    data = fixture("bmw_de", "offers.json")
    listings, *_ = parse_offers(data, "https://www.bmw.de", "x5-g05")
    edge = next(x for x in listings if x.source_listing_id == "DE-1002")
    assert edge.price is None
    assert edge.mileage_km is None
    assert "price missing" in edge.get_data_quality().warnings


def test_parse_stolo_vehicle_payload(fixture: Loader) -> None:
    data = fixture("bmw_de", "stolo_hits.json")
    listings, found, failures, _warnings, layout = parse_offers(
        data, "https://www.bmw.de", "x5-g05"
    )

    assert found == 1
    assert failures == 0
    assert layout is False

    listing = listings[0]
    assert listing.source_listing_id == "018e933c-75c4-73fa-8190-f387c4c683b6"
    assert listing.url.startswith("https://www.bmw.de/de-de/sl/gebrauchtwagen/details/")
    assert "modelCode=JU81" in listing.url
    assert listing.title == "BMW X5 xDrive30d"
    assert listing.model == "X5"
    assert listing.variant == "X5 30D"
    assert listing.price == 65890
    assert listing.mileage_km == 41855
    assert listing.model_year == 2021
    assert listing.build_date is not None
    assert listing.fuel_type is FuelType.DIESEL
    assert listing.transmission is Transmission.AUTOMATIC
    assert listing.power_hp == 286
    assert listing.power_kw == 210
    assert listing.displacement_cc == 2993
    assert listing.owners == 1
    assert listing.warranty == "BMW Premium Selection (24 months)"
    assert listing.vat_status == "vat_deductible"
    assert listing.accident_info is not None
    assert "Heckklappe" in listing.accident_info
    assert "accident/damage history reported" in listing.get_data_quality().warnings


def test_parse_stolo_structured_equipment(fixture: Loader) -> None:
    data = fixture("bmw_de", "stolo_hits.json")
    listings, *_ = parse_offers(data, "https://www.bmw.de", "x5-g05")
    canon = {f.canonical for f in listings[0].get_features()}

    assert "driving_assistant_professional" in canon
    assert "surround_view_camera" in canon
    assert "air_suspension" in canon
    assert "comfort_seats" in canon
    assert "seat_ventilation" in canon
    assert "panoramic_roof" in canon
    assert "head_up_display" in canon
    assert "towbar" in canon
    assert "harman_kardon" in canon


def test_unknown_payload_flags_layout_change() -> None:
    listings, found, _failures, _warnings, layout = parse_offers({"nope": 1}, "https://www.bmw.de")
    assert listings == []
    assert found == 0
    assert layout is True


def test_challenge_detection() -> None:
    assert looks_like_challenge("Just a moment...", "<html>checking your browser</html>") is True
    assert looks_like_challenge("Pardon Our Interruption", "<html></html>") is True
    assert looks_like_challenge("BMW X5 Gebrauchtwagen", "<html>results here</html>") is False
