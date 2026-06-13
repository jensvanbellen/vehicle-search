"""URL-import tests — offline (parsing + URL cleaning + source routing)."""

from __future__ import annotations

from pathlib import Path

from vehicle_finder.models.enums import FuelType, Transmission, VehicleType
from vehicle_finder.sources.url_import import clean_url, parse_listing_html, source_id_for

FIXTURES = Path(__file__).parent / "fixtures" / "url_import"


def test_clean_url_strips_tracking() -> None:
    dirty = "https://www.marktplaats.nl/v/auto-s/bmw/m2100-bmw-x5?c=123&correlationId=abc&foo=keep"
    cleaned = clean_url(dirty)
    assert "c=123" not in cleaned
    assert "correlationId" not in cleaned
    assert "foo=keep" in cleaned


def test_source_routing() -> None:
    assert source_id_for("www.marktplaats.nl") == "marktplaats"
    assert source_id_for("suchen.mobile.de") == "mobile-de"
    assert source_id_for("example.com").startswith("url:")


def test_parse_marktplaats_jsonld() -> None:
    html = (FIXTURES / "marktplaats_x5.html").read_text(encoding="utf-8")
    url = "https://www.marktplaats.nl/v/auto-s/bmw/m2100000001-bmw-x5-xdrive45e"
    listing = parse_listing_html(html, url, "marktplaats")
    assert listing.source == "marktplaats"
    assert listing.make == "BMW"
    assert listing.model == "X5"
    assert listing.vehicle_type is VehicleType.CAR
    assert listing.price == 64950
    assert listing.mileage_km == 68000
    assert listing.model_year == 2022
    assert listing.colour == "black"
    assert listing.fuel_type is FuelType.PLUGIN_HYBRID
    assert listing.transmission is Transmission.AUTOMATIC
    assert len(listing.image_urls) == 2
    canon = {f.canonical for f in listing.get_features()}
    assert "panoramic_roof" in canon
    assert "head_up_display" in canon
    assert "towbar" in canon


def test_motorcycle_detected_from_url() -> None:
    html = (FIXTURES / "marktplaats_x5.html").read_text(encoding="utf-8")
    url = "https://www.marktplaats.nl/v/motoren/motoren-bmw/m999-bmw-s-1000-xr"
    listing = parse_listing_html(html, url, "marktplaats")
    assert listing.vehicle_type is VehicleType.MOTORCYCLE
