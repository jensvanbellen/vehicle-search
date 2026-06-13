"""Read-side helpers: turn ORM rows into plain dicts for templates.

Conversion happens inside the DB session so templates never touch detached ORM objects.
The UI is group-centric: one row per consolidated vehicle, never per duplicate.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlmodel import Session, col, desc, select

from vehicle_finder.configio import get_search
from vehicle_finder.models.enums import ListingStatus
from vehicle_finder.models.group import VehicleGroup
from vehicle_finder.models.history import PriceObservation, SourceRun
from vehicle_finder.models.listing import VehicleListing, utcnow
from vehicle_finder.models.userstate import UserVehicleState
from vehicle_finder.normalize.lci import LciStatus, lci_status
from vehicle_finder.scoring.import_cost import estimate_import_cost

_NEW_WINDOW = timedelta(hours=24)


def _lci_for(members: list[VehicleListing]) -> LciStatus:
    if not members:
        return LciStatus("unknown", "none")
    member = next((m for m in members if m.build_date), members[0])
    generation = None
    if member.search_id:
        target = get_search(member.search_id)
        generation = target.variant_generation if target else None
    return lci_status(
        member.make, member.model, generation, member.build_date, member.registration_date
    )


def _members(session: Session, group_id: str) -> list[VehicleListing]:
    return list(
        session.exec(
            select(VehicleListing).where(
                VehicleListing.group_id == group_id,
                VehicleListing.status == ListingStatus.ACTIVE,
            )
        ).all()
    )


def _union_features(members: list[VehicleListing]) -> list[str]:
    labels: dict[str, None] = {}
    for m in members:
        for f in m.get_features():
            if f.is_scored:
                labels[f.label] = None
    return list(labels)


def _first_image(members: list[VehicleListing]) -> str | None:
    for m in members:
        if m.image_urls:
            return m.image_urls[0]
    return None


def group_to_view(
    session: Session, group: VehicleGroup, state: UserVehicleState | None
) -> dict[str, Any]:
    members = _members(session, group.group_id)
    return {
        "group_id": group.group_id,
        "vehicle_type": group.vehicle_type.value,
        "make": group.make,
        "model": group.model,
        "model_year": group.model_year,
        "member_count": group.member_count,
        "sources": group.sources,
        "price": group.canonical_price,
        "price_min": group.price_min,
        "price_max": group.price_max,
        "price_spread": group.price_spread,
        "country": group.country,
        "distance_km": group.distance_km,
        "score": group.score,
        "image": _first_image(members),
        "features": _union_features(members)[:5],
        "is_new": group.first_seen >= utcnow() - _NEW_WINDOW,
        "lci": _lci_for(members).label,
        "rdw_verified": any(m.rdw for m in members),
        "shortlisted": bool(state and state.shortlisted),
        "rejected": bool(state and state.rejected),
    }


def active_group_views(session: Session) -> list[dict[str, Any]]:
    groups = session.exec(select(VehicleGroup)).all()
    states = {s.group_id: s for s in session.exec(select(UserVehicleState)).all()}
    return [group_to_view(session, g, states.get(g.group_id)) for g in groups]


def _combined_price_history(
    session: Session, members: list[VehicleListing]
) -> list[dict[str, Any]]:
    timeline: list[dict[str, Any]] = []
    for m in members:
        if m.id is None:
            continue
        for obs in session.exec(
            select(PriceObservation).where(PriceObservation.listing_id == m.id)
        ).all():
            timeline.append(
                {
                    "source": m.source,
                    "price": obs.price,
                    "observed_at": obs.observed_at.date().isoformat(),
                }
            )
    timeline.sort(key=lambda r: r["observed_at"], reverse=True)
    return timeline


def group_detail_view(session: Session, group_id: str) -> dict[str, Any] | None:
    group = session.get(VehicleGroup, group_id)
    if group is None:
        return None
    members = _members(session, group_id)
    state = session.get(UserVehicleState, group_id)

    member_views: list[dict[str, Any]] = []
    for m in members:
        member_views.append(
            {
                "id": m.id,
                "source": m.source,
                "url": m.url,
                "price": m.price,
                "mileage_km": m.mileage_km,
                "seller_name": m.seller_name,
                "country": m.country,
                "kenteken": m.kenteken,
                "owners": m.owners,
                "warranty": m.warranty,
                "accident_info": m.accident_info,
                "status": m.status.value,
                "data_quality": m.get_data_quality().warnings,
            }
        )

    # Union of features with provenance + confidence (from any member).
    feature_rows: dict[str, dict[str, Any]] = {}
    for m in members:
        for f in m.get_features():
            row = feature_rows.setdefault(
                f.canonical, {"label": f.label, "confidence": f.confidence.value, "sources": []}
            )
            if m.source not in row["sources"]:
                row["sources"].append(m.source)

    images: list[str] = []
    for m in members:
        for url in m.image_urls:
            if url not in images:
                images.append(url)

    lci = _lci_for(members)
    rdw_member = next((m for m in members if m.rdw), None)
    de_member = next(
        (m for m in members if (m.country or "").upper() == "DE" and m.price), None
    ) or next((m for m in members if (m.country or "").upper() == "DE"), None)
    estimate = estimate_import_cost(de_member) if de_member else None
    import_cost = (
        {
            "line_items": estimate.line_items,
            "added_total": estimate.added_total,
            "asking_price": estimate.asking_price,
            "all_in_price": estimate.all_in_price,
            "disclaimer": estimate.disclaimer,
        }
        if estimate
        else None
    )

    return {
        "group_id": group.group_id,
        "make": group.make,
        "model": group.model,
        "model_year": group.model_year,
        "vehicle_type": group.vehicle_type.value,
        "score": group.score,
        "score_breakdown": group.score_breakdown,
        "merge_explanation": group.merge_explanation,
        "price": group.canonical_price,
        "price_min": group.price_min,
        "price_max": group.price_max,
        "price_spread": group.price_spread,
        "country": group.country,
        "distance_km": group.distance_km,
        "member_count": group.member_count,
        "members": member_views,
        "features": list(feature_rows.values()),
        "images": images[:10],
        "price_history": _combined_price_history(session, members),
        "lci": {"label": lci.label, "confidence": lci.confidence},
        "rdw": rdw_member.rdw if rdw_member else {},
        "import_cost": import_cost,
        "shortlisted": bool(state and state.shortlisted),
        "rejected": bool(state and state.rejected),
        "reject_reason": state.reject_reason if state else None,
        "notes": state.notes if state else None,
    }


def dashboard_data(session: Session) -> dict[str, Any]:
    groups = list(session.exec(select(VehicleGroup)).all())
    active_listings = len(
        session.exec(
            select(VehicleListing).where(VehicleListing.status == ListingStatus.ACTIVE)
        ).all()
    )
    cutoff = utcnow() - _NEW_WINDOW
    new_groups = [g for g in groups if g.first_seen >= cutoff]
    multi = [g for g in groups if g.member_count > 1]
    best = sorted(
        (g for g in groups if g.score is not None),
        key=lambda g: g.score or 0,
        reverse=True,
    )[:5]
    last_runs = session.exec(
        select(SourceRun).order_by(desc(col(SourceRun.started_at))).limit(20)
    ).all()
    return {
        "group_count": len(groups),
        "active_listings": active_listings,
        "new_count": len(new_groups),
        "merged_count": len(multi),
        "best": [
            {
                "group_id": g.group_id,
                "make": g.make,
                "model": g.model,
                "model_year": g.model_year,
                "price": g.canonical_price,
                "score": g.score,
                "member_count": g.member_count,
            }
            for g in best
        ],
        "last_run": last_runs[0].started_at.isoformat(timespec="minutes") if last_runs else None,
    }
