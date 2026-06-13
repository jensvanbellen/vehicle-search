"""RDW (Dutch vehicle registry) open-data enrichment.

Free, official, no auth: by kenteken, the RDW Open Data API returns authoritative
first-registration date, an odometer-reading judgement (``tellerstandoordeel`` =
plausible/implausible — a fraud signal), registered colour, catalogue price, gross BPM,
and recall/export flags. This is exactly the kind of verification the listings can't
self-report. Only NL-plated listings are looked up.
"""

from __future__ import annotations

import re
from typing import Any, cast

from sqlmodel import Session, select

from vehicle_finder.config import Settings, get_settings
from vehicle_finder.logging import get_logger
from vehicle_finder.models.enums import ListingStatus
from vehicle_finder.models.listing import VehicleListing
from vehicle_finder.normalize.fields import normalize_colour, parse_int
from vehicle_finder.sources.http import PoliteClient

log = get_logger("rdw")

RDW_RESOURCE = "https://opendata.rdw.nl/resource/m9d7-ebf2.json"


def normalize_plate(kenteken: str | None) -> str:
    """RDW keys plates uppercase with no separators (e.g. '53-MX-FD' -> '53MXFD')."""
    return re.sub(r"[^A-Za-z0-9]", "", kenteken or "").upper()


def _date_from(rec: dict[str, Any], compact_key: str) -> str | None:
    """Parse an RDW date (prefers the ISO ``*_dt`` companion, else 'YYYYMMDD')."""
    iso = rec.get(f"{compact_key}_dt")
    if isinstance(iso, str) and "T" in iso:
        return iso.split("T", 1)[0]
    raw = str(rec.get(compact_key) or "")
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
    return None


def parse_rdw_record(rec: dict[str, Any]) -> dict[str, Any]:
    """Extract the useful, verified fields from one RDW record. Pure; fixture-tested."""
    colour_raw = str(rec.get("eerste_kleur") or "").strip()
    colour = (
        colour_raw
        if colour_raw and colour_raw.lower() not in ("n.v.t.", "niet geregistreerd")
        else None
    )
    judgement = str(rec.get("tellerstandoordeel") or "").strip() or None
    out: dict[str, Any] = {
        "verified": True,
        "make": rec.get("merk"),
        "trade_name": rec.get("handelsbenaming"),
        "first_admission": _date_from(rec, "datum_eerste_toelating"),
        "first_nl_registration": _date_from(rec, "datum_eerste_tenaamstelling_in_nederland"),
        "odometer_judgement": judgement,
        "colour": normalize_colour(colour) or colour,
        "catalogue_price": parse_int(rec.get("catalogusprijs")),
        "gross_bpm": parse_int(rec.get("bruto_bpm")),
        "recall_open": str(rec.get("openstaande_terugroepactie_indicator") or "").lower() == "ja",
        "exported": str(rec.get("export_indicator") or "").lower() == "ja",
        "apk_expiry": _date_from(rec, "vervaldatum_apk"),
    }
    return {k: v for k, v in out.items() if v is not None}


def odometer_is_implausible(rdw: dict[str, Any]) -> bool:
    return str(rdw.get("odometer_judgement", "")).lower() == "onlogisch"


def lookup_kenteken(plate: str, client: PoliteClient) -> dict[str, Any] | None:
    """Fetch + parse one plate from RDW. Returns None if not found / on error."""
    normalized = normalize_plate(plate)
    if not normalized:
        return None
    try:
        resp = client.request("GET", RDW_RESOURCE, params={"kenteken": normalized})
        records = resp.json()
    except Exception as exc:
        log.warning("rdw_lookup_failed", plate=normalized, error=str(exc))
        return None
    if not isinstance(records, list) or not records:
        return None
    first = cast("list[Any]", records)[0]
    return parse_rdw_record(cast("dict[str, Any]", first)) if isinstance(first, dict) else None


def enrich_listings(
    session: Session, client: PoliteClient | None = None, settings: Settings | None = None
) -> int:
    """Look up RDW data for active NL-plated listings that lack it. Returns count enriched."""
    settings = settings or get_settings()
    if not settings.rdw_enabled:
        return 0
    pending = [
        x
        for x in session.exec(
            select(VehicleListing).where(VehicleListing.status == ListingStatus.ACTIVE)
        ).all()
        if x.kenteken and not x.rdw
    ]
    if not pending:
        return 0
    owns = client is None
    client = client or PoliteClient(settings, min_delay=1.0)
    enriched = 0
    try:
        for listing in pending:
            data = lookup_kenteken(listing.kenteken or "", client)
            if data:
                listing.rdw = data
                if odometer_is_implausible(data):
                    dq = listing.get_data_quality()
                    dq.warnings.append("RDW odometer judgement: implausible (possible clock issue)")
                    listing.set_data_quality(dq)
                session.add(listing)
                enriched += 1
    finally:
        if owns:
            client.close()
    log.info("rdw_enriched", count=enriched, considered=len(pending))
    return enriched
