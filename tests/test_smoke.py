"""Application smoke test — isolated temp DB, no live network. Group-centric UI."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

import vehicle_finder.persistence.db as db
from vehicle_finder import __version__
from vehicle_finder.dedup.cluster import regroup
from vehicle_finder.models.enums import SellerType, VehicleType
from vehicle_finder.models.group import VehicleGroup
from vehicle_finder.models.listing import VehicleListing
from vehicle_finder.models.userstate import UserVehicleState
from vehicle_finder.persistence.db import init_database
from vehicle_finder.web.app import app


def _listing(source: str, lid: str) -> VehicleListing:
    return VehicleListing(
        vehicle_type=VehicleType.CAR,
        source=source,
        source_listing_id=lid,
        url=f"https://{source}/{lid}",
        title="BMW X5 xDrive45e",
        make="BMW",
        model="X5",
        model_year=2022,
        registration_date=date(2022, 3, 1),
        mileage_km=50000,
        price=60000,
        seller_type=SellerType.DEALER,
        seller_name="Demo Dealer A",
        country="NL",
        score=42.0,
    )


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, str]]:
    engine = db.get_engine(tmp_path / "smoke.db")
    init_database(engine)
    monkeypatch.setattr(db, "_engine", engine)
    with db.session_scope(engine) as session:
        session.add(_listing("bmw-nl", "1"))
        session.add(_listing("marktplaats", "2"))  # cross-post -> should merge
    with db.session_scope(engine) as session:
        regroup(session)
    with db.session_scope(engine) as session:
        group_id = session.exec(select(VehicleGroup)).one().group_id
    yield TestClient(app), group_id


def test_version() -> None:
    assert __version__ == "0.1.0"


def test_health(client: tuple[TestClient, str]) -> None:
    resp = client[0].get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_dashboard(client: tuple[TestClient, str]) -> None:
    resp = client[0].get("/")
    assert resp.status_code == 200
    assert "Consolidated vehicles" in resp.text


def test_listings_shows_consolidated_vehicle(client: tuple[TestClient, str]) -> None:
    resp = client[0].get("/listings")
    assert resp.status_code == 200
    assert "BMW X5" in resp.text
    assert "seen on 2" in resp.text  # cross-post merged into one row


def test_group_detail(client: tuple[TestClient, str]) -> None:
    _client, group_id = client
    resp = _client.get(f"/group/{group_id}")
    assert resp.status_code == 200
    assert "Per-source listings" in resp.text
    assert "Why these are grouped" in resp.text


def test_diagnostics_page(client: tuple[TestClient, str]) -> None:
    resp = client[0].get("/diagnostics")
    assert resp.status_code == 200
    assert "Source diagnostics" in resp.text


def test_shortlist_action_persists(client: tuple[TestClient, str]) -> None:
    _client, group_id = client
    resp = _client.post(
        f"/group/{group_id}/shortlist", data={"value": "true"}, follow_redirects=False
    )
    assert resp.status_code == 303
    with db.session_scope() as session:
        state = session.get(UserVehicleState, group_id)
        assert state is not None and state.shortlisted is True


def test_compare(client: tuple[TestClient, str]) -> None:
    _client, group_id = client
    resp = _client.get(f"/compare?ids={group_id}")
    assert resp.status_code == 200
    assert "Compare vehicles" in resp.text
