"""FastAPI application.

A minimal app now (a health route + placeholder home) so ``vehicle-search serve``
works end-to-end. The dashboard, listing table, detail, comparison and diagnostics
views are built out in milestone 7.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from vehicle_finder import __version__

app = FastAPI(title="Vehicle Finder", version=__version__)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return (
        "<!doctype html><html><head><title>Vehicle Finder</title></head>"
        "<body style='font-family:system-ui;max-width:40rem;margin:4rem auto'>"
        "<h1>Vehicle Finder</h1>"
        "<p>Local used car &amp; motorcycle finder. The full UI lands in milestone 7.</p>"
        "<p>See <code>docs/architecture.md</code>.</p>"
        "</body></html>"
    )
