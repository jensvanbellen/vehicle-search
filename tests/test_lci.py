"""pre-LCI vs LCI detection tests."""

from __future__ import annotations

from datetime import date

from vehicle_finder.normalize.lci import lci_status


def test_pre_lci_from_build_date() -> None:
    s = lci_status("BMW", "X5", "G05", build_date=date(2022, 6, 1))
    assert s.label == "pre-LCI"
    assert s.confidence == "high"
    assert s.is_pre_lci is True


def test_lci_from_build_date() -> None:
    s = lci_status("BMW", "X5", "G05", build_date=date(2023, 6, 1))
    assert s.label == "LCI"
    assert s.confidence == "high"


def test_low_confidence_from_registration_only() -> None:
    s = lci_status("BMW", "X5", "G05", build_date=None, registration_date=date(2022, 1, 1))
    assert s.label == "pre-LCI"
    assert s.confidence == "low"


def test_unknown_without_generation() -> None:
    assert lci_status("BMW", "X5", None, build_date=date(2022, 1, 1)).label == "unknown"


def test_unknown_for_unconfigured_model() -> None:
    # X3/G01 isn't in config/generations.yaml -> unknown rather than a guess.
    assert lci_status("BMW", "X3", "G01", build_date=date(2022, 1, 1)).label == "unknown"
