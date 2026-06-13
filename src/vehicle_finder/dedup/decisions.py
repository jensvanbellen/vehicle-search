"""Record sticky manual merge decisions (confirm-merge / mark-not-duplicate).

These are authoritative over automatic clustering and persist across refreshes. Used by
the UI and CLI; the clustering step (``dedup.cluster``) applies them on every regroup.
"""

from __future__ import annotations

from sqlmodel import Session, select

from vehicle_finder.logging import get_logger
from vehicle_finder.models.group import MergeDecision

log = get_logger("decisions")


def record_decision(
    session: Session, key_a: str, key_b: str, decision: str, reason: str | None = None
) -> MergeDecision:
    """Upsert a manual decision for a listing pair. ``decision`` in {merge, not_duplicate}."""
    if decision not in ("merge", "not_duplicate"):
        raise ValueError(f"invalid decision: {decision!r}")
    a, b = MergeDecision.pair_key(key_a, key_b)
    existing = session.exec(
        select(MergeDecision).where(MergeDecision.key_a == a, MergeDecision.key_b == b)
    ).first()
    if existing is not None:
        existing.decision = decision
        existing.reason = reason
        session.add(existing)
        log.info("decision_updated", pair=(a, b), decision=decision)
        return existing
    row = MergeDecision(key_a=a, key_b=b, decision=decision, reason=reason)
    session.add(row)
    log.info("decision_recorded", pair=(a, b), decision=decision)
    return row


def confirm_merge(
    session: Session, key_a: str, key_b: str, reason: str | None = None
) -> MergeDecision:
    return record_decision(session, key_a, key_b, "merge", reason)


def mark_not_duplicate(
    session: Session, key_a: str, key_b: str, reason: str | None = None
) -> MergeDecision:
    return record_decision(session, key_a, key_b, "not_duplicate", reason)


def clear_decision(session: Session, key_a: str, key_b: str) -> bool:
    a, b = MergeDecision.pair_key(key_a, key_b)
    existing = session.exec(
        select(MergeDecision).where(MergeDecision.key_a == a, MergeDecision.key_b == b)
    ).first()
    if existing is None:
        return False
    session.delete(existing)
    return True
