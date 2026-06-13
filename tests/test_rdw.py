"""RDW parsing tests — offline (no live API)."""

from __future__ import annotations

from vehicle_finder.enrich.rdw import normalize_plate, odometer_is_implausible, parse_rdw_record

CAR_RECORD = {
    "kenteken": "AB123C",
    "merk": "BMW",
    "handelsbenaming": "X5",
    "datum_eerste_toelating": "20220309",
    "datum_eerste_toelating_dt": "2022-03-09T00:00:00.000",
    "datum_eerste_tenaamstelling_in_nederland": "20220401",
    "tellerstandoordeel": "Logisch",
    "eerste_kleur": "Grijs",
    "catalogusprijs": "95000",
    "bruto_bpm": "12000",
    "openstaande_terugroepactie_indicator": "Nee",
    "export_indicator": "Nee",
}


def test_normalize_plate() -> None:
    assert normalize_plate("53-MX-FD") == "53MXFD"
    assert normalize_plate("hpx-83-z") == "HPX83Z"
    assert normalize_plate(None) == ""


def test_parse_record() -> None:
    d = parse_rdw_record(CAR_RECORD)
    assert d["verified"] is True
    assert d["first_admission"] == "2022-03-09"  # from the ISO _dt companion
    assert d["first_nl_registration"] == "2022-04-01"  # from the compact YYYYMMDD
    assert d["odometer_judgement"] == "Logisch"
    assert d["colour"] == "grey"  # normalized from "Grijs"
    assert d["catalogue_price"] == 95000
    assert d["gross_bpm"] == 12000
    assert d["recall_open"] is False


def test_colour_nvt_dropped() -> None:
    d = parse_rdw_record({"datum_eerste_toelating": "20220101", "eerste_kleur": "N.v.t."})
    assert "colour" not in d


def test_odometer_implausible_flag() -> None:
    assert odometer_is_implausible({"odometer_judgement": "Onlogisch"}) is True
    assert odometer_is_implausible({"odometer_judgement": "Logisch"}) is False
    assert odometer_is_implausible({}) is False
