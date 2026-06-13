"""bmw.de Gebrauchtwagen adapter — fixtures + Playwright live transport.

bmw.de is a modern SPA. ``robots.txt`` is permissive (sitemap only), but the site's
WAF blocks non-browser clients (and this build environment entirely). So:

* The **filter encoder and offers parser are pure and fully unit-tested against a
  saved fixture** — interface + parsing are complete regardless of this environment.
* The **live transport is Playwright** (a real browser is genuinely required), run
  polite / non-headless / low-rate, to be verified on the user's NL network.
* **Escalation guardrail:** if a polite browser still hits a bot challenge / interstitial,
  we STOP and treat bmw.de as URL-import only. We do NOT rotate proxies or spoof
  fingerprints.

The internal offers-JSON field names could not be observed from here, so
:func:`parse_offers` is intentionally **tolerant** (multi-candidate key lookup) and the
representative fixture mirrors the documented filter format. Validate field mappings
against a real capture on first live run (the transport dumps raw payloads to
``data/raw/`` for exactly this purpose).
"""

from __future__ import annotations

import json
import urllib.parse
from typing import Any, cast

from vehicle_finder.config import REPO_ROOT, get_settings
from vehicle_finder.configio import SearchTarget, load_sources
from vehicle_finder.logging import get_logger
from vehicle_finder.models.enums import SellerType, VehicleType
from vehicle_finder.models.listing import VehicleListing
from vehicle_finder.models.values import DataQuality
from vehicle_finder.normalize.equipment import EquipmentNormalizer
from vehicle_finder.normalize.fields import (
    normalize_colour,
    normalize_fuel,
    normalize_transmission,
    parse_int,
    parse_iso_date,
)
from vehicle_finder.sources.base import FetchResult, register
from vehicle_finder.sources.http import PoliteClient

log = get_logger("bmw_de")

_SCROLL_STEPS = 6  # lazy-load passes after consent
# Cookie-consent accept buttons (German). Accepting cookies is a normal user action.
_CONSENT_SELECTORS = (
    'button:has-text("Akzeptieren")',
    'button:has-text("Alle akzeptieren")',
    'button:has-text("Zustimmen")',
    "#onetrust-accept-btn-handler",
)

# Markers that indicate an anti-bot interstitial — when seen, STOP (no escalation).
_CHALLENGE_MARKERS = (
    "just a moment",
    "captcha",
    "access denied",
    "challenge-platform",
    "pardon our interruption",
    "are you a human",
    "reference #",  # Akamai
)
# Keys that mark a JSON record as a vehicle offer (used to locate the offers list).
_OFFER_HINT_KEYS = {
    "price",
    "grossPrice",
    "priceAmount",
    "mileage",
    "mileageKm",
    "firstRegistration",
    "registrationDate",
    "powerHp",
    "powerInHp",
    "fuelType",
    "marketingModelRange",
    "modelName",
    "vehicleId",
    "offerId",
}


def build_filter_param(marketing_range: str, min_year: int | None, max_year: int | None) -> str:
    """Build the double-URL-encoded JSON ``filters`` param (verified vs the live format)."""
    obj: dict[str, Any] = {"MARKETING_MODEL_RANGE": [marketing_range], "IS_INSTALLMENT": False}
    if min_year or max_year:
        obj["REGISTRATION_YEAR"] = [min_year or 1990, max_year or 2100]
    inner = json.dumps(obj, separators=(",", ":"))
    return urllib.parse.quote(urllib.parse.quote(inner, safe=""), safe="")


def build_results_url(base_url: str, request_uri: str, filter_param: str) -> str:
    return (
        f"{base_url.rstrip('/')}{request_uri}?filters={filter_param}&sorting=SORT_ORDER_PRICE_ASC"
    )


def looks_like_challenge(title: str, html: str) -> bool:
    """True if the page looks like an anti-bot interstitial rather than results."""
    haystack = f"{title} {html[:4000]}".lower()
    return any(marker in haystack for marker in _CHALLENGE_MARKERS)


