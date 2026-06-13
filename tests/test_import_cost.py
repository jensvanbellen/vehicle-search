"""German import-cost estimate tests (uses config/import_costs.yaml placeholders)."""

from __future__ import annotations

from vehicle_finder.models.enums import SellerType, VehicleType
from vehicle_finder.models.listing import VehicleListing
from vehicle_finder.scoring.import_cost import estimate_import_cost


def _car(country: str, price: int | None, model: str = "X5") -> VehicleListing:
    return VehicleListing(
        vehicle_type=VehicleType.CAR,
        source="bmw-de",
        source_listing_id="1",
        url="https://x/1",
        title=f"BMW {model}",
        make="BMW",
        model=model,
        price=price,
        country=country,
        seller_type=SellerType.DEALER,
    )


def test_de_car_estimate() -> None:
    est = estimate_import_cost(_car("DE", 60000))
    assert est is not None
    assert est.added_total > 0
    assert est.all_in_price == 60000 + est.added_total
    assert any("BPM" in label for label, _amount in est.line_items)
    assert est.disclaimer  # always labelled as an estimate


def test_nl_car_not_estimated() -> None:
    assert estimate_import_cost(_car("NL", 60000)) is None


def test_de_motorcycle_no_bpm() -> None:
    bike = VehicleListing(
        vehicle_type=VehicleType.MOTORCYCLE,
        source="bmw-de",
        source_listing_id="2",
        url="https://x/2",
        title="BMW S 1000 XR",
        make="BMW",
        model="S 1000 XR",
        price=20000,
        country="DE",
        seller_type=SellerType.DEALER,
    )
    est = estimate_import_cost(bike)
    assert est is not None
    assert not any("BPM" in label for label, _amount in est.line_items)  # motorcycle_bpm = 0
