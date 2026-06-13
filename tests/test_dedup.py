"""Cross-platform merging tests — the required scenarios, fully offline."""

from __future__ import annotations

from datetime import date

from sqlmodel import Session, select

from vehicle_finder.dedup.cluster import cluster_listings, listing_key, regroup
from vehicle_finder.dedup.decisions import confirm_merge, mark_not_duplicate
from vehicle_finder.dedup.matcher import MatchVerdict, compute_match
from vehicle_finder.models.enums import SellerType, VehicleType
from vehicle_finder.models.group import MergeDecision, VehicleGroup
from vehicle_finder.models.listing import VehicleListing


def _mk(
    source: str,
    lid: str,
    *,
    dealer: str = "Demo Dealer A",
    mileage: int = 50000,
    reg: date = date(2022, 3, 1),
    price: int = 60000,
    phashes: list[str] | None = None,
    kenteken: str | None = None,
    colour: str = "black",
    description: str = "X5 xDrive45e met panoramadak en trekhaak",
) -> VehicleListing:
    return VehicleListing(
        vehicle_type=VehicleType.CAR,
        source=source,
        source_listing_id=lid,
        url=f"https://{source}/{lid}",
        title="BMW X5 xDrive45e",
        make="BMW",
        model="X5",
        model_year=reg.year,
        registration_date=reg,
        mileage_km=mileage,
        price=price,
        seller_type=SellerType.DEALER,
        seller_name=dealer,
        colour=colour,
        kenteken=kenteken,
        description=description,
        image_phashes=phashes or [],
    )


# --------------------------------------------------------------------------- matcher
def test_kenteken_is_decisive() -> None:
    a = _mk("bmw-nl", "1", kenteken="AB-123-C", dealer="Dealer A")
    b = _mk("marktplaats", "2", kenteken="AB-123-C", dealer="Different Dealer", mileage=99999)
    result = compute_match(a, b)
    assert result.verdict is MatchVerdict.MERGE
    assert result.decisive is True


def test_crosspost_merges() -> None:
    # Same dealer + mileage + first registration => 0.20 + 0.30 + 0.25 = 0.75 => MERGE.
    a = _mk("bmw-nl", "1")
    b = _mk("marktplaats", "2", price=61500)  # asking price differs across platforms
    result = compute_match(a, b)
    assert result.verdict is MatchVerdict.MERGE
    assert any("dealer" in r for r in result.reasons)


def test_distinct_vehicles_do_not_merge() -> None:
    a = _mk("bmw-nl", "1", dealer="Dealer A", mileage=50000, reg=date(2022, 3, 1))
    b = _mk(
        "bmw-de", "2", dealer="Dealer Z", mileage=120000, reg=date(2021, 9, 1), description="other"
    )
    result = compute_match(a, b)
    assert result.verdict is MatchVerdict.DISTINCT


def test_mid_confidence_is_possible_not_merge() -> None:
    # Same dealer (0.20) + registration (0.25) + similar description (0.15) = 0.60 => POSSIBLE.
    a = _mk("bmw-nl", "1", mileage=50000)
    b = _mk("marktplaats", "2", mileage=70000, colour="white")  # mileage far, colour differs
    result = compute_match(a, b)
    assert result.verdict is MatchVerdict.POSSIBLE
    assert 0.55 <= result.confidence < 0.75


def test_photos_signal_merges() -> None:
    shared = ["ffffffff00000000", "aaaaaaaa55555555"]
    a = _mk("bmw-nl", "1", dealer="Dealer A", reg=date(2022, 1, 1), phashes=shared)
    b = _mk("bmw-de", "2", dealer="Dealer Z", reg=date(2020, 1, 1), phashes=shared, description="x")
    # photos (0.45) + mileage (0.30) = 0.75 => MERGE even with different dealer/registration.
    result = compute_match(a, b)
    assert result.verdict is MatchVerdict.MERGE
    assert any("photos" in r for r in result.reasons)


# --------------------------------------------------------------------------- clustering
def test_cluster_groups_crossposts() -> None:
    a = _mk("bmw-nl", "1")
    b = _mk("marktplaats", "2")
    c = _mk(
        "bmw-de", "9", dealer="Far Dealer", mileage=130000, reg=date(2021, 1, 1), description="z"
    )
    outcome = cluster_listings([a, b, c], set(), set())
    assert outcome.group_id_of[listing_key(a)] == outcome.group_id_of[listing_key(b)]
    assert outcome.group_id_of[listing_key(c)] != outcome.group_id_of[listing_key(a)]


def test_manual_merge_forces_group() -> None:
    a = _mk("bmw-nl", "1", dealer="A", mileage=50000, reg=date(2022, 1, 1))
    b = _mk("bmw-de", "2", dealer="Z", mileage=120000, reg=date(2020, 1, 1), description="x")
    merge_pairs = {MergeDecision.pair_key(listing_key(a), listing_key(b))}
    outcome = cluster_listings([a, b], merge_pairs, set())
    assert outcome.group_id_of[listing_key(a)] == outcome.group_id_of[listing_key(b)]


def test_manual_not_duplicate_forbids_merge() -> None:
    a = _mk("bmw-nl", "1")
    b = _mk("marktplaats", "2")  # would auto-merge
    forbid = {MergeDecision.pair_key(listing_key(a), listing_key(b))}
    outcome = cluster_listings([a, b], set(), forbid)
    assert outcome.group_id_of[listing_key(a)] != outcome.group_id_of[listing_key(b)]


# --------------------------------------------------------------------------- persistence
def test_regroup_persists_and_is_stable(session: Session) -> None:
    a, b = _mk("bmw-nl", "1"), _mk("marktplaats", "2")
    session.add(a)
    session.add(b)
    session.commit()

    n1 = regroup(session, score=False)
    session.commit()
    assert n1 == 1  # the two cross-posts consolidate into one vehicle
    group = session.exec(select(VehicleGroup)).one()
    assert group.member_count == 2
    assert set(group.sources) == {"bmw-nl", "marktplaats"}
    assert group.merge_explanation  # human-readable why-grouped
    gid_first = group.group_id

    # Re-run (a "refresh"): group id stays stable, still one group.
    assert regroup(session, score=False) == 1
    session.commit()
    assert session.exec(select(VehicleGroup)).one().group_id == gid_first


def test_manual_split_persists_across_refresh(session: Session) -> None:
    a, b = _mk("bmw-nl", "1"), _mk("marktplaats", "2")
    session.add(a)
    session.add(b)
    session.commit()
    assert regroup(session, score=False) == 1  # auto-merged

    mark_not_duplicate(session, listing_key(a), listing_key(b), reason="different cars")
    session.commit()
    assert regroup(session, score=False) == 2  # split honoured
    session.commit()
    # Sticky across another refresh.
    assert regroup(session, score=False) == 2


def test_manual_merge_persists_across_refresh(session: Session) -> None:
    a = _mk("bmw-nl", "1", dealer="A", mileage=50000, reg=date(2022, 1, 1))
    b = _mk("bmw-de", "2", dealer="Z", mileage=120000, reg=date(2020, 1, 1), description="x")
    session.add(a)
    session.add(b)
    session.commit()
    assert regroup(session, score=False) == 2  # auto: distinct

    confirm_merge(session, listing_key(a), listing_key(b), reason="same car, verified")
    session.commit()
    assert regroup(session, score=False) == 1  # forced merge
    session.commit()
    assert regroup(session, score=False) == 1  # sticky
