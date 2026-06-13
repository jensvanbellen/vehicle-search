"""dasimport HTML parser tests — fixtures only, no live HTTP."""

from __future__ import annotations

from pathlib import Path

from vehicle_finder.models.enums import FuelType, SellerType, VehicleType
from vehicle_finder.sources.dasimport import parse_html

FIXTURES = Path(__file__).parent / "fixtures" / "dasimport"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_cards() -> None:
    listings, found, failures, warnings, layout = parse_html(
        _read("x5_aanbod_page1.html"), "https://www.dasimport.nl", "x5-g05"
    )
    assert found == 3
    assert len(listings) == 3
    assert failures == 0
    assert layout is False
    assert warnings == []

    first = listings[0]
    assert first.source == "dasimport"
    assert first.make == "BMW"
    assert first.model == "X5"
    assert first.vehicle_type is VehicleType.CAR
    assert first.seller_type is SellerType.DEALER
    assert first.price and first.price > 0
    assert first.mileage_km and first.mileage_km > 0
    assert first.model_year in (2021, 2022, 2023)
    assert first.fuel_type is FuelType.PLUGIN_HYBRID
    assert first.source_listing_id.isdigit()
    assert "importeren-" in first.url
    # Prices are NL-landed; country stays NL so no German-import penalty is applied.
    assert first.country == "NL"
    assert first.vat_status == "nl_landed_incl_bpm"


def test_equipment_from_title() -> None:
    listings, *_ = parse_html(_read("x5_aanbod_page1.html"), "https://www.dasimport.nl", "x5-g05")
    # The 2nd card's title contains "Leder" -> leather feature.
    with_leather = [x for x in listings if any(f.canonical == "leather" for f in x.get_features())]
    assert with_leather


def test_empty_page_no_layout_flag() -> None:
    listings, found, failures, _warnings, layout = parse_html(
        _read("empty_aanbod.html"), "https://www.dasimport.nl", "x5-g05"
    )
    assert listings == []
    assert found == 0
    assert failures == 0
    assert layout is False  # genuinely empty, not a layout change
