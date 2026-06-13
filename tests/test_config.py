"""Config-level behaviour tests."""

from __future__ import annotations

from typing import Any

from vehicle_finder.configio import SearchTarget
from vehicle_finder.models.enums import VehicleType


def _target(**kw: Any) -> SearchTarget:
    return SearchTarget(id="t", vehicle_type=VehicleType.CAR, make="BMW", model="X5", **kw)


def test_variant_includes_keeps_only_matching() -> None:
    t = _target(variant_includes=["30d", "40d"])
    assert t.variant_allowed("xDrive30d") is True
    assert t.variant_allowed("BMW X5 xDrive 40 d M Sport") is True  # space-insensitive
    assert t.variant_allowed("xDrive45e") is False  # PHEV excluded
    assert t.variant_allowed("xDrive40i") is False  # petrol excluded


def test_variant_excludes_drops_matching() -> None:
    t = _target(variant_excludes=["45e", "m60"])
    assert t.variant_allowed("xDrive30d") is True
    assert t.variant_allowed("X5 xDrive45e") is False
    assert t.variant_allowed("X5 M60i") is False


def test_no_filter_allows_everything() -> None:
    t = _target()
    assert t.variant_allowed("anything at all") is True
