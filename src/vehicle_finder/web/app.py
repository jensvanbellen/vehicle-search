"""FastAPI application: dashboard-lite listing table + detail page.

The vertical-slice UI. The full dashboard, comparison, filters and diagnostics views
arrive in milestone 7; routes here read straight from the local DB.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from vehicle_finder import __version__
from vehicle_finder.persistence.db import session_scope
from vehicle_finder.web.views import active_listing_views, listing_detail_view

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

app = FastAPI(title="Vehicle Finder", version=__version__)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


_SORTS: dict[str, Callable[[dict[str, Any]], tuple[bool, float]]] = {
    "score": lambda v: (v["score"] is not None, v["score"] or 0),
    "price": lambda v: (v["price"] is None, v["price"] or 0),
    "mileage": lambda v: (v["mileage_km"] is None, v["mileage_km"] or 0),
    "year": lambda v: (v["model_year"] is not None, v["model_year"] or 0),
}


@app.get("/", response_class=HTMLResponse)
def listings(
    request: Request,
    q: str | None = None,
    source: str | None = None,
    sort: str = "score",
) -> HTMLResponse:
    with session_scope() as session:
        views = active_listing_views(session)

    available_sources = sorted({v["source"] for v in views})
    if q:
        needle = q.lower()
        views = [v for v in views if needle in f"{v['title']} {v['description'] or ''}".lower()]
    if source:
        views = [v for v in views if v["source"] == source]

    reverse = sort in ("score", "year")
    views.sort(key=_SORTS.get(sort, _SORTS["score"]), reverse=reverse)

    context: dict[str, Any] = {
        "listings": views,
        "count": len(views),
        "q": q or "",
        "source": source or "",
        "sort": sort,
        "sources": available_sources,
    }
    return _TEMPLATES.TemplateResponse(request, "listings.html", context)


@app.get("/listing/{listing_id}", response_class=HTMLResponse)
def listing_detail(request: Request, listing_id: int) -> HTMLResponse:
    with session_scope() as session:
        view = listing_detail_view(session, listing_id)
    if view is None:
        return HTMLResponse("<h1>404 — listing not found</h1>", status_code=404)
    return _TEMPLATES.TemplateResponse(request, "detail.html", {"v": view})
