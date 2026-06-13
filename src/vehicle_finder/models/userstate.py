"""Per-vehicle user state: shortlist, rejection, notes. Keyed by stable group_id."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from sqlmodel import Field, SQLModel

from vehicle_finder.models.listing import utcnow


class UserVehicleState(SQLModel, table=True):
    """Sticky personal state for a consolidated vehicle (survives refreshes via group_id)."""

    __tablename__: ClassVar[str] = "user_vehicle_state"  # pyright: ignore[reportIncompatibleVariableOverride]

    group_id: str = Field(primary_key=True)
    shortlisted: bool = Field(default=False, index=True)
    rejected: bool = Field(default=False, index=True)
    reject_reason: str | None = None
    notes: str | None = None
    updated_at: datetime = Field(default_factory=utcnow)
