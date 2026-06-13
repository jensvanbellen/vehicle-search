"""Export tests (CSV + JSON) against an isolated temp DB."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import vehicle_finder.persistence.db as db
from vehicle_finder.exporting import export_listings
from vehicle_finder.models.enums import SellerType, VehicleType
from vehicle_finder.models.listing import VehicleListing
from vehicle_finder.persistence.db import init_database
from vehicle_finder.persistence.repository import upsert_listing


@pytest.fixture
def populated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = db.get_engine(tmp_path / "exp.db")
    init_database(engine)
    monkeypatch.setattr(db, "_engine", engine)
    with db.session_scope(engine) as session:
        upsert_listing(
            session,
            VehicleListing(
                vehicle_type=VehicleType.CAR,
                source="bmw-nl",
                source_listing_id="1",
                url="https://x/1",
                title="BMW X5",
                make="BMW",
                model="X5",
                price=60000,
                mileage_km=50000,
                seller_type=SellerType.DEALER,
            ),
        )


def test_json_export(populated_db: None, tmp_path: Path) -> None:
    out = str(tmp_path / "export")
    path = export_listings(fmt="json", out=out)
    assert path.endswith(".json")
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert len(payload["listings"]) == 1
    assert payload["listings"][0]["make"] == "BMW"
    assert "price_history" in payload["listings"][0]


def test_csv_export(populated_db: None, tmp_path: Path) -> None:
    out = str(tmp_path / "export")
    path = export_listings(fmt="csv", out=out)
    assert path.endswith(".csv")
    text = Path(path).read_text(encoding="utf-8")
    assert "make" in text.splitlines()[0]  # header
    assert "BMW" in text


def test_invalid_format(populated_db: None, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsupported export format"):
        export_listings(fmt="xml", out=str(tmp_path / "x"))
