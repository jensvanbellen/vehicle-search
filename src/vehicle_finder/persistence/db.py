"""SQLite engine, schema bootstrap, and session management."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, SQLModel, create_engine

# Importing the models package registers every table on SQLModel.metadata (side-effect).
import vehicle_finder.models as _models
from vehicle_finder.config import get_settings
from vehicle_finder.logging import get_logger

_ = _models  # ensure table classes are imported before create_all()
log = get_logger("db")

_engine: Engine | None = None


def get_engine(db_path: Path | None = None, echo: bool = False) -> Engine:
    """Return (creating once) the process-wide SQLite engine."""
    global _engine
    if db_path is not None:
        # Explicit path (e.g. tests / in-memory) — build a dedicated engine.
        return _build_engine(db_path, echo)
    if _engine is None:
        _engine = _build_engine(get_settings().db_file, echo)
    return _engine


def _build_engine(db_path: Path, echo: bool) -> Engine:
    if str(db_path) == ":memory:":
        url = "sqlite://"
    else:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{db_path}"
    return create_engine(url, echo=echo, connect_args={"check_same_thread": False})


def init_database(engine: Engine | None = None) -> None:
    """Create all tables if they do not exist."""
    eng = engine or get_engine()
    SQLModel.metadata.create_all(eng)
    log.info("database_initialized", url=str(eng.url))


@contextmanager
def session_scope(engine: Engine | None = None) -> Generator[Session, None, None]:
    """Transactional session context: commit on success, rollback on error."""
    eng = engine or get_engine()
    session = Session(eng)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
