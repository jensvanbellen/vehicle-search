"""FastAPI application — group-centric UI.

Dashboard, consolidated-vehicle table (one row per group), group detail, side-by-side
comparison, source diagnostics, and shortlist/reject/notes actions. All data is read
from the local DB; nothing here fetches the network.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from vehicle_finder import __version__
from vehicle_finder.diagnostics import source_diagnostics
from vehicle_finder.persistence.db import session_scope
from vehicle_finder.persistence.userstate import set_notes, set_rejected, set_shortlist
from vehicle_finder.web.views import (
    active_group_views,
    dashboard_data,
    group_detail_view,
)

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

app = FastAPI(title="Vehicle Finder", version=__version__)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


_SORTS: dict[str, Callable[[dict[str, Any]], tuple[bool, float]]] = {
    "score": lambda v: (v["score"] is not None, v["score"] or 0),
    "price": lambda v: (v["price"] is None, v["price"] or 0),
    "year": lambda v: (v["model_year"] is not None, v["model_year"] or 0),
    "distance": lambda v: (v["distance_km"] is None, v["distance_km"] or 0),
}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    with session_scope() as session:
        data = dashboard_data(session)
        diagnostics = source_diagnostics()
    return _TEMPLATES.TemplateResponse(
        request, "dashboard.html", {"d": data, "diagnostics": diagnostics}
    )


@app.get("/listings", response_class=HTMLResponse)
def listings(
    request: Request,
    q: str | None = None,
    source: str | None = None,
    vtype: str | None = None,
    sort: str = "score",
    show_rejected: bool = False,
) -> HTMLResponse:
    with session_scope() as session:
        views = active_group_views(session)

    sources = sorted({s for v in views for s in v["sources"]})
    if not show_rejected:
        views = [v for v in views if not v["rejected"]]
    if q:
        needle = q.lower()
        views = [v for v in views if needle in f"{v['make']} {v['model']}".lower()]
    if source:
        views = [v for v in views if source in v["sources"]]
    if vtype:
        views = [v for v in views if v["vehicle_type"] == vtype]

    views.sort(key=_SORTS.get(sort, _SORTS["score"]), reverse=sort in ("score", "year"))
    context: dict[str, Any] = {
        "groups": views,
        "count": len(views),
        "q": q or "",
        "source": source or "",
        "vtype": vtype or "",
        "sort": sort,
        "sources": sources,
        "show_rejected": show_rejected,
    }
    return _TEMPLATES.TemplateResponse(request, "listings.html", context)


@app.get("/group/{group_id}", response_class=HTMLResponse)
def group_detail(request: Request, group_id: str) -> HTMLResponse:
    with session_scope() as session:
        view = group_detail_view(session, group_id)
    if view is None:
        return HTMLResponse("<h1>404 — vehicle not found</h1>", status_code=404)
    return _TEMPLATES.TemplateResponse(request, "detail.html", {"v": view})


@app.get("/compare", response_class=HTMLResponse)
def compare(request: Request, ids: str = "") -> HTMLResponse:
    group_ids = [g for g in ids.split(",") if g]
    with session_scope() as session:
        views = [v for gid in group_ids if (v := group_detail_view(session, gid))]
    return _TEMPLATES.TemplateResponse(request, "compare.html", {"vehicles": views})


@app.get("/diagnostics", response_class=HTMLResponse)
def diagnostics_page(request: Request) -> HTMLResponse:
    return _TEMPLATES.TemplateResponse(request, "diagnostics.html", {"rows": source_diagnostics()})


@app.post("/group/{group_id}/shortlist")
def toggle_shortlist(group_id: str, value: bool = Form(True)) -> RedirectResponse:
    with session_scope() as session:
        set_shortlist(session, group_id, value)
    return RedirectResponse(f"/group/{group_id}", status_code=303)


@app.post("/group/{group_id}/reject")
def toggle_reject(
    group_id: str, value: bool = Form(True), reason: str = Form("")
) -> RedirectResponse:
    with session_scope() as session:
        set_rejected(session, group_id, value, reason or None)
    return RedirectResponse(f"/group/{group_id}", status_code=303)


@app.post("/group/{group_id}/notes")
def save_notes(group_id: str, notes: str = Form("")) -> RedirectResponse:
    with session_scope() as session:
        set_notes(session, group_id, notes or None)
    return RedirectResponse(f"/group/{group_id}", status_code=303)
