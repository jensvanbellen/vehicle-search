"""Application smoke test — isolated temp DB, no live network."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import vehicle_finder.persistence.db as db
from vehicle_finder import __version__
from vehicle_finder.models.enums import SellerType, VehicleType
from vehicle_finder.models.listing import VehicleListing
from vehicle_finder.persistence.db import init_database
from vehicle_finder.web.app import app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    engine = db.get_engine(tmp_path / "smoke.db")
    init_database(engine)
    monkeypatch.setattr(db, "_engine", engine)
    with db.session_scope(engine) as session:
        session.add(
            VehicleListing(
                vehicle_type=VehicleType.CAR,
                source="bmw-nl",
                source_listing_id="smoke1",
                url="https://x/1",
                title="BMW X5 smoke-test",
                make="BMW",
                model="X5",
                price=50000,
                seller_type=SellerType.DEALER,
                score=42.0,
            )
        )
    yield TestClient(app)


def test_version() -> None:
    assert __version__ == "0.1.0"


def test_health_endpoint(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_listings_page_renders(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Vehicle Finder" in resp.text
    assert "BMW X5 smoke-test" in resp.text


def test_detail_page_renders(client: TestClient) -> None:
    resp = client.get("/")
    assert "/listing/" in resp.text
    detail = client.get("/listing/1")
    assert detail.status_code == 200
    assert "Score breakdown" in detail.text
