"""Data models. Importing this package registers all SQLModel tables on the metadata."""

from __future__ import annotations

from vehicle_finder.models.enums import (
    Drivetrain,
    FeatureConfidence,
    FuelType,
    ListingStatus,
    SellerType,
    Transmission,
    VehicleType,
)
from vehicle_finder.models.history import PriceObservation, SourceRun
from vehicle_finder.models.listing import VehicleListing, utcnow
from vehicle_finder.models.values import DataQuality, FeatureMatch

__all__ = [
    "DataQuality",
    "Drivetrain",
    "FeatureConfidence",
    "FeatureMatch",
    "FuelType",
    "ListingStatus",
    "PriceObservation",
    "SellerType",
    "SourceRun",
    "Transmission",
    "VehicleListing",
    "VehicleType",
    "utcnow",
]
