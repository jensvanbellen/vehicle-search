"""Unit tests for field-level normalizers."""

from __future__ import annotations

from datetime import date

import pytest

from vehicle_finder.models.enums import FuelType, Transmission
from vehicle_finder.normalize.fields import (
    normalize_colour,
    normalize_fuel,
    normalize_transmission,
    parse_int,
    parse_iso_date,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("48895", 48895),
        ("107.470 km", 107470),
        ("107 470", 107470),  # includes a non-breaking space
        ("€ 22.900,-", 22900),
        ("", None),
        (None, None),
        (2998, 2998),
    ],
)
def test_parse_int(raw: object, expected: int | None) -> None:
    assert parse_int(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2021-03-09", date(2021, 3, 9)),
        ("2022-01", date(2022, 1, 1)),
        ("2020", date(2020, 1, 1)),
        ("", None),
        (None, None),
        ("garbage", None),
    ],
)
def test_parse_iso_date(raw: object, expected: date | None) -> None:
    assert parse_iso_date(raw) == expected


def test_normalize_fuel_multilingual() -> None:
    assert normalize_fuel("Benzine") is FuelType.PETROL
    assert normalize_fuel("Benzin") is FuelType.PETROL
    assert normalize_fuel("Plug-in Hybride") is FuelType.PLUGIN_HYBRID
    assert normalize_fuel("Elektrisch") is FuelType.ELECTRIC
    assert normalize_fuel("") is FuelType.UNKNOWN
    assert normalize_fuel("Kerosene") is FuelType.OTHER


def test_normalize_transmission() -> None:
    assert normalize_transmission("Automaat") is Transmission.AUTOMATIC
    assert normalize_transmission("Handgeschakeld") is Transmission.MANUAL
    assert normalize_transmission("Schaltgetriebe") is Transmission.MANUAL
    assert normalize_transmission(None) is Transmission.UNKNOWN


def test_normalize_colour() -> None:
    assert normalize_colour("zwart") == "black"
    assert normalize_colour("Schwarz") == "black"
    assert normalize_colour("wit metallic") == "white"  # first token wins
    assert normalize_colour("onbekend") is None
    assert normalize_colour(None) is None
