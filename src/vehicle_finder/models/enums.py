"""Enumerations shared across the data model."""

from __future__ import annotations

from enum import StrEnum


class VehicleType(StrEnum):
    CAR = "car"
    MOTORCYCLE = "motorcycle"


class SellerType(StrEnum):
    DEALER = "dealer"
    PRIVATE = "private"
    UNKNOWN = "unknown"


class ListingStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"  # not seen recently; passed the grace period
    SOLD = "sold"


class FuelType(StrEnum):
    PETROL = "petrol"
    DIESEL = "diesel"
    ELECTRIC = "electric"
    HYBRID = "hybrid"
    PLUGIN_HYBRID = "plugin_hybrid"
    HYDROGEN = "hydrogen"
    OTHER = "other"
    UNKNOWN = "unknown"


class Transmission(StrEnum):
    MANUAL = "manual"
    AUTOMATIC = "automatic"
    UNKNOWN = "unknown"


class Drivetrain(StrEnum):
    FWD = "fwd"
    RWD = "rwd"
    AWD = "awd"
    UNKNOWN = "unknown"


class FeatureConfidence(StrEnum):
    """Confidence that a normalized feature is actually present on the vehicle."""

    HIGH = "high"  # structured field or unambiguous token match
    MEDIUM = "medium"  # alias match in free text
    LOW = "low"  # weak/partial signal — surfaced as "possibly equipped", not scored
