"""Offline distance tests."""

from __future__ import annotations

from vehicle_finder.distance import distance_from_home_km, haversine_km


def test_haversine_known_distance() -> None:
    # The Hague -> Maastricht is ~160 km straight-line.
    km = haversine_km((52.043, 4.358), (50.8514, 5.6910))
    assert 150 < km < 175


def test_distance_from_dealer_city_name() -> None:
    # Dealer name contains a known city -> resolves to its centroid.
    km = distance_from_home_km(
        seller_name="Ekris Maastricht", country="NL", home_postcode="2512 AB"
    )
    assert km is not None and 150 < km < 175


def test_distance_from_postcode() -> None:
    km = distance_from_home_km(postcode="3011 AB", location="Rotterdam", home_postcode="2512 AB")
    assert km is not None and km < 40  # Rotterdam is close to The Hague


def test_distance_unknown_returns_none() -> None:
    assert distance_from_home_km(seller_name="Mystery Garage XYZ", home_postcode="2512 AB") is None


def test_german_city_resolves() -> None:
    km = distance_from_home_km(seller_name="BMW Köln", country="DE", home_postcode="2512 AB")
    assert km is not None and 180 < km < 250
