"""Equipment normalization tests (uses the real config catalog — not live HTTP)."""

from __future__ import annotations

from vehicle_finder.models.enums import FeatureConfidence
from vehicle_finder.normalize.equipment import EquipmentNormalizer


def test_detects_multilingual_aliases() -> None:
    norm = EquipmentNormalizer()
    # NL, DE, EN spellings of the same features.
    nl = {f.canonical for f in norm.normalize_text("Met trekhaak en verwarmde handvatten")}
    de = {f.canonical for f in norm.normalize_text("mit Anhängerkupplung und Heizgriffe")}
    en = {f.canonical for f in norm.normalize_text("with towbar and heated grips")}
    assert "towbar" in nl and "towbar" in de and "towbar" in en
    assert "heated_grips" in nl and "heated_grips" in de and "heated_grips" in en


def test_provenance_and_confidence() -> None:
    norm = EquipmentNormalizer()
    matches = norm.normalize_text("Uitgerust met Head-Up Display", source="bmw-nl")
    hud = next(m for m in matches if m.canonical == "head_up_display")
    assert hud.confidence is FeatureConfidence.MEDIUM  # free text => medium
    assert hud.source == "bmw-nl"
    assert hud.source_text  # provenance preserved
    assert hud.is_scored is True


def test_no_false_positive_on_empty() -> None:
    assert EquipmentNormalizer().normalize_text("") == []
    assert EquipmentNormalizer().normalize_text(None) == []


def test_distinct_features_deduped() -> None:
    norm = EquipmentNormalizer()
    # "Surround View" appears twice; should yield a single match.
    matches = norm.normalize_text("Surround View camera, echt een Surround View")
    svc = [m for m in matches if m.canonical == "surround_view_camera"]
    assert len(svc) == 1
