"""Shared test fixtures. The suite is fully offline — no live HTTP, ever."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlmodel import Session

from vehicle_finder.persistence.db import get_engine, init_database

FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(*parts: str) -> dict[str, Any]:
    return json.loads((FIXTURES.joinpath(*parts)).read_text(encoding="utf-8"))


@pytest.fixture
def fixture() -> Callable[..., dict[str, Any]]:
    """Return a loader for JSON fixtures under tests/fixtures/."""
    return _load_fixture


@pytest.fixture
def engine() -> Engine:
    """A fresh in-memory SQLite engine with the schema created."""
    eng = get_engine(Path(":memory:"))
    init_database(eng)
    return eng


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine) as s:
        yield s
