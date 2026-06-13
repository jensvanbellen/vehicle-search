"""Explainable scoring. Every component is a labelled line; the total is their sum.

Weights come from ``config/scoring/weights.yaml`` (per vehicle type); rare-option points
come from ``config/scoring/features.yaml``. Scoring runs over a *set* of comparables
(same search) so price/mileage are market-relative and ``rarity: auto`` boosts reflect
how rare a feature is in the current result set.
"""

from __future__ import annotations

import functools
import re
import statistics
from dataclasses import dataclass
from datetime import date
from typing import Any, cast

from vehicle_finder.configio import SearchTarget, load_yaml_mapping
from vehicle_finder.models.enums import VehicleType
from vehicle_finder.models.listing import VehicleListing
from vehicle_finder.normalize.equipment import FeatureCatalog, get_catalog


@functools.lru_cache(maxsize=1)
def _penalty_patterns() -> list[tuple[re.Pattern[str], str, float]]:
    """Compiled (pattern, label, points) for aesthetic/character penalties (config-driven)."""
    raw = load_yaml_mapping("scoring/penalties.yaml").get("penalties")
    out: list[tuple[re.Pattern[str], str, float]] = []
    if not isinstance(raw, dict):
        return out
    for key, entry in cast("dict[str, Any]", raw).items():
        if not isinstance(entry, dict):
            continue
        entry_d = cast("dict[str, Any]", entry)
        label = str(entry_d.get("label", key))
        points = float(entry_d.get("points", 0.0) or 0.0)
        aliases = entry_d.get("aliases")
        if isinstance(aliases, list):
            for alias in cast("list[Any]", aliases):
                pattern = re.compile(rf"(?<!\w){re.escape(str(alias))}(?!\w)", re.IGNORECASE)
                out.append((pattern, label, points))
    return out


def clear_penalty_cache() -> None:
    _penalty_patterns.cache_clear()


@dataclass
class ScoreLine:
    label: str
    points: float


@dataclass
class ScoreResult:
    total: float
    lines: list[ScoreLine]

    def as_breakdown(self) -> list[dict[str, Any]]:
        return [{"label": ln.label, "points": round(ln.points, 1)} for ln in self.lines]


def _label_for(key: str, catalog: FeatureCatalog) -> str:
    f = catalog.features.get(key)
    return f.label if f else key.replace("_", " ")


def _clamp(value: float, cap: float) -> float:
    return max(-cap, min(cap, value))


