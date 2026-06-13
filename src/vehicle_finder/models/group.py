"""Consolidated-vehicle group and sticky manual merge decisions."""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from vehicle_finder.models.enums import VehicleType
from vehicle_finder.models.listing import utcnow


class VehicleGroup(SQLModel, table=True):
    """One physical vehicle, consolidating N source listings (members link via group_id).

    Group IDs are stable across refreshes (anchored to the lexicographically smallest
    member key) and deterministic given the same data + manual decisions.
    """

    __tablename__: ClassVar[str] = "vehicle_group"  # pyright: ignore[reportIncompatibleVariableOverride]

    group_id: str = Field(primary_key=True)
    vehicle_type: VehicleType = Field(index=True)
    make: str | None = None
    model: str | None = Field(default=None, index=True)
    model_year: int | None = Field(default=None, index=True)
    member_count: int = 1
    sources: list[str] = Field(default_factory=list, sa_column=Column(JSON))

    canonical_price: int | None = Field(default=None, index=True)
    price_min: int | None = None
    price_max: int | None = None  # spread = price_max - price_min

    country: str | None = None
    distance_km: float | None = None
    score: float | None = Field(default=None, index=True)
    score_breakdown: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    merge_explanation: list[str] = Field(default_factory=list, sa_column=Column(JSON))

    first_seen: datetime = Field(default_factory=utcnow)
    last_seen: datetime = Field(default_factory=utcnow)

    @property
    def price_spread(self) -> int | None:
        if self.price_min is None or self.price_max is None:
            return None
        return self.price_max - self.price_min


class MergeDecision(SQLModel, table=True):
    """A sticky, authoritative manual decision about a pair of listings.

    ``merge`` forces the pair into one group; ``not_duplicate`` forces them apart even
    if the automatic clustering would merge them. Keys are "source:source_listing_id".
    """

    __tablename__: ClassVar[str] = "merge_decision"  # pyright: ignore[reportIncompatibleVariableOverride]

    id: int | None = Field(default=None, primary_key=True)
    key_a: str = Field(index=True)
    key_b: str = Field(index=True)
    decision: str  # "merge" | "not_duplicate"
    reason: str | None = None
    created_at: datetime = Field(default_factory=utcnow)

    @staticmethod
    def pair_key(a: str, b: str) -> tuple[str, str]:
        """Order a pair canonically so (a,b) and (b,a) are the same decision."""
        return (a, b) if a <= b else (b, a)
