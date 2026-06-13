"""Cross-platform clustering: assign listings to consolidated VehicleGroups.

Blocking (make+model+type, adjacent year) keeps comparisons tractable; a union-find over
high-confidence (and manually-confirmed) edges forms clusters; manual ``not_duplicate``
decisions forbid edges; group IDs are stable (anchored to the smallest member key).
Scoring runs on the consolidated representative, not on duplicates.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlmodel import Session, select

from vehicle_finder.configio import get_search
from vehicle_finder.dedup.matcher import MatchVerdict, compute_match, get_dedup_config
from vehicle_finder.logging import get_logger
from vehicle_finder.models.enums import ListingStatus
from vehicle_finder.models.group import MergeDecision, VehicleGroup
from vehicle_finder.models.listing import VehicleListing
from vehicle_finder.models.values import FeatureMatch
from vehicle_finder.scoring.scorer import Scorer

log = get_logger("cluster")


def listing_key(listing: VehicleListing) -> str:
    return f"{listing.source}:{listing.source_listing_id}"


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, x: str) -> None:
        self.parent.setdefault(x, x)

    def find(self, x: str) -> str:
        self.add(x)
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:  # path compression
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # Keep the lexicographically smaller root for stable group ids.
            lo, hi = (ra, rb) if ra <= rb else (rb, ra)
            self.parent[hi] = lo


def _empty_str_map() -> dict[str, str]:
    return {}


def _empty_reason_map() -> dict[str, list[str]]:
    return {}


@dataclass
class ClusterOutcome:
    group_id_of: dict[str, str] = field(default_factory=_empty_str_map)
    reasons_of: dict[str, list[str]] = field(default_factory=_empty_reason_map)
    possible_links: dict[str, list[str]] = field(default_factory=_empty_reason_map)


def _block_key(listing: VehicleListing) -> tuple[str, str, str]:
    return (
        listing.vehicle_type.value,
        (listing.make or "").lower().strip(),
        (listing.model or "").lower().strip(),
    )


def _years_adjacent(a: VehicleListing, b: VehicleListing) -> bool:
    if a.model_year is None or b.model_year is None:
        return True  # unknown year: don't exclude on this alone
    return abs(a.model_year - b.model_year) <= 1


def _group_id(member_keys: list[str]) -> str:
    anchor = min(member_keys)
    return "grp-" + hashlib.sha1(anchor.encode("utf-8")).hexdigest()[:12]


def cluster_listings(
    listings: list[VehicleListing],
    merge_pairs: set[tuple[str, str]],
    forbid_pairs: set[tuple[str, str]],
) -> ClusterOutcome:
    """Group listings into clusters. ``merge_pairs``/``forbid_pairs`` are manual overrides."""
    cfg = get_dedup_config()
    uf = _UnionFind()
    for listing in listings:
        uf.add(listing_key(listing))

    edge_reasons: list[tuple[str, str, list[str]]] = []
    possible: dict[str, list[str]] = defaultdict(list)

    blocks: dict[tuple[str, str, str], list[VehicleListing]] = defaultdict(list)
    for listing in listings:
        blocks[_block_key(listing)].append(listing)

    for members in blocks.values():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                ka, kb = listing_key(a), listing_key(b)
                pair = MergeDecision.pair_key(ka, kb)
                if pair in forbid_pairs:
                    continue  # manual not_duplicate is authoritative
                if pair in merge_pairs:
                    uf.union(ka, kb)
                    edge_reasons.append((ka, kb, ["manually confirmed as the same vehicle"]))
                    continue
                if not _years_adjacent(a, b):
                    continue
                result = compute_match(a, b, cfg)
                if result.verdict is MatchVerdict.MERGE:
                    uf.union(ka, kb)
                    edge_reasons.append((ka, kb, result.reasons))
                elif result.verdict is MatchVerdict.POSSIBLE:
                    possible[ka].append(kb)
                    possible[kb].append(ka)

    clusters: dict[str, list[VehicleListing]] = defaultdict(list)
    for listing in listings:
        clusters[uf.find(listing_key(listing))].append(listing)

    outcome = ClusterOutcome(possible_links=dict(possible))
    root_to_gid: dict[str, str] = {}
    for root, members in clusters.items():
        gid = _group_id([listing_key(m) for m in members])
        root_to_gid[root] = gid
        for m in members:
            outcome.group_id_of[listing_key(m)] = gid
    for ka, _kb, reasons in edge_reasons:
        gid = outcome.group_id_of[ka]
        outcome.reasons_of.setdefault(gid, [])
        for r in reasons:
            if r not in outcome.reasons_of[gid]:
                outcome.reasons_of[gid].append(r)
    return outcome


def build_representative(members: list[VehicleListing]) -> VehicleListing:
    """An in-memory consolidated vehicle for scoring: best data + union of features."""

    # Most complete member wins as the base (then lowest price as tie-break).
    def completeness(x: VehicleListing) -> tuple[int, int]:
        present = sum(
            1
            for v in (x.price, x.mileage_km, x.model_year, x.description, x.image_urls, x.power_hp)
            if v
        )
        return (present, -(x.price or 10**9))

    base = max(members, key=completeness)
    active_prices = [m.price for m in members if m.price]
    union: dict[str, FeatureMatch] = {}
    for m in members:
        for f in m.get_features():
            if f.canonical not in union or f.confidence.value == "high":
                union[f.canonical] = f
    distances = [m.distance_km for m in members if m.distance_km is not None]

    # A fresh, DETACHED listing (not added to any session) — never model_copy an
    # ORM-attached instance: it shares _sa_instance_state and mutations corrupt the original.
    rep = VehicleListing(
        vehicle_type=base.vehicle_type,
        source=base.source,
        source_listing_id=base.source_listing_id,
        url=base.url,
        title=base.title,
        make=base.make,
        model=base.model,
        variant=base.variant,
        model_year=base.model_year,
        registration_date=base.registration_date,
        mileage_km=base.mileage_km,
        price=min(active_prices) if active_prices else base.price,
        currency=base.currency,
        seller_type=base.seller_type,
        seller_name=base.seller_name,
        country=base.country,
        distance_km=min(distances) if distances else base.distance_km,
        warranty=base.warranty,
        description=base.description,
        raw_options_text=base.raw_options_text,  # so character penalties see the options text
        image_urls=list(base.image_urls),
        search_id=base.search_id,
    )
    rep.set_features(list(union.values()))
    return rep


def _load_decisions(session: Session) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    merge_pairs: set[tuple[str, str]] = set()
    forbid_pairs: set[tuple[str, str]] = set()
    for d in session.exec(select(MergeDecision)).all():
        pair = MergeDecision.pair_key(d.key_a, d.key_b)
        if d.decision == "merge":
            merge_pairs.add(pair)
        elif d.decision == "not_duplicate":
            forbid_pairs.add(pair)
    return merge_pairs, forbid_pairs


def regroup(session: Session, *, score: bool = True) -> int:
    """Recompute groups over all ACTIVE listings; persist VehicleGroup rows. Returns count."""
    listings = list(
        session.exec(
            select(VehicleListing).where(VehicleListing.status == ListingStatus.ACTIVE)
        ).all()
    )
    merge_pairs, forbid_pairs = _load_decisions(session)
    outcome = cluster_listings(listings, merge_pairs, forbid_pairs)

    members_by_gid: dict[str, list[VehicleListing]] = defaultdict(list)
    for listing in listings:
        gid = outcome.group_id_of[listing_key(listing)]
        listing.group_id = gid
        session.add(listing)
        members_by_gid[gid].append(listing)

    # Score consolidated representatives, grouped by search for market-relative metrics.
    rep_score: dict[str, tuple[float, list[dict[str, Any]]]] = {}
    if score:
        reps_by_search: dict[str, list[tuple[str, VehicleListing]]] = defaultdict(list)
        for gid, members in members_by_gid.items():
            rep = build_representative(members)
            reps_by_search[rep.search_id or "_"].append((gid, rep))
        scorer = Scorer()
        for search_id, pairs in reps_by_search.items():
            target = get_search(search_id) if search_id != "_" else None
            if target is None:
                continue
            results = scorer.compute_scores([rep for _gid, rep in pairs], target)
            for (gid, _rep), result in zip(pairs, results, strict=True):
                rep_score[gid] = (result.total, result.as_breakdown())

    # Replace group rows.
    for existing in session.exec(select(VehicleGroup)).all():
        session.delete(existing)
    session.flush()

    for gid, members in members_by_gid.items():
        prices = [m.price for m in members if m.price]
        sources = sorted({m.source for m in members})
        # Derive timestamps from members so "new since" survives regrouping.
        first_seen = min(m.first_seen for m in members)
        last_seen = max(m.last_seen for m in members)
        base = build_representative(members)
        explanation = outcome.reasons_of.get(gid, [])
        if len(members) > 1 and explanation:
            explanation = [f"Merged {len(members)} listings ({', '.join(sources)}):", *explanation]
        default_score: tuple[float | None, list[dict[str, Any]]] = (None, [])
        score_total, breakdown = rep_score.get(gid, default_score)
        session.add(
            VehicleGroup(
                group_id=gid,
                vehicle_type=base.vehicle_type,
                make=base.make,
                model=base.model,
                model_year=base.model_year,
                member_count=len(members),
                sources=sources,
                canonical_price=min(prices) if prices else None,
                price_min=min(prices) if prices else None,
                price_max=max(prices) if prices else None,
                country=base.country,
                distance_km=base.distance_km,
                score=score_total,
                score_breakdown=breakdown,
                merge_explanation=explanation,
                first_seen=first_seen,
                last_seen=last_seen,
            )
        )
    log.info("regrouped", listings=len(listings), groups=len(members_by_gid))
    return len(members_by_gid)
