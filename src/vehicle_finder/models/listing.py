"""The central normalized listing model.

A single flat table with a ``vehicle_type`` discriminator and **nullable**
type-specific fields, chosen (over a strict discriminated union) so partial scrapes
always persist. JSON-backed columns hold lists/dicts (features, images, raw payload).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, ClassVar

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from vehicle_finder.models.enums import (
    Drivetrain,
    FuelType,
    ListingStatus,
    SellerType,
    Transmission,
    VehicleType,
)
from vehicle_finder.models.values import DataQuality, FeatureMatch


def utcnow() -> datetime:
    return datetime.now(UTC)


class VehicleListing(SQLModel, table=True):
    """One marketplace listing, normalized. Unique per (source, source_listing_id)."""

    __tablename__: ClassVar[str] = "listing"  # pyright: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (UniqueConstraint("source", "source_listing_id", name="uq_source_listing"),)

    id: int | None = Field(default=None, primary_key=True)

    # --- Identity / provenance ---
    vehicle_type: VehicleType = Field(index=True)
    source: str = Field(index=True)  # e.g. "bmw-nl"
    source_listing_id: str = Field(index=True)
    url: str

    # --- Core descriptive ---
    title: str
    make: str | None = Field(default=None, index=True)
    model: str | None = Field(default=None, index=True)
    variant: str | None = None  # generation / trim, when identifiable
    model_year: int | None = Field(default=None, index=True)
    registration_date: date | None = None

    # --- Condition / commercials ---
    mileage_km: int | None = Field(default=None, index=True)
    price: int | None = Field(default=None, index=True)  # integer currency units
    currency: str = "EUR"
    seller_type: SellerType = SellerType.UNKNOWN
    seller_name: str | None = None
    location: str | None = None
    country: str | None = Field(default=None, index=True)  # "NL" / "DE"
    distance_km: float | None = None  # straight-line from home postcode

    # --- Mechanical (shared) ---
    displacement_cc: int | None = None
    power_kw: int | None = None
    power_hp: int | None = None
    colour: str | None = None

    # --- History / trust ---
    owners: int | None = None
    warranty: str | None = None
    service_history: str | None = None
    accident_info: str | None = None
    vat_status: str | None = None  # e.g. "margin" / "vat_deductible"
    vin: str | None = Field(default=None, index=True)
    kenteken: str | None = Field(default=None, index=True)  # NL licence plate

    # --- Text ---
    description: str | None = None
    raw_options_text: str | None = None

    # --- JSON-backed ---
    features: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    image_urls: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    image_phashes: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    data_quality: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    raw_payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    score_breakdown: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))

    # --- Car-specific (nullable) ---
    body_style: str | None = None
    doors: int | None = None
    seats: int | None = None
    transmission: Transmission | None = None
    drivetrain: Drivetrain | None = None
    fuel_type: FuelType | None = None
    battery_kwh: float | None = None
    range_km: int | None = None
    co2_g_km: int | None = None

    # --- Motorcycle-specific (nullable) ---
    bike_category: str | None = None  # sport / tourer / roadster / modern-classic

    # --- Lifecycle / scoring ---
    first_seen: datetime = Field(default_factory=utcnow)
    last_seen: datetime = Field(default_factory=utcnow)
    status: ListingStatus = Field(default=ListingStatus.ACTIVE, index=True)
    group_id: str | None = Field(default=None, index=True)  # set by merging (milestone 6)
    score: float | None = Field(default=None, index=True)
    search_id: str | None = Field(default=None, index=True)  # which configured search found it

    # ------------------------------------------------------------------ helpers
    def get_features(self) -> list[FeatureMatch]:
        return [FeatureMatch.model_validate(f) for f in self.features]

    def set_features(self, matches: list[FeatureMatch]) -> None:
        self.features = [m.model_dump(mode="json") for m in matches]

    def get_data_quality(self) -> DataQuality:
        return DataQuality.model_validate(self.data_quality) if self.data_quality else DataQuality()

    def set_data_quality(self, dq: DataQuality) -> None:
        self.data_quality = dq.model_dump(mode="json")
