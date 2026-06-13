"""Basic application smoke test — no live network involved."""

from __future__ import annotations

from fastapi.testclient import TestClient

from vehicle_finder import __version__
from vehicle_finder.web.app import app


def test_version() -> None:
    assert __version__ == "0.1.0"


def test_health_endpoint() -> None:
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_home_page() -> None:
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Vehicle Finder" in resp.text
