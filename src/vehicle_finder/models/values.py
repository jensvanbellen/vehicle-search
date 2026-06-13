"""Value objects embedded in listings (stored as JSON)."""

from __future__ import annotations

from pydantic import BaseModel

from vehicle_finder.models.enums import FeatureConfidence


class FeatureMatch(BaseModel):
    """A normalized equipment/feature detected on a listing, with provenance."""

    canonical: str  # canonical feature key, e.g. "heated_grips"
    label: str  # human-readable label
    confidence: FeatureConfidence = FeatureConfidence.MEDIUM
    source_text: str | None = None  # the raw text that matched (provenance)
    source: str | None = None  # which source asserted it (for merged groups)

    @property
    def is_scored(self) -> bool:
        """Only high/medium-confidence features count toward scoring."""
        return self.confidence in (FeatureConfidence.HIGH, FeatureConfidence.MEDIUM)


class DataQuality(BaseModel):
    """Per-listing data-quality / confidence indicators."""

    warnings: list[str] = []  # e.g. "mileage missing", "year/registration mismatch"

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)
