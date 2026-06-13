"""dasimport.nl adapter — polite server-rendered HTML.

A single importer of German cars to NL. ``robots.txt`` permits ``/aanbod``. Filters are
query-string with numeric brand/model IDs (config ``source_codes.dasimport``). Listing
cards (``.di-car-item``) carry title, price (schema.org microdata), build date, mileage
and fuel. Prices are **already NL-landed (incl. BPM/import)** — flagged so the German
import-cost module does not double-count.
"""

from __future__ import annotations

import re

from selectolax.parser import HTMLParser, Node

from vehicle_finder.configio import SearchTarget, load_sources
from vehicle_finder.logging import get_logger
from vehicle_finder.models.enums import SellerType, VehicleType
from vehicle_finder.models.listing import VehicleListing
from vehicle_finder.models.values import DataQuality
from vehicle_finder.normalize.equipment import EquipmentNormalizer
from vehicle_finder.normalize.fields import normalize_fuel, parse_int, parse_iso_date
from vehicle_finder.sources.base import FetchResult, register
from vehicle_finder.sources.http import PoliteClient

log = get_logger("dasimport")

MAX_PAGES = 40
_ID_RE = re.compile(r"importeren-(\d+)")
_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{4})\b")  # build date MM/YYYY
_PRICE_INCL_RE = re.compile(r"([\d.]+)\s*incl", re.IGNORECASE)


def _spec_texts(card: Node) -> list[str]:
    return [re.sub(r"\s+", " ", n.text()).strip() for n in card.css(".di-car-info .di-car-spec")]


def _extract_build_date(specs: list[str]) -> tuple[str | None, int | None]:
    for s in specs:
        m = _DATE_RE.search(s)
        if m:
            return f"{m.group(2)}-{int(m.group(1)):02d}", int(m.group(2))
    return None, None


def _extract_mileage(specs: list[str]) -> int | None:
    for s in specs:
        if re.fullmatch(r"[\d.\s ]+", s) and not _DATE_RE.search(s):
            return parse_int(s)
    return None


def _extract_fuel_text(specs: list[str]) -> str | None:
    for s in specs:
        if re.search(r"[A-Za-z]", s) and "/" not in s[:3]:
            return s
    return None


def parse_card(card: Node, base_url: str, search_id: str | None = None) -> VehicleListing | None:
    """Parse one ``.di-car-item`` card into a normalized listing. Pure; fixture-tested."""
    link = card.css_first('a[href*="importeren-"]')
    href = link.attributes.get("href") if link else None
    if not href:
        return None
    id_match = _ID_RE.search(href)
    if not id_match:
        return None
    listing_id = id_match.group(1)
    url = href if href.startswith("http") else f"{base_url}{href}"

    title_node = card.css_first(".di-car-title")
    title = re.sub(r"\s+", " ", title_node.text()).strip() if title_node else "BMW"
    tokens = title.split()
    make = tokens[0] if tokens else "BMW"
    model = tokens[1] if len(tokens) > 1 else None
    variant = " ".join(tokens[2:]) or None if len(tokens) > 2 else None

    specs = _spec_texts(card)
    build_iso, year = _extract_build_date(specs)
    mileage = _extract_mileage(specs)
    fuel_text = _extract_fuel_text(specs)

    # Price: prefer the visible NL-landed figure ("X incl. BPM…"); fall back to microdata.
    price: int | None = None
    price_node = card.css_first(".di-car-price")
    if price_node:
        m = _PRICE_INCL_RE.search(re.sub(r"\s+", " ", price_node.text()))
        if m:
            price = parse_int(m.group(1))
    if price is None:
        meta = card.css_first("meta[itemprop=price]")
        price = parse_int(meta.attributes.get("content")) if meta else None

    img = card.css_first(".di-car-image img") or card.css_first("img")
    image = (img.attributes.get("src") or img.attributes.get("data-src")) if img else None

    dq = DataQuality()
    if price is None:
        dq.warnings.append("price missing")
    if mileage is None:
        dq.warnings.append("mileage missing")

    listing = VehicleListing(
        vehicle_type=VehicleType.CAR,
        source="dasimport",
        source_listing_id=listing_id,
        url=url,
        title=title,
        make=make,
        model=model,
        variant=variant,
        model_year=year,
        registration_date=parse_iso_date(build_iso),
        build_date=parse_iso_date(build_iso),  # dasimport's card date is the build year
        mileage_km=mileage,
        price=price,
        currency="EUR",
        seller_type=SellerType.DEALER,
        seller_name="via dasimport.nl",
        country="NL",  # already imported & landed; no German-import penalty
        vat_status="nl_landed_incl_bpm",
        fuel_type=normalize_fuel(fuel_text),
        image_urls=[image] if image else [],
        search_id=search_id,
    )
    listing.set_features(EquipmentNormalizer().normalize_text(title, source="dasimport"))
    listing.set_data_quality(dq)
    return listing


