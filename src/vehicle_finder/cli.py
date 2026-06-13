"""``vehicle-search`` command-line interface.

Commands are thin wrappers that wire configuration + logging and delegate to the
pipeline / web / export modules. Heavy logic lives in those modules, not here.
"""

from __future__ import annotations

import typer

from vehicle_finder.config import get_settings
from vehicle_finder.logging import configure_logging, get_logger

app = typer.Typer(
    name="vehicle-search",
    help="Local used car & motorcycle finder (NL/DE).",
    no_args_is_help=True,
    add_completion=False,
)
log = get_logger("cli")


def _boot() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)


@app.command()
def fetch(
    source: str | None = typer.Option(None, help="Only fetch this source id (e.g. bmw-nl)."),
    search: str | None = typer.Option(None, help="Only fetch this search id (e.g. x5-g05)."),
    dry_run: bool = typer.Option(False, help="Fetch & parse but do not write to the DB."),
) -> None:
    """Refresh listings from configured sources (idempotent)."""
    _boot()
    from vehicle_finder.pipeline import run_fetch

    summary = run_fetch(source=source, search=search, dry_run=dry_run)
    typer.echo(summary.render())


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8000),
    reload: bool = typer.Option(False),
) -> None:
    """Start the local web UI."""
    _boot()
    import uvicorn

    uvicorn.run("vehicle_finder.web.app:app", host=host, port=port, reload=reload)


@app.command()
def export(
    fmt: str = typer.Option("json", "--format", help="json or csv."),
    out: str = typer.Option("data/exports/export", help="Output path (without extension)."),
) -> None:
    """Export normalized listings + history to CSV or JSON."""
    _boot()
    from vehicle_finder.exporting import export_listings

    path = export_listings(fmt=fmt, out=out)
    typer.echo(f"Exported to {path}")


@app.command(name="import-url")
def import_url(url: str = typer.Argument(..., help="A single listing URL to import.")) -> None:
    """Import one listing from a pasted URL (Marktplaats listing pages, etc.)."""
    _boot()
    from vehicle_finder.sources.url_import import ImportNotAllowedError, import_single_url

    try:
        listing = import_single_url(url)
    except ImportNotAllowedError as exc:
        typer.secho(str(exc), fg=typer.colors.YELLOW)
        raise typer.Exit(1) from exc
    typer.echo(f"Imported: {listing.title} ({listing.source})")


@app.command(name="add-manual")
def add_manual(
    file: str = typer.Option(..., "--file", help="JSON file with listing fields."),
) -> None:
    """Add a hand-entered listing from a JSON file (mobile.de fallback, etc.)."""
    _boot()
    from vehicle_finder.sources.manual import add_manual_listing, load_manual_input

    listing = add_manual_listing(load_manual_input(file))
    typer.echo(f"Added: {listing.title} ({listing.source})")


@app.command()
def diagnostics() -> None:
    """Show per-source health: last fetch, counts, parse failures, layout drift."""
    _boot()
    from vehicle_finder.diagnostics import render_diagnostics

    typer.echo(render_diagnostics())


@app.command(name="init-db")
def init_db() -> None:
    """Create the SQLite schema if it does not exist."""
    _boot()
    from vehicle_finder.persistence.db import init_database

    init_database()
    typer.echo("Database initialized.")


if __name__ == "__main__":
    app()
