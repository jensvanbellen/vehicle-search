"""Fetch pipeline orchestration.

The real implementation (fetch -> parse -> normalize -> store -> regroup -> rescore
-> summary) lands with the BMW NL vertical slice. :class:`RunSummary` is the stable
interface the CLI prints, defined here now.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SourceRunResult:
    """Outcome of fetching a single source during a run."""

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
    """Aggregate, human-readable summary of a fetch run."""

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
        lines.append(f"Consolidated vehicles: {self.groups_total}")
        return "\n".join(lines)


def run_fetch(
    source: str | None = None,
    search: str | None = None,
    dry_run: bool = False,
) -> RunSummary:
    """Run a refresh. PLACEHOLDER — implemented in the BMW NL vertical slice (milestone 2)."""
    raise NotImplementedError(
        "run_fetch is implemented in the BMW NL vertical slice (see docs/architecture.md §9)."
    )
