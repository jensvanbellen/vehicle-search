"""Equipment / option normalization.

Maps inconsistent NL/DE/EN seller text to canonical feature keys, preserving the raw
matched text as provenance and attaching a confidence. The feature catalog is loaded
from config (``equipment_synonyms.yaml`` + ``scoring/features.yaml``) — never hard-coded.

Free-text matches are MEDIUM confidence by default (option text is unreliable);
callers may assert HIGH-confidence features from structured fields separately.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, cast

from vehicle_finder.configio import load_yaml_mapping
from vehicle_finder.models.enums import FeatureConfidence
from vehicle_finder.models.values import FeatureMatch


@dataclass(frozen=True)
class FeatureDef:
    canonical: str
    label: str
    aliases: tuple[str, ...]
    points: float = 0.0
    rarity: str | None = None  # "auto" | "high" | "medium" | "low" | None
    scored: bool = False  # True if it came from the scored-features catalog


class FeatureCatalog:
    """All known features, with a compiled alias->canonical match index."""

    def __init__(self, features: dict[str, FeatureDef]) -> None:
        self.features = features
        self.patterns: list[tuple[re.Pattern[str], str]] = []
        for fdef in features.values():
            for alias in fdef.aliases:
                alias = alias.strip()
                if not alias:
                    continue
                # word-ish boundaries; tolerate punctuation like "360°" / "B&W".
                pattern = re.compile(rf"(?<!\w){re.escape(alias)}(?!\w)", re.IGNORECASE)
                self.patterns.append((pattern, fdef.canonical))

    def scored_features(self) -> list[FeatureDef]:
        return [f for f in self.features.values() if f.scored]


def _iter_feature_entries(raw: object) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield (key, entry-dict) pairs from a YAML 'features' mapping, ignoring junk."""
    if not isinstance(raw, dict):
        return
    for key, entry in cast("dict[str, Any]", raw).items():
        if isinstance(entry, dict):
            yield str(key), cast("dict[str, Any]", entry)


def _collect_aliases(entry: dict[str, Any]) -> list[str]:
    aliases: list[str] = []
    for key in ("aliases", "aliases_nl", "aliases_de", "aliases_en"):
        val = entry.get(key)
        if isinstance(val, list):
            aliases.extend(str(a) for a in cast("list[Any]", val))
    return aliases


def _build_catalog() -> FeatureCatalog:
    features: dict[str, FeatureDef] = {}

    # 1) Scored/desirable features (carry points + rarity).
    scored_raw = load_yaml_mapping("scoring/features.yaml").get("features")
    for key, entry in _iter_feature_entries(scored_raw):
        features[key] = FeatureDef(
            canonical=key,
            label=str(entry.get("label", key)),
            aliases=tuple(_collect_aliases(entry)),
            points=float(entry.get("points", 0.0) or 0.0),
            rarity=(str(entry["rarity"]) if entry.get("rarity") is not None else None),
            scored=True,
        )

    # 2) General normalizable features (label + aliases only).
    synonyms_raw = load_yaml_mapping("equipment_synonyms.yaml").get("features")
    for key, entry in _iter_feature_entries(synonyms_raw):
        if key in features:
            continue
        features[key] = FeatureDef(
            canonical=key,
            label=str(entry.get("label", key)),
            aliases=tuple(_collect_aliases(entry)),
        )

    return FeatureCatalog(features)


@functools.lru_cache(maxsize=1)
def get_catalog() -> FeatureCatalog:
    return _build_catalog()


def clear_catalog_cache() -> None:
    get_catalog.cache_clear()


class EquipmentNormalizer:
    """Detects canonical features in free text."""

    def __init__(self, catalog: FeatureCatalog | None = None) -> None:
        self.catalog = catalog or get_catalog()

    def normalize_text(
        self,
        text: str | None,
        source: str | None = None,
        confidence: FeatureConfidence = FeatureConfidence.MEDIUM,
    ) -> list[FeatureMatch]:
        """Return one FeatureMatch per distinct feature found in ``text``."""
        if not text:
            return []
        found: dict[str, FeatureMatch] = {}
        for pattern, canonical in self.catalog.patterns:
            if canonical in found:
                continue
            match = pattern.search(text)
            if match is None:
                continue
            fdef = self.catalog.features[canonical]
            found[canonical] = FeatureMatch(
                canonical=canonical,
                label=fdef.label,
                confidence=confidence,
                source_text=match.group(0),
                source=source,
            )
        return list(found.values())
