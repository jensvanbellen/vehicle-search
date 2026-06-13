"""Explainable scoring tests."""

from __future__ import annotations

from vehicle_finder.configio import SearchTarget
from vehicle_finder.models.enums import FeatureConfidence, SellerType, VehicleType
from vehicle_finder.models.listing import VehicleListing
from vehicle_finder.models.values import FeatureMatch
from vehicle_finder.scoring.scorer import Scorer


def _car(lid: str, price: int, mileage: int, year: int, features: list[str]) -> VehicleListing:
    listing = VehicleListing(
        vehicle_type=VehicleType.CAR,
        source="bmw-nl",
        source_listing_id=lid,
        url=f"https://x/{lid}",
        title="BMW X5",
        make="BMW",
        model="X5",
        model_year=year,
        mileage_km=mileage,
        price=price,
        country="NL",
        seller_type=SellerType.DEALER,
        warranty="BMW Premium Selection",
        description="desc",
        image_urls=["https://x/img.jpg"],
    )
    listing.set_features(
        [FeatureMatch(canonical=c, label=c, confidence=FeatureConfidence.HIGH) for c in features]
    )
    return listing


TARGET = SearchTarget(
    id="x5-g05",
    vehicle_type=VehicleType.CAR,
    make="BMW",
    model="X5",
    required_equipment=["panoramic_roof"],
    preferred_equipment=["four_wheel_steering", "surround_view_camera", "head_up_display"],
)


def test_total_equals_sum_of_lines() -> None:
    listings = [_car("a", 50000, 100000, 2021, ["panoramic_roof"])]
    result = Scorer().compute_scores(listings, TARGET, reference_year=2026)[0]
    assert result.total == round(sum(line.points for line in result.lines), 1)


def test_more_equipment_scores_higher() -> None:
    rich = _car(
        "rich", 50000, 100000, 2021, ["panoramic_roof", "four_wheel_steering", "head_up_display"]
    )
    bare = _car("bare", 50000, 100000, 2021, ["panoramic_roof"])
    results = Scorer().compute_scores([rich, bare], TARGET, reference_year=2026)
    assert results[0].total > results[1].total


def test_required_equipment_missing_penalised() -> None:
    missing = _car("m", 50000, 100000, 2021, [])  # lacks required panoramic_roof
    result = Scorer().compute_scores([missing], TARGET, reference_year=2026)[0]
    assert any(line.points < 0 and "Missing required" in line.label for line in result.lines)


def test_accident_history_is_penalised() -> None:
    damaged = _car("damaged", 50000, 100000, 2021, ["panoramic_roof"])
    damaged.accident_info = "Accident history reported"
    result = Scorer().compute_scores([damaged], TARGET, reference_year=2026)[0]
    assert any(
        line.points < 0 and "Accident/damage history" in line.label for line in result.lines
    )


def test_rare_option_shows_frequency() -> None:
    # 1 of 4 listings has four_wheel_steering => "on 25% of matches".
    listings = [
        _car("a", 50000, 100000, 2021, ["panoramic_roof", "four_wheel_steering"]),
        _car("b", 50000, 100000, 2021, ["panoramic_roof"]),
        _car("c", 50000, 100000, 2021, ["panoramic_roof"]),
        _car("d", 50000, 100000, 2021, ["panoramic_roof"]),
    ]
    result = Scorer().compute_scores(listings, TARGET, reference_year=2026)[0]
    rare_lines = [line for line in result.lines if "of matches" in line.label]
    assert rare_lines, "rare-option line should report frequency"
    assert "25% of matches" in rare_lines[0].label


def test_sporty_spec_is_penalised() -> None:
    sporty = _car("sporty", 50000, 100000, 2021, ["panoramic_roof"])
    sporty.raw_options_text = "M Aerodynamikpaket, 22 inch velgen, Shadow Line hochglanz"
    plain = _car("plain", 50000, 100000, 2021, ["panoramic_roof"])
    results = Scorer().compute_scores([sporty, plain], TARGET, reference_year=2026)
    sporty_penalties = [
        line for line in results[0].lines if line.points < 0 and "wheel" in line.label.lower()
    ]
    assert sporty_penalties  # large-wheels penalty fired
    assert any("Shadow Line" in line.label for line in results[0].lines)
    # Same equipment, but the sporty car scores lower thanks to the character penalties.
    assert results[0].total < results[1].total


def test_cheaper_listing_gets_price_bonus() -> None:
    cheap = _car("cheap", 40000, 100000, 2021, ["panoramic_roof"])
    dear = _car("dear", 60000, 100000, 2021, ["panoramic_roof"])
    results = Scorer().compute_scores([cheap, dear], TARGET, reference_year=2026)
    cheap_price_line = next(line for line in results[0].lines if "Price" in line.label)
    assert cheap_price_line.points > 0  # below median
