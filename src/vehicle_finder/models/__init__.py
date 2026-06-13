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
from vehicle_finder.models.group import MergeDecision, VehicleGroup
from vehicle_finder.models.history import PriceObservation, SourceRun
from vehicle_finder.models.listing import VehicleListing, utcnow
from vehicle_finder.models.userstate import UserVehicleState
from vehicle_finder.models.values import DataQuality, FeatureMatch

__all__ = [
    "DataQuality",
    "Drivetrain",
    "FeatureConfidence",
    "FeatureMatch",
    "FuelType",
    "ListingStatus",
    "MergeDecision",
    "PriceObservation",
    "SellerType",
    "SourceRun",
    "Transmission",
    "UserVehicleState",
    "VehicleGroup",
    "VehicleListing",
    "VehicleType",
    "utcnow",
]
