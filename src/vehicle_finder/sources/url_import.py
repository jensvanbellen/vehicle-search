"""Single-URL listing import (e.g. a pasted Marktplaats listing page).

Robots-aware: before fetching, we consult the host's ``robots.txt`` and refuse any path
it disallows. This is what keeps us correct per-site without hard-coding rules:

* Marktplaats individual listing pages (``/v/…``, ``/a/…``) are allowed → imported.
  (Tracking params like ``c=`` / ``correlationId=`` are stripped first.)
* mobile.de listing pages are disallowed → refused, with a pointer to manual entry.

Parsing prefers schema.org JSON-LD, then Open Graph, then visible heuristics. The raw
HTML reference is retained for debugging.
"""

from __future__ import annotations

import json
import urllib.parse
from typing import Any, cast
from urllib.robotparser import RobotFileParser

from selectolax.parser import HTMLParser

from vehicle_finder.logging import get_logger
from vehicle_finder.models.enums import SellerType, VehicleType
from vehicle_finder.models.listing import VehicleListing
from vehicle_finder.normalize.equipment import EquipmentNormalizer
from vehicle_finder.normalize.fields import (
    normalize_colour,
    normalize_fuel,
    normalize_transmission,
    parse_int,
)
from vehicle_finder.sources.http import PoliteClient

log = get_logger("url_import")

_TRACKING_PARAMS = {
    "c",
    "correlationid",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "gclid",
    "fbclid",
}
_VEHICLE_LD_TYPES = {"car", "vehicle", "motorcycle", "product", "individualproduct"}
_MOTORCYCLE_HINTS = ("/motoren", "/motorrad", "motorcycle", "/motorbikes")


class ImportNotAllowedError(RuntimeError):
    """Raised when robots.txt disallows fetching the pasted URL."""


def clean_url(url: str) -> str:
    """Drop tracking query params; keep the canonical listing URL."""
    parts = urllib.parse.urlsplit(url)
    kept = [
        (k, v) for k, v in urllib.parse.parse_qsl(parts.query) if k.lower() not in _TRACKING_PARAMS
    ]
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(kept), "")
    )


def source_id_for(netloc: str) -> str:
    host = netloc.lower().removeprefix("www.")
    if "marktplaats" in host:
        return "marktplaats"
    if "mobile.de" in host:
        return "mobile-de"
    return f"url:{host}"


def _flatten_jsonld(data: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    stack: list[Any] = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, list):
            stack.extend(cast("list[Any]", node))
        elif isinstance(node, dict):
            d = cast("dict[str, Any]", node)
            out.append(d)
            if "@graph" in d:
                stack.append(d["@graph"])
    return out


def _jsonld_objects(tree: HTMLParser) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for node in tree.css('script[type="application/ld+json"]'):
        raw = node.text()
        if not raw:
            continue
        try:
            objects.extend(_flatten_jsonld(json.loads(raw)))
        except (ValueError, TypeError):
            continue
    return objects


def _ld_type(obj: dict[str, Any]) -> str:
    t = obj.get("@type", "")
    if isinstance(t, list):
        return " ".join(str(x) for x in cast("list[Any]", t)).lower()
    return str(t).lower()


def _og(tree: HTMLParser, prop: str) -> str | None:
    node = tree.css_first(f'meta[property="{prop}"]') or tree.css_first(f'meta[name="{prop}"]')
    return node.attributes.get("content") if node else None


def _nested_price(offers: Any) -> int | None:
    objs: list[Any] = cast("list[Any]", offers) if isinstance(offers, list) else [offers]
    for o in objs:
        if isinstance(o, dict):
            od = cast("dict[str, Any]", o)
            price = od.get("price") or od.get("lowPrice")
            if price is None and isinstance(od.get("priceSpecification"), dict):
                price = cast("dict[str, Any]", od["priceSpecification"]).get("price")
            parsed = parse_int(price)
            if parsed is not None:
                return parsed
    return None


