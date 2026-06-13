"""Pairwise duplicate matching: weighted signals -> confidence + explanation.

Conservative by design (bias toward NOT merging). Matching VIN/kenteken is decisive.
All weights/thresholds come from ``config/dedup.yaml``.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, cast

from rapidfuzz import fuzz

from vehicle_finder.configio import load_yaml_mapping
from vehicle_finder.imaging import count_near_identical
from vehicle_finder.models.listing import VehicleListing


class MatchVerdict(StrEnum):
    MERGE = "merge"
    POSSIBLE = "possible"
    DISTINCT = "distinct"


def _empty_reasons() -> list[str]:
    return []


def _empty_weights() -> dict[str, float]:
    return {}


@dataclass
class MatchResult:
    verdict: MatchVerdict
    confidence: float
    reasons: list[str] = field(default_factory=_empty_reasons)
    decisive: bool = False


@dataclass(frozen=True)
class DedupConfig:
    mileage_tolerance_km: int = 200
    description_similarity_threshold: int = 82
    phash_max_hamming: int = 8
    phash_min_matches: int = 2
    power_tolerance_hp: int = 5
    price_proximity_pct: float = 5.0
    merge_threshold: float = 0.75
    possible_duplicate_threshold: float = 0.55
    weights: dict[str, float] = field(default_factory=_empty_weights)


@functools.lru_cache(maxsize=1)
def get_dedup_config() -> DedupConfig:
    raw: dict[str, Any] = load_yaml_mapping("dedup.yaml")
    weights_raw = raw.get("weights", {})
    weights: dict[str, float] = (
        {str(k): float(v) for k, v in cast("dict[str, Any]", weights_raw).items()}
        if isinstance(weights_raw, dict)
        else {}
    )
    return DedupConfig(
        mileage_tolerance_km=int(raw.get("mileage_tolerance_km", 200)),
        description_similarity_threshold=int(raw.get("description_similarity_threshold", 82)),
        phash_max_hamming=int(raw.get("phash_max_hamming", 8)),
        phash_min_matches=int(raw.get("phash_min_matches", 2)),
        power_tolerance_hp=int(raw.get("power_tolerance_hp", 5)),
        price_proximity_pct=float(raw.get("price_proximity_pct", 5.0)),
        merge_threshold=float(raw.get("merge_threshold", 0.75)),
        possible_duplicate_threshold=float(raw.get("possible_duplicate_threshold", 0.55)),
        weights=weights,
    )


def clear_dedup_cache() -> None:
    get_dedup_config.cache_clear()


def _norm(text: str | None) -> str:
    return (text or "").strip().lower()


def _same_registration(a: VehicleListing, b: VehicleListing) -> bool:
    if a.registration_date and b.registration_date:
        return (a.registration_date.year, a.registration_date.month) == (
            b.registration_date.year,
            b.registration_date.month,
        )
    if a.model_year and b.model_year:
        return a.model_year == b.model_year
    return False


def compute_match(
    a: VehicleListing, b: VehicleListing, cfg: DedupConfig | None = None
) -> MatchResult:
    """Score how likely two listings are the same physical vehicle."""
    cfg = cfg or get_dedup_config()
    w = cfg.weights

    # Decisive identifiers.
    if a.vin and b.vin and _norm(a.vin) == _norm(b.vin):
        return MatchResult(MatchVerdict.MERGE, 1.0, [f"identical VIN {a.vin}"], decisive=True)
    if a.kenteken and b.kenteken and _norm(a.kenteken) == _norm(b.kenteken):
        return MatchResult(
            MatchVerdict.MERGE, 1.0, [f"identical kenteken {a.kenteken}"], decisive=True
        )

    confidence = 0.0
    reasons: list[str] = []

    if (
        a.mileage_km is not None
        and b.mileage_km is not None
        and abs(a.mileage_km - b.mileage_km) <= cfg.mileage_tolerance_km
    ):
        confidence += w.get("mileage", 0.0)
        reasons.append(
            f"mileage within {cfg.mileage_tolerance_km} km ({a.mileage_km:,}/{b.mileage_km:,})"
        )

    if _same_registration(a, b):
        confidence += w.get("registration", 0.0)
        if a.registration_date and b.registration_date:
            reasons.append(f"same first registration {a.registration_date:%Y-%m}")
        else:
            reasons.append(f"same model year {a.model_year}")

    if a.seller_name and b.seller_name and _norm(a.seller_name) == _norm(b.seller_name):
        confidence += w.get("dealer", 0.0)
        reasons.append(f"same dealer ({a.seller_name})")

    photo_matches = count_near_identical(a.image_phashes, b.image_phashes, cfg.phash_max_hamming)
    if photo_matches >= cfg.phash_min_matches:
        confidence += w.get("photos", 0.0)
        reasons.append(f"{photo_matches} near-identical photos")

    if (
        a.variant
        and b.variant
        and _norm(a.variant) == _norm(b.variant)
        and a.power_hp is not None
        and b.power_hp is not None
        and abs(a.power_hp - b.power_hp) <= cfg.power_tolerance_hp
    ):
        confidence += w.get("variant_power", 0.0)
        reasons.append(f"same variant + power ({a.variant}, {a.power_hp} hp)")

    if a.description and b.description:
        ratio = fuzz.token_set_ratio(a.description, b.description)
        if ratio >= cfg.description_similarity_threshold:
            confidence += w.get("description", 0.0)
            reasons.append(f"description similarity {int(ratio)}%")

    if a.colour and b.colour and _norm(a.colour) == _norm(b.colour):
        confidence += w.get("colour", 0.0)
        reasons.append(f"same colour ({a.colour})")

    if a.price and b.price:
        hi = max(a.price, b.price)
        if hi and abs(a.price - b.price) / hi * 100 <= cfg.price_proximity_pct:
            confidence += w.get("price", 0.0)
            reasons.append("price within tolerance")

    confidence = min(1.0, round(confidence, 3))
    if confidence >= cfg.merge_threshold:
        verdict = MatchVerdict.MERGE
    elif confidence >= cfg.possible_duplicate_threshold:
        verdict = MatchVerdict.POSSIBLE
    else:
        verdict = MatchVerdict.DISTINCT
    return MatchResult(verdict, confidence, reasons)
