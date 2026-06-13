"""Per-source health diagnostics from the SourceRun audit table."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, col, desc, select

from vehicle_finder.configio import load_sources
from vehicle_finder.models.history import SourceRun
from vehicle_finder.persistence.db import session_scope


def _latest_runs(session: Session, source: str) -> tuple[SourceRun | None, SourceRun | None]:
    last = session.exec(
        select(SourceRun)
        .where(SourceRun.source == source)
        .order_by(desc(col(SourceRun.started_at)))
    ).first()
    last_ok = session.exec(
        select(SourceRun)
        .where(SourceRun.source == source, col(SourceRun.succeeded).is_(True))
        .order_by(desc(col(SourceRun.started_at)))
    ).first()
    return last, last_ok


def source_diagnostics() -> list[dict[str, Any]]:
    """Structured per-source health for the UI and CLI."""
    rows: list[dict[str, Any]] = []
    with session_scope() as session:
        for source_id, cfg in load_sources().items():
            last, last_ok = _latest_runs(session, source_id)
            # bmw.de live transport can't be exercised here; surface that explicitly.
            if cfg.adapter == "bmw_de" and last_ok is None:
                status = "unverified in build env"
            elif last is None:
                status = "never run"
            elif last.error:
                status = "error"
            elif last.layout_changed:
                status = "layout changed?"
            elif last.parse_failures:
                status = "partial (parse failures)"
            else:
                status = "ok"
            rows.append(
                {
                    "source": source_id,
                    "enabled": cfg.enabled,
                    "adapter": cfg.adapter,
                    "status": status,
                    "last_attempt": last.started_at.isoformat(timespec="minutes") if last else None,
                    "last_success": last_ok.started_at.isoformat(timespec="minutes")
                    if last_ok
                    else None,
                    "found": last.found if last else 0,
                    "parsed": last.parsed if last else 0,
                    "parse_failures": last.parse_failures if last else 0,
                    "layout_changed": last.layout_changed if last else False,
                    "warnings": (last.warnings[:5] if last else []),
                }
            )
    return rows


def render_diagnostics() -> str:
    """Human-readable per-source health table for the CLI."""
    lines = ["Source diagnostics", "=" * 60]
    for row in source_diagnostics():
        flag = "on " if row["enabled"] else "off"
        lines.append(
            f"[{flag}] {row['source']:<18} {row['status']:<22} "
            f"found={row['found']} parsed={row['parsed']} failures={row['parse_failures']}"
        )
        lines.append(
            f"        last attempt: {row['last_attempt'] or '—'}  "
            f"last success: {row['last_success'] or '—'}"
        )
        for warning in row["warnings"]:
            lines.append(f"        ⚠ {warning}")
    return "\n".join(lines)
