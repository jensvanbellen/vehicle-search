"""Price history and per-source run audit tables."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from vehicle_finder.models.listing import utcnow


class PriceObservation(SQLModel, table=True):
    """A point in a listing's price timeline. One row per observed change."""

    __tablename__: ClassVar[str] = "price_observation"  # pyright: ignore[reportIncompatibleVariableOverride]

    id: int | None = Field(default=None, primary_key=True)
    listing_id: int = Field(index=True, foreign_key="listing.id")
    source: str = Field(index=True)
    source_listing_id: str = Field(index=True)
    price: int | None = None
    currency: str = "EUR"
    observed_at: datetime = Field(default_factory=utcnow, index=True)


class SourceRun(SQLModel, table=True):
    """Audit row for one source fetch within a run (powers diagnostics)."""

    __tablename__: ClassVar[str] = "source_run"  # pyright: ignore[reportIncompatibleVariableOverride]

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    search_id: str | None = Field(default=None, index=True)
    started_at: datetime = Field(default_factory=utcnow, index=True)
    finished_at: datetime | None = None
    succeeded: bool = False
    found: int = 0
    parsed: int = 0
    parse_failures: int = 0
    layout_changed: bool = False
    error: str | None = None
    warnings: list[str] = Field(default_factory=list, sa_column=Column(JSON))
