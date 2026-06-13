"""Build a human-readable highlights digest (best matches, price drops, shortlist)."""

from __future__ import annotations

from sqlmodel import Session, col, desc, select

from vehicle_finder.models.enums import ListingStatus
from vehicle_finder.models.group import VehicleGroup
from vehicle_finder.models.history import PriceObservation
from vehicle_finder.models.listing import VehicleListing
from vehicle_finder.models.userstate import UserVehicleState


def _price_drops(session: Session, limit: int = 10) -> list[tuple[VehicleListing, int, int]]:
    """Active listings whose two most recent price observations show a decrease."""
    drops: list[tuple[VehicleListing, int, int]] = []
    listings = session.exec(
        select(VehicleListing).where(VehicleListing.status == ListingStatus.ACTIVE)
    ).all()
    for listing in listings:
        if listing.id is None:
            continue
        obs = session.exec(
            select(PriceObservation)
            .where(PriceObservation.listing_id == listing.id)
            .order_by(desc(col(PriceObservation.observed_at)))
        ).all()
        prices = [o.price for o in obs if o.price is not None]
        if len(prices) >= 2 and prices[0] < prices[1]:
            drops.append((listing, prices[1], prices[0]))
    drops.sort(key=lambda t: t[1] - t[2], reverse=True)
    return drops[:limit]


def build_digest(session: Session, top_n: int = 5) -> str:
    """Markdown highlights: best matches, price drops, shortlisted vehicles."""
    lines: list[str] = ["# Vehicle Finder digest", ""]

    best = session.exec(
        select(VehicleGroup)
        .where(col(VehicleGroup.score).is_not(None))
        .order_by(desc(col(VehicleGroup.score)))
        .limit(top_n)
    ).all()
    lines.append("## Best current matches")
    if best:
        for g in best:
            price = f"€{g.canonical_price:,}" if g.canonical_price else "?"
            badge = f" (on {g.member_count} platforms)" if g.member_count > 1 else ""
            lines.append(
                f"- **{g.make} {g.model}** {g.model_year or ''} — {price} · score {g.score}{badge}"
            )
    else:
        lines.append("- (none yet — run a fetch)")

    drops = _price_drops(session)
    lines.append("\n## Price drops")
    if drops:
        for listing, was, now in drops:
            lines.append(
                f"- {listing.title} ({listing.source}): EUR {was:,} -> {now:,} (-{was - now:,})"
            )
    else:
        lines.append("- (none)")

    shortlisted = session.exec(
        select(VehicleGroup, UserVehicleState)
        .join(UserVehicleState, col(VehicleGroup.group_id) == col(UserVehicleState.group_id))
        .where(col(UserVehicleState.shortlisted).is_(True))
    ).all()
    lines.append("\n## Shortlisted")
    if shortlisted:
        for g, _state in shortlisted:
            price = f"€{g.canonical_price:,}" if g.canonical_price else "?"
            lines.append(f"- {g.make} {g.model} {g.model_year or ''} — {price}")
    else:
        lines.append("- (none)")

    return "\n".join(lines)
