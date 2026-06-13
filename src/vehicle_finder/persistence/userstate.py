"""Read/write helpers for per-vehicle user state (shortlist / reject / notes)."""

from __future__ import annotations

from sqlmodel import Session, select

from vehicle_finder.models.listing import utcnow
from vehicle_finder.models.userstate import UserVehicleState


def get_state(session: Session, group_id: str) -> UserVehicleState | None:
    return session.get(UserVehicleState, group_id)


def _get_or_create(session: Session, group_id: str) -> UserVehicleState:
    state = session.get(UserVehicleState, group_id)
    if state is None:
        state = UserVehicleState(group_id=group_id)
        session.add(state)
    return state


def set_shortlist(session: Session, group_id: str, value: bool) -> UserVehicleState:
    state = _get_or_create(session, group_id)
    state.shortlisted = value
    state.updated_at = utcnow()
    session.add(state)
    return state


def set_rejected(
    session: Session, group_id: str, value: bool, reason: str | None = None
) -> UserVehicleState:
    state = _get_or_create(session, group_id)
    state.rejected = value
    state.reject_reason = reason if value else None
    state.updated_at = utcnow()
    session.add(state)
    return state


def set_notes(session: Session, group_id: str, notes: str | None) -> UserVehicleState:
    state = _get_or_create(session, group_id)
    state.notes = notes
    state.updated_at = utcnow()
    session.add(state)
    return state


def all_states(session: Session) -> dict[str, UserVehicleState]:
    return {s.group_id: s for s in session.exec(select(UserVehicleState)).all()}
