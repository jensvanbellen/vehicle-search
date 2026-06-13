"""Fetch pipeline: fetch -> normalize -> distance -> score -> upsert -> inactivate stale
-> summary. Idempotent; per-source failures are recorded without corrupting stored data.

Cross-platform merging (milestone 6) will slot in between scoring and the summary; until
then ``groups_total`` reports active listings.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from vehicle_finder.config import get_settings
from vehicle_finder.configio import get_search, load_searches, load_sources
from vehicle_finder.distance import distance_from_home_km
from vehicle_finder.logging import get_logger
from vehicle_finder.models.history import SourceRun
from vehicle_finder.models.listing import VehicleListing, utcnow
from vehicle_finder.persistence.db import session_scope
from vehicle_finder.persistence.repository import (
    UpsertOutcome,
    count_active_listings,
    mark_stale_inactive,
    upsert_listing,
)
from vehicle_finder.scoring.scorer import apply_scores
from vehicle_finder.sources.base import get_adapter
from vehicle_finder.sources.http import PoliteClient

log = get_logger("pipeline")


@dataclass
class SourceRunResult:
    source: str
    found: int = 0
    new: int = 0
    updated: int = 0
    price_changes: int = 0
    removed: int = 0
    parse_failures: int = 0
    error: str | None = None


def _empty_results() -> list[SourceRunResult]:
    return []


@dataclass
class RunSummary:
    sources: list[SourceRunResult] = field(default_factory=_empty_results)
    groups_total: int = 0
    dry_run: bool = False

    def render(self) -> str:
        lines = ["Fetch run summary" + (" (dry-run)" if self.dry_run else "")]
        for s in self.sources:
            if s.error:
                lines.append(f"  {s.source}: ERROR — {s.error}")
            else:
                lines.append(
                    f"  {s.source}: found={s.found} new={s.new} updated={s.updated} "
                    f"price_changes={s.price_changes} removed={s.removed} "
                    f"parse_failures={s.parse_failures}"
                )
        lines.append(f"Active listings: {self.groups_total}")
        return "\n".join(lines)


def run_fetch(
    source: str | None = None,
    search: str | None = None,
    dry_run: bool = False,
) -> RunSummary:
    """Run a refresh across every configured source and search."""
    settings = get_settings()
    searches = [s for s in load_searches() if s.enabled and (search is None or s.id == search)]
    sources_cfg = load_sources()
    summary = RunSummary(dry_run=dry_run)
    per_source: dict[str, SourceRunResult] = {}
    fetched_sources: set[str] = set()
    by_search: dict[str, list[VehicleListing]] = defaultdict(list)
    audits: list[SourceRun] = []

    client = PoliteClient(settings)
    try:
        for target in searches:
            for src_id, cfg in sources_cfg.items():
                if not cfg.enabled or (source is not None and src_id != source):
                    continue
                adapter = get_adapter(src_id)
                if adapter is None or not adapter.supports(target):
                    continue
                fetched_sources.add(src_id)
                result = per_source.setdefault(src_id, SourceRunResult(source=src_id))
                audit = SourceRun(source=src_id, search_id=target.id)
                # Apply this source's polite request rate (falls back to the global default).
                client.min_delay = cfg.rate_limit_seconds or settings.request_delay_seconds
                try:
                    fetched = adapter.fetch(target, client)
                except Exception as exc:
                    log.error(
                        "source_fetch_failed", source=src_id, search=target.id, error=str(exc)
                    )
                    result.error = str(exc)
                    audit.error = str(exc)
                    audit.finished_at = utcnow()
                    audits.append(audit)
                    continue

                for listing in fetched.listings:
                    listing.distance_km = distance_from_home_km(
                        location=listing.location,
                        seller_name=listing.seller_name,
                        country=listing.country,
                        home_postcode=settings.home_postcode,
                    )
                by_search[target.id].extend(fetched.listings)
                result.found += fetched.found
                result.parse_failures += fetched.parse_failures
                audit.found = fetched.found
                audit.parsed = len(fetched.listings)
                audit.parse_failures = fetched.parse_failures
                audit.layout_changed = fetched.layout_changed
                audit.warnings = fetched.warnings
                audit.succeeded = not fetched.layout_changed
                audit.finished_at = utcnow()
                audits.append(audit)

        # Score each search's combined cross-source set (market-relative).
        for search_id, listings in by_search.items():
            target = get_search(search_id)
            if target:
                apply_scores(listings, target)

        if dry_run:
            summary.groups_total = sum(len(v) for v in by_search.values())
        else:
            with session_scope() as session:
                for listings in by_search.values():
                    for listing in listings:
                        outcome = upsert_listing(session, listing)
                        res = per_source[listing.source]
                        if outcome is UpsertOutcome.NEW:
                            res.new += 1
                        elif outcome is UpsertOutcome.PRICE_CHANGED:
                            res.price_changes += 1
                        elif outcome is UpsertOutcome.UPDATED:
                            res.updated += 1
                for src_id in fetched_sources:
                    per_source[src_id].removed = mark_stale_inactive(
                        session, {src_id}, settings.inactive_grace_hours
                    )
                for audit in audits:
                    session.add(audit)
                summary.groups_total = count_active_listings(session)
    finally:
        client.close()

    summary.sources = list(per_source.values())
    log.info("fetch_complete", sources=len(summary.sources), active=summary.groups_total)
    return summary