def parse_listing_html(html: str, url: str, source_id: str) -> VehicleListing:
    """Extract a normalized listing from a single listing page (JSON-LD → OG → heuristics)."""
    tree = HTMLParser(html)
    vehicle_type = (
        VehicleType.MOTORCYCLE
        if any(h in url.lower() for h in _MOTORCYCLE_HINTS)
        else VehicleType.CAR
    )

    title: str | None = None
    make: str | None = None
    model: str | None = None
    price: int | None = None
    mileage: int | None = None
    year: int | None = None
    colour: str | None = None
    fuel: str | None = None
    transmission: str | None = None
    images: list[str] = []
    description: str | None = None

    for obj in _jsonld_objects(tree):
        if not (_VEHICLE_LD_TYPES & set(_ld_type(obj).split())):
            continue
        title = title or (str(obj["name"]) if obj.get("name") else None)
        brand = obj.get("brand")
        if isinstance(brand, dict):
            make = make or cast("dict[str, Any]", brand).get("name")
        elif isinstance(brand, str):
            make = make or brand
        model = model or (str(obj["model"]) if obj.get("model") else None)
        if "motorcycle" in _ld_type(obj):
            vehicle_type = VehicleType.MOTORCYCLE
        price = price or _nested_price(obj.get("offers"))
        odo = obj.get("mileageFromOdometer")
        if isinstance(odo, dict):
            mileage = mileage or parse_int(cast("dict[str, Any]", odo).get("value"))
        else:
            mileage = mileage or parse_int(odo)
        year = year or parse_int(
            obj.get("vehicleModelDate") or obj.get("productionDate") or obj.get("modelDate")
        )
        colour = colour or (str(obj["color"]) if obj.get("color") else None)
        fuel = fuel or (str(obj["fuelType"]) if obj.get("fuelType") else None)
        transmission = transmission or (
            str(obj["vehicleTransmission"]) if obj.get("vehicleTransmission") else None
        )
        description = description or (str(obj["description"]) if obj.get("description") else None)
        img = obj.get("image")
        if isinstance(img, list):
            images.extend(str(x) for x in cast("list[Any]", img))
        elif isinstance(img, str):
            images.append(img)

    # Open Graph fallbacks.
    title = title or _og(tree, "og:title")
    if not images:
        og_img = _og(tree, "og:image")
        if og_img:
            images.append(og_img)
    if price is None:
        price = parse_int(_og(tree, "product:price:amount"))
    description = description or _og(tree, "og:description")

    listing_id = clean_url(url).rstrip("/").rsplit("/", 1)[-1] or clean_url(url)
    listing = VehicleListing(
        vehicle_type=vehicle_type,
        source=source_id,
        source_listing_id=listing_id,
        url=clean_url(url),
        title=title or "Imported listing",
        make=make,
        model=model,
        model_year=year,
        mileage_km=mileage,
        price=price,
        currency="EUR",
        seller_type=SellerType.UNKNOWN,
        colour=normalize_colour(colour) or colour,
        fuel_type=normalize_fuel(fuel),
        transmission=normalize_transmission(transmission),
        description=description,
        raw_options_text=description,
        image_urls=images,
    )
    listing.set_features(EquipmentNormalizer().normalize_text(description, source=source_id))
    return listing


def _robots_allows(client: PoliteClient, url: str, user_agent: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    try:
        resp = client.request("GET", robots_url)
    except Exception:
        return False
    if resp.status_code != 200:
        return True  # no robots.txt published => allowed
    rp = RobotFileParser()
    rp.parse(resp.text.splitlines())
    return rp.can_fetch(user_agent, url) or rp.can_fetch("*", url)


def import_single_url(url: str, client: PoliteClient | None = None) -> VehicleListing:
    """Fetch one allowed listing page, parse it, and persist it. Live (interactive)."""
    from vehicle_finder.persistence.db import session_scope
    from vehicle_finder.persistence.repository import upsert_listing

    owns_client = client is None
    client = client or PoliteClient()
    try:
        cleaned = clean_url(url)
        source_id = source_id_for(urllib.parse.urlsplit(cleaned).netloc)
        if source_id == "mobile-de":
            raise ImportNotAllowedError(
                "mobile.de disallows automated fetching of listing pages. "
                "Use `vehicle-search add-manual` (paste the saved page's fields) instead."
            )
        if not _robots_allows(client, cleaned, client.settings.user_agent):
            raise ImportNotAllowedError(
                f"robots.txt disallows fetching {cleaned}. Use `vehicle-search add-manual` instead."
            )
        resp = client.request("GET", cleaned)
        listing = parse_listing_html(resp.text, cleaned, source_id)
        with session_scope() as session:
            upsert_listing(session, listing)
        log.info("url_imported", source=source_id, title=listing.title)
        return listing
    finally:
        if owns_client:
            client.close()