def _g(rec: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in rec and rec[k] not in (None, ""):
            return rec[k]
    return None


def _amount(value: Any) -> int | None:
    """Extract an integer amount from a scalar or a nested {amount|value} object."""
    if isinstance(value, dict):
        value = _g(cast("dict[str, Any]", value), "amount", "value", "gross", "price")
    return parse_int(value)


def _find_offer_list(data: Any) -> list[dict[str, Any]]:
    """Recursively locate the most offer-like list of dicts in an arbitrary payload."""
    best: list[dict[str, Any]] = []
    stack: list[Any] = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            stack.extend(cast("dict[str, Any]", node).values())
        elif isinstance(node, list):
            items = cast("list[Any]", node)
            dicts: list[dict[str, Any]] = [
                cast("dict[str, Any]", x) for x in items if isinstance(x, dict)
            ]
            if (
                dicts
                and len(dicts) > len(best)
                and any(_OFFER_HINT_KEYS & set(d.keys()) for d in dicts)
            ):
                best = dicts
            stack.extend(items)
    return best


def parse_offer(rec: dict[str, Any], base_url: str, search_id: str | None) -> VehicleListing | None:
    """Map one offer record to a normalized listing (tolerant of unknown field names)."""
    vid = _g(rec, "vehicleId", "offerId", "id")
    if vid is None:
        return None
    vid = str(vid)

    reg_raw = _g(rec, "firstRegistration", "registrationDate", "registration")
    reg_date = parse_iso_date(reg_raw)
    year = reg_date.year if reg_date else parse_int(_g(rec, "modelYear", "year"))

    model = _g(rec, "modelName", "marketingModelRange", "model")
    title = _g(rec, "title", "name") or f"BMW {model or ''}".strip()
    detail = _g(rec, "detailPageUrl", "url", "href")
    url = (
        (detail if str(detail).startswith("http") else f"{base_url}{detail}")
        if detail
        else f"{base_url}/de-de/sl/gebrauchtwagen/details/{vid}"
    )

    images_raw: Any = _g(rec, "images", "imageUrls", "media") or []
    images: list[str] = []
    if isinstance(images_raw, list):
        for item in cast("list[Any]", images_raw):
            if isinstance(item, str):
                images.append(item)
            elif isinstance(item, dict):
                u = _g(cast("dict[str, Any]", item), "url", "src", "href")
                if u:
                    images.append(str(u))

    dq = DataQuality()
    price = _amount(_g(rec, "price", "grossPrice", "priceAmount"))
    mileage = parse_int(_g(rec, "mileage", "mileageKm", "mileageInKm"))
    if price is None:
        dq.warnings.append("price missing")
    if mileage is None:
        dq.warnings.append("mileage missing")

    desc = _g(rec, "description", "equipmentText", "optionsText")
    listing = VehicleListing(
        vehicle_type=VehicleType.CAR,
        source="bmw-de",
        source_listing_id=vid,
        url=url,
        title=str(title),
        make="BMW",
        model=str(model) if model else None,
        variant=_g(rec, "derivative", "engine", "trim"),
        model_year=year,
        registration_date=reg_date,
        mileage_km=mileage,
        price=price,
        currency=str(_g(rec, "currency") or "EUR"),
        seller_type=SellerType.DEALER,
        seller_name=_g(rec, "dealerName", "sellerName"),
        location=_g(rec, "dealerCity", "city", "location"),
        country="DE",  # physically in Germany -> import-cost module applies
        power_hp=parse_int(_g(rec, "powerHp", "powerInHp", "power")),
        power_kw=parse_int(_g(rec, "powerKw", "powerInKw")),
        colour=normalize_colour(_g(rec, "color", "colour", "exteriorColor")),
        fuel_type=normalize_fuel(_g(rec, "fuelType", "fuel")),
        transmission=normalize_transmission(_g(rec, "transmission", "gearbox")),
        description=str(desc) if desc else None,
        raw_options_text=str(desc) if desc else None,
        image_urls=images,
        raw_payload=rec,
        search_id=search_id,
    )
    text = " ".join(p for p in (listing.description, listing.title, listing.variant) if p)
    listing.set_features(EquipmentNormalizer().normalize_text(text, source="bmw-de"))
    listing.set_data_quality(dq)
    return listing


def parse_offers(
    data: Any, base_url: str, search_id: str | None = None
) -> tuple[list[VehicleListing], int, int, list[str], bool]:
    """Parse an offers payload. Returns (listings, found, failures, warnings, layout_changed)."""
    records = _find_offer_list(data)
    if not records:
        return [], 0, 0, ["no offer records found in payload"], True
    listings: list[VehicleListing] = []
    failures = 0
    warnings: list[str] = []
    for rec in records:
        try:
            parsed = parse_offer(rec, base_url, search_id)
        except Exception as exc:
            failures += 1
            warnings.append(f"offer parse error: {exc}")
            continue
        if parsed is None:
            failures += 1
        else:
            listings.append(parsed)
    return listings, len(records), failures, warnings, False


class BmwDeAdapter:
    id = "bmw-de"

    def __init__(self, base_url: str, request_uri: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.request_uri = request_uri

    def supports(self, target: SearchTarget) -> bool:
        return target.vehicle_type is VehicleType.CAR and bool(
            target.codes_for(self.id).get("marketing_model_range")
        )

    def fetch(self, target: SearchTarget, client: PoliteClient) -> FetchResult:
        """Live-fetch via Playwright. Disabled by default; verify on an NL network."""
        result = FetchResult()
        codes = target.codes_for(self.id)
        marketing_range = codes.get("marketing_model_range")
        if not marketing_range:
            result.warnings.append(
                f"bmw-de: no source_codes.marketing_model_range for '{target.id}'"
            )
            return result

        settings = get_settings()
        if not settings.bmwde_enabled:
            result.warnings.append(
                "bmw-de disabled (status: unverified in build env). "
                "Set VF_BMWDE_ENABLED=true on an NL network with `uv sync --extra browser`."
            )
            return result

        url = build_results_url(
            self.base_url,
            self.request_uri,
            build_filter_param(marketing_range, target.min_year, target.max_year),
        )
        try:
            payload, html, title = self._render(url, settings.playwright_headless)
        except RuntimeError as exc:
            result.warnings.append(str(exc))
            return result

        if looks_like_challenge(title, html):
            # Guardrail: stop here. Do NOT escalate to proxies/fingerprint spoofing.
            result.warnings.append(
                "bmw-de: bot challenge/interstitial detected — STOPPING. "
                "Use single-URL import instead; do not fight anti-bot."
            )
            return result
        if payload is None:
            result.warnings.append("bmw-de: no offers JSON captured (layout/API may have changed)")
            result.layout_changed = True
            return result

        listings, found, failures, warnings, layout = parse_offers(
            payload, self.base_url, target.id
        )
        result.listings = [x for x in listings if self._passes(target, x)]
        result.found = found
        result.parse_failures = failures
        result.warnings.extend(warnings)
        result.layout_changed = layout
        log.info("bmw_de_fetch_done", search=target.id, kept=len(result.listings), found=found)
        return result

    def _passes(self, target: SearchTarget, listing: VehicleListing) -> bool:
        if target.min_year and listing.model_year and listing.model_year < target.min_year:
            return False
        return not (target.max_year and listing.model_year and listing.model_year > target.max_year)

    def _render(self, url: str, headless: bool) -> tuple[Any, str, str]:
        """Drive a real browser (accept consent, scroll to lazy-load), capturing the offers
        JSON. Returns (payload, html, title). Raises RuntimeError on a missing browser binary.

        bmw.de is a SPA backed by BMW's STOLO API (``stolo-data-service…/vehiclesearch/…``);
        a cookie-consent overlay gates content, so we accept it before scrolling.
        """
        from playwright.sync_api import Response, sync_playwright

        captured: list[dict[str, Any]] = []

        def _on_response(response: Response) -> None:
            if "json" not in response.headers.get("content-type", ""):
                return
            low = response.url.lower()
            if not any(
                k in low
                for k in ("stolo", "offer", "search", "vehicle", "/sl/", "gebraucht", "inventory")
            ):
                return
            try:
                captured.append(cast("dict[str, Any]", response.json()))
            except Exception:
                return

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=headless)
                page = browser.new_page()
                page.on("response", _on_response)
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2500)
                self._accept_consent(page)
                for _ in range(_SCROLL_STEPS):
                    page.mouse.wheel(0, 4000)
                    page.wait_for_timeout(1200)
                html = page.content()
                title = page.title()
                browser.close()
        except Exception as exc:
            raise RuntimeError(
                f"bmw-de: browser run failed ({type(exc).__name__}). If Chromium is missing, "
                "run `uv run playwright install chromium`. Verify on an NL network."
            ) from exc

        # Dump raw captures so the real STOLO field names can be validated on first run.
        if captured:
            raw_dir = REPO_ROOT / "data" / "raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            (raw_dir / "bmwde_last_capture.json").write_text(
                json.dumps(captured, indent=1)[:2_000_000], encoding="utf-8"
            )

        best = max((c for c in captured), key=lambda c: len(_find_offer_list(c)), default=None)
        return best, html, title

    @staticmethod
    def _accept_consent(page: Any) -> None:
        """Click the cookie-consent accept button if present (legitimate, not anti-bot evasion)."""
        for selector in _CONSENT_SELECTORS:
            try:
                element = page.query_selector(selector)
                if element is not None:
                    element.click()
                    page.wait_for_timeout(1500)
                    return
            except Exception:
                continue


def register_adapters() -> None:
    for _source_id, cfg in load_sources().items():
        if cfg.adapter != "bmw_de" or not cfg.enabled:
            continue
        register(BmwDeAdapter(cfg.base_url, cfg.request_uri or "/de-de/sl/gebrauchtwagen/results"))