class Scorer:
    def __init__(self, catalog: FeatureCatalog | None = None) -> None:
        self.catalog = catalog or get_catalog()
        raw = load_yaml_mapping("scoring/weights.yaml")
        self._defaults: dict[str, Any] = raw.get("defaults", {})
        self._by_type: dict[str, dict[str, Any]] = {
            "car": raw.get("car", self._defaults),
            "motorcycle": raw.get("motorcycle", self._defaults),
        }

    def _weights(self, vtype: VehicleType) -> dict[str, Any]:
        return self._by_type.get(vtype.value, self._defaults) or self._defaults

    def compute_scores(
        self,
        listings: list[VehicleListing],
        target: SearchTarget,
        reference_year: int | None = None,
    ) -> list[ScoreResult]:
        """Score every listing relative to the set. Returns results aligned by index."""
        ref_year = reference_year or date.today().year
        prices = [x.price for x in listings if x.price]
        mileages = [x.mileage_km for x in listings if x.mileage_km]
        median_price = statistics.median(prices) if prices else None
        median_mileage = statistics.median(mileages) if mileages else None

        # Feature frequency across the set (for rarity:auto), counting scored matches only.
        n = len(listings) or 1
        freq: dict[str, float] = {}
        for ldef in self.catalog.scored_features():
            have = sum(1 for x in listings if self._has_feature(x, ldef.canonical))
            freq[ldef.canonical] = have / n

        return [
            self._score_one(x, target, median_price, median_mileage, freq, ref_year)
            for x in listings
        ]

    @staticmethod
    def _has_feature(listing: VehicleListing, canonical: str) -> bool:
        return any(f.canonical == canonical and f.is_scored for f in listing.get_features())

    def _score_one(
        self,
        listing: VehicleListing,
        target: SearchTarget,
        median_price: float | None,
        median_mileage: float | None,
        freq: dict[str, float],
        ref_year: int,
    ) -> ScoreResult:
        w = self._weights(listing.vehicle_type)
        lines: list[ScoreLine] = [ScoreLine("Base value", float(w.get("base", 0)))]

        # Price vs comparable market median.
        if listing.price and median_price:
            pct = (median_price - listing.price) / median_price * 100
            cfg = w.get("price_vs_market", {})
            pts = _clamp(
                pct / cfg.get("pct_step", 5) * cfg.get("points_per_step", 3), cfg.get("cap", 24)
            )
            verb = "below" if pct >= 0 else "above"
            label = f"Price {verb} median (€{listing.price:,} vs €{int(median_price):,})"
            lines.append(ScoreLine(label, pts))

        # Mileage vs comparable median.
        if listing.mileage_km and median_mileage:
            diff = median_mileage - listing.mileage_km
            cfg = w.get("low_mileage", {})
            pts = _clamp(
                diff / cfg.get("mileage_step", 10000) * cfg.get("points_per_step", 2),
                cfg.get("cap", 12),
            )
            verb = "Lower" if diff >= 0 else "Higher"
            lines.append(
                ScoreLine(
                    f"{verb} mileage ({listing.mileage_km:,} km vs {int(median_mileage):,})", pts
                )
            )

        # Age.
        if listing.model_year:
            cfg = w.get("age", {})
            over = max(0, (ref_year - listing.model_year) - int(cfg.get("age_grace_years", 1)))
            pts = -min(over * cfg.get("penalty_per_year", 2), cfg.get("cap", 16))
            if pts:
                lines.append(ScoreLine(f"Age {ref_year - listing.model_year}y", pts))

        feats = {f.canonical for f in listing.get_features() if f.is_scored}

        # Required equipment (penalty if absent).
        for req in target.required_equipment:
            if req not in feats:
                lines.append(
                    ScoreLine(
                        f"Missing required: {_label_for(req, self.catalog)}",
                        -float(w.get("required_equipment_missing_penalty", 25)),
                    )
                )

        # Preferred equipment (confidence-gated; rarity:auto adds a scarcity bonus).
        default_pref = float(w.get("preferred_equipment_points", 3))
        for pref in target.preferred_equipment:
            if pref not in feats:
                continue
            fdef = self.catalog.features.get(pref)
            base_pts = float(fdef.points) if fdef and fdef.points else default_pref
            if fdef and fdef.rarity == "auto":
                fr = freq.get(pref, 0.0)
                bonus = base_pts * (1 - fr)
                lines.append(
                    ScoreLine(
                        f"{_label_for(pref, self.catalog)} (rare: on {fr * 100:.0f}% of matches)",
                        round(base_pts + bonus, 1),
                    )
                )
            else:
                lines.append(ScoreLine(_label_for(pref, self.catalog), base_pts))

        # Warranty.
        if listing.warranty:
            lines.append(
                ScoreLine(f"Warranty: {listing.warranty}", float(w.get("warranty_dealer_bonus", 7)))
            )

        # Seller type.
        if listing.seller_type.value == "dealer":
            b = float(w.get("seller_dealer_bonus", 0))
            if b:
                lines.append(ScoreLine("Dealer seller", b))

        # Distance (straight-line).
        if listing.distance_km is not None:
            cfg = w.get("distance", {})
            pts = -min(
                listing.distance_km
                / cfg.get("distance_step_km", 100)
                * cfg.get("penalty_per_step", 1.5),
                cfg.get("cap", 9),
            )
            lines.append(
                ScoreLine(f"{listing.distance_km:.0f} km away (straight-line)", round(pts, 1))
            )

        # Import friction (foreign listing).
        if (listing.country or "").upper() == "DE":
            lines.append(ScoreLine("German import", -float(w.get("import_friction_penalty", 5))))

        # Accident / damage history reported by the source.
        if listing.accident_info:
            lines.append(
                ScoreLine(
                    "Accident/damage history reported",
                    -float(w.get("accident_history_penalty", 35)),
                )
            )

        # Completeness / trust.
        present = sum(
            1
            for x in (
                listing.price,
                listing.mileage_km,
                listing.model_year,
                listing.image_urls,
                listing.description,
            )
            if x
        )
        if present >= 4:
            lines.append(ScoreLine("Listing complete", float(w.get("completeness_bonus", 5))))

        # Character adjustments from text: penalties (big wheels, Shadow Line, M aero,
        # lowered, light interior) and rewards (black/dark interior). Points may be + or -.
        text = " ".join(
            p for p in (listing.title, listing.description, listing.raw_options_text) if p
        )
        seen: set[str] = set()
        for pattern, label, points in _penalty_patterns():
            if label not in seen and pattern.search(text):
                seen.add(label)
                lines.append(ScoreLine(label, points))

        total = round(sum(ln.points for ln in lines), 1)
        return ScoreResult(total=total, lines=lines)


def apply_scores(
    listings: list[VehicleListing], target: SearchTarget, reference_year: int | None = None
) -> None:
    """Compute and write score + breakdown onto each listing in place."""
    results = Scorer().compute_scores(listings, target, reference_year)
    for listing, result in zip(listings, results, strict=True):
        listing.score = result.total
        listing.score_breakdown = result.as_breakdown()