def parse_html(
    html: str, base_url: str, search_id: str | None = None
) -> tuple[list[VehicleListing], int, int, list[str], bool]:
    """Parse a results page. Returns (listings, found, failures, warnings, layout_changed)."""
    cards = HTMLParser(html).css(".di-car-item")
    if not cards:
        # No cards: either a genuinely empty result or a layout change. Flag if the page
        # clearly rendered something else substantial.
        layout = "di-car-item" not in html and len(html) > 2000
        return [], 0, 0, (["no .di-car-item cards found"] if layout else []), layout

    listings: list[VehicleListing] = []
    failures = 0
    warnings: list[str] = []
    for card in cards:
        try:
            parsed = parse_card(card, base_url, search_id)
        except Exception as exc:
            failures += 1
            warnings.append(f"card parse error: {exc}")
            continue
        if parsed is None:
            failures += 1
        else:
            listings.append(parsed)
    return listings, len(cards), failures, warnings, False


class DasImportAdapter:
    id = "dasimport"

    def __init__(self, base_url: str, request_uri: str = "/aanbod") -> None:
        self.base_url = base_url.rstrip("/")
        self.request_uri = request_uri

    def supports(self, target: SearchTarget) -> bool:
        return target.vehicle_type is VehicleType.CAR and bool(
            target.codes_for(self.id).get("brand")
        )

    def _params(self, target: SearchTarget, page: int) -> dict[str, str]:
        codes = target.codes_for(self.id)
        params: dict[str, str] = {
            "business": "0",
            "buy": "1",
            "brand": str(codes["brand"]),
            "power": "PK",
            "page": str(page),
        }
        if codes.get("model"):
            params["model"] = str(codes["model"])
        if target.min_year:
            params["year_s"] = str(target.min_year)
        if target.max_year:
            params["year_e"] = str(target.max_year)
        if target.max_price:
            params["price_e"] = str(target.max_price)
        if target.max_mileage:
            params["km_e"] = str(target.max_mileage)
        return params

    def _passes(self, target: SearchTarget, listing: VehicleListing) -> bool:
        if not target.variant_allowed(f"{listing.variant or ''} {listing.title or ''}"):
            return False
        if target.min_year and listing.model_year and listing.model_year < target.min_year:
            return False
        if target.max_year and listing.model_year and listing.model_year > target.max_year:
            return False
        if target.max_mileage and listing.mileage_km and listing.mileage_km > target.max_mileage:
            return False
        return not (target.max_price and listing.price and listing.price > target.max_price)

    def fetch(self, target: SearchTarget, client: PoliteClient) -> FetchResult:
        result = FetchResult()
        if not target.codes_for(self.id).get("brand"):
            result.warnings.append(f"dasimport: no source_codes.brand for '{target.id}'")
            return result

        seen: set[str] = set()
        url = f"{self.base_url}{self.request_uri}"
        for page in range(1, MAX_PAGES + 1):
            resp = client.request("GET", url, params=self._params(target, page))
            listings, found, failures, warnings, layout = parse_html(
                resp.text, self.base_url, target.id
            )
            result.warnings.extend(f"p{page}: {w}" for w in warnings)
            result.layout_changed = result.layout_changed or layout
            if not listings:
                break
            fresh = [x for x in listings if x.source_listing_id not in seen]
            if not fresh:
                break
            for x in fresh:
                seen.add(x.source_listing_id)
                if self._passes(target, x):
                    result.listings.append(x)
            result.found += found
            result.parse_failures += failures

        log.info(
            "dasimport_fetch_done", search=target.id, kept=len(result.listings), seen=len(seen)
        )
        return result


def register_adapters() -> None:
    """Register a dasimport adapter for every config source with adapter == 'dasimport'."""
    for _source_id, cfg in load_sources().items():
        if cfg.adapter != "dasimport" or not cfg.enabled:
            continue
        register(DasImportAdapter(cfg.base_url, cfg.request_uri or "/aanbod"))
