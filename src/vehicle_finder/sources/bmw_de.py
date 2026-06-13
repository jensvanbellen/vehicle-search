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
from vehicle_finder.models.enums import Drivetrain, FeatureConfidence, SellerType, VehicleType
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
_MAX_SEARCH_PAGES = 10  # BMW returns 12 per page; equivalent to several "load more" clicks.
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


def build_filter_param(
    marketing_range: str,
    min_year: int | None,
    max_year: int | None,
    engine_type: str | None = None,
    max_mileage: int | None = None,
    equipment_groups: dict[str, list[str]] | None = None,
) -> str:
    """Build the double-URL-encoded JSON ``filters`` param (verified vs the live format)."""
    obj: dict[str, Any] = {"MARKETING_MODEL_RANGE": [marketing_range], "IS_INSTALLMENT": False}
    if engine_type:
        obj["ENGINE_TYPE"] = [engine_type]
    if max_mileage:
        obj["USED_CAR_MILEAGE"] = [0, max_mileage]
    if min_year or max_year:
        obj["REGISTRATION_YEAR"] = [min_year or 1990, max_year or 2100]
    if equipment_groups:
        obj["EQUIPMENT_GROUPS"] = equipment_groups
    inner = json.dumps(obj, separators=(",", ":"))
    return urllib.parse.quote(urllib.parse.quote(inner, safe=""), safe="")


def build_results_url(base_url: str, request_uri: str, filter_param: str) -> str:
    return (
        f"{base_url.rstrip('/')}{request_uri}?filters={filter_param}"
        "&sorting=SORT_ORDER_SF_OFFER_INSTALLMENT_ASC"
    )


def with_start_index(url: str, start_index: int) -> str:
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    query["startIndex"] = [str(start_index)]
    encoded = urllib.parse.urlencode(query, doseq=True)
    return urllib.parse.urlunparse(parsed._replace(query=encoded))


def _max_results(url: str) -> int:
    parsed = urllib.parse.urlparse(url)
    value = urllib.parse.parse_qs(parsed.query).get("maxResults", ["12"])[0]
    return parse_int(value) or 12


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
        value = _g(
            cast("dict[str, Any]", value),
            "amount",
            "value",
            "gross",
            "price",
            "grossSalesPrice",
            "netSalesPrice",
        )
    return parse_int(value)


def _localized(value: Any) -> str | None:
    """Pick the German/default text from BMW's localized label dictionaries."""
    if value in (None, ""):
        return None
    if isinstance(value, dict):
        mapping = cast("dict[str, Any]", value)
        for key in ("de_DE", "default_DE", "en_GB", "default_EN"):
            text = mapping.get(key)
            if text not in (None, ""):
                return str(text)
        for text in mapping.values():
            if text not in (None, ""):
                return str(text)
        return None
    return str(value)


def _nested(data: dict[str, Any], *keys: str) -> Any:
    node: Any = data
    for key in keys:
        if not isinstance(node, dict):
            return None
        node = cast("dict[str, Any]", node).get(key)
    return node


def _technical_value(technical: dict[str, Any], key: str) -> Any:
    raw = _nested(technical, "technicalData", "otdRawData")
    if not isinstance(raw, list):
        return None
    for item in cast("list[Any]", raw):
        if isinstance(item, dict):
            item_d = cast("dict[str, Any]", item)
            if item_d.get("key") == key:
                return item_d.get("value")
    return None


def _drivetrain(value: Any) -> Drivetrain:
    text = str(value or "").strip().upper()
    if text in {"ALL_WHEEL", "AWD", "XDRIVE"}:
        return Drivetrain.AWD
    if text in {"REAR_WHEEL", "RWD"}:
        return Drivetrain.RWD
    if text in {"FRONT_WHEEL", "FWD"}:
        return Drivetrain.FWD
    return Drivetrain.UNKNOWN


def _append_urls(value: Any, out: list[str]) -> None:
    if isinstance(value, str):
        if value.startswith("http") and value not in out:
            out.append(value)
    elif isinstance(value, dict):
        value_d = cast("dict[str, Any]", value)
        for key in ("url", "src", "href", "default"):
            _append_urls(value_d.get(key), out)
        if not any(key in value_d for key in ("url", "src", "href", "default")):
            for nested in value_d.values():
                _append_urls(nested, out)
    elif isinstance(value, list):
        for item in cast("list[Any]", value):
            _append_urls(item, out)


def _extract_images(rec: dict[str, Any]) -> list[str]:
    images: list[str] = []
    images_raw: Any = _g(rec, "images", "imageUrls")
    _append_urls(images_raw, images)
    media = rec.get("media")
    if isinstance(media, dict):
        media_d = cast("dict[str, Any]", media)
        for key in ("usedCarImageList", "usedCarImages", "cosyImages"):
            _append_urls(media_d.get(key), images)
    return images[:20]


def _equipment_names(equipments: Any) -> list[str]:
    if not isinstance(equipments, dict):
        return []
    names: list[str] = []
    for code, raw in cast("dict[str, Any]", equipments).items():
        if not isinstance(raw, dict):
            continue
        raw_d = cast("dict[str, Any]", raw)
        name = _localized(raw_d.get("name")) or _localized(
            _nested(raw_d, "marketingText", "salesText")
        )
        if name:
            names.append(name)
        else:
            names.append(code)
    return names


def _vss_parts(vss_config_id: Any) -> tuple[str | None, str | None, str | None, list[str]]:
    """Return (model_code, fabric, paint, option_codes) from a BMW vssConfigId string."""
    if not vss_config_id:
        return None, None, None, []
    head, _, rest = str(vss_config_id).partition(":")
    parts = [p for p in rest.split(",") if p]
    fabric = next((p for p in parts if p.startswith("F")), None)
    paint = next((p for p in parts if p.startswith("P")), None)
    options = [p for p in parts if p.startswith("S")]
    return head or None, fabric, paint, options


def _stolo_detail_url(rec: dict[str, Any], base_url: str) -> str:
    vid = str(rec["vssId"])
    vss_config_id = _nested(rec, "internal", "vssConfigId")
    model_code, fabric, paint, options = _vss_parts(vss_config_id)
    model_range = _localized(
        _nested(rec, "vehicleSpecification", "modelAndOption", "modelRange", "name")
    )
    params: dict[str, str] = {}
    if model_code:
        params["modelCode"] = model_code
    if paint:
        params["paint"] = paint
    if fabric:
        params["fabric"] = fabric
    if model_range:
        params["modelRangeCode"] = model_range
    if options:
        params["options"] = ",".join(options)
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    return f"{base_url}/de-de/sl/gebrauchtwagen/details/{vid}{query}"


def _accident_info(lifecycle: dict[str, Any]) -> str | None:
    damage = lifecycle.get("vehicleDamage")
    damage_d = cast("dict[str, Any]", damage) if isinstance(damage, dict) else {}
    involved = (
        lifecycle.get("involvedInAccident") is True
        or damage_d.get("involvedInAccident") is True
    )
    description = damage_d.get("damageDescription")
    repaired = damage_d.get("isRepaired")
    if not involved and not description:
        return None
    parts: list[str] = []
    if involved:
        parts.append("Accident history reported")
    if description:
        parts.append(str(description))
    if repaired is False:
        parts.append("not marked as repaired")
    return "; ".join(parts)


def _warranty(lifecycle: dict[str, Any]) -> str | None:
    warranty = lifecycle.get("warrantyInfo")
    program = lifecycle.get("usedCarProgram")
    if isinstance(warranty, dict):
        warranty_d = cast("dict[str, Any]", warranty)
        warranty_type = warranty_d.get("type") or program
        duration = warranty_d.get("duration")
        if warranty_type and duration:
            return f"{warranty_type} ({duration} months)"
        if warranty_type:
            return str(warranty_type)
    return str(program) if program else None


def _bmw_engine_type(target: SearchTarget, codes: dict[str, Any]) -> str | None:
    explicit = codes.get("engine_type")
    if explicit:
        return str(explicit)
    fuel = (target.fuel_type or "").strip().lower()
    return {
        "diesel": "DIESEL",
        "petrol": "PETROL",
        "benzine": "PETROL",
        "hybrid": "HYBRID",
        "plugin_hybrid": "PHEV",
        "plug-in hybrid": "PHEV",
        "electric": "ELECTRIC",
    }.get(fuel)


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


def _extract_records(data: Any) -> list[dict[str, Any]]:
    """Locate the offer records. STOLO returns ``{hits: [{country, score, vehicle:{...}}]}``
    so each car is nested under ``hit['vehicle']``; fall back to a generic deep search."""
    if isinstance(data, dict):
        hits = cast("dict[str, Any]", data).get("hits")
        if isinstance(hits, list):
            records: list[dict[str, Any]] = []
            for hit in cast("list[Any]", hits):
                if not isinstance(hit, dict):
                    continue
                hit_d = cast("dict[str, Any]", hit)
                vehicle = hit_d.get("vehicle")
                if isinstance(vehicle, dict):
                    records.append(cast("dict[str, Any]", vehicle))
            if records:
                return records
    return _find_offer_list(data)


def _combined_hits_payload(payloads: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Combine paged STOLO search payloads into one payload for the parser."""
    search_payloads = [p for p in payloads if isinstance(p.get("hits"), list)]
    if not search_payloads:
        return None

    combined = dict(search_payloads[0])
    hits: list[Any] = []
    seen: set[str] = set()
    for payload in search_payloads:
        for hit in cast("list[Any]", payload.get("hits") or []):
            if not isinstance(hit, dict):
                continue
            hit_d = cast("dict[str, Any]", hit)
            vehicle = hit_d.get("vehicle")
            key = None
            if isinstance(vehicle, dict):
                vehicle_d = cast("dict[str, Any]", vehicle)
                key = str(vehicle_d.get("vssId") or vehicle_d.get("documentId") or "")
            if not key:
                key = json.dumps(hit_d, sort_keys=True, default=str)
            if key in seen:
                continue
            seen.add(key)
            hits.append(hit_d)
    combined["hits"] = hits
    return combined


def _parse_stolo_vehicle(
    rec: dict[str, Any], base_url: str, search_id: str | None
) -> VehicleListing:
    """Map BMW STOLO ``hit['vehicle']`` records to our normalized listing model."""
    spec = _nested(rec, "vehicleSpecification", "modelAndOption")
    spec_d = cast("dict[str, Any]", spec) if isinstance(spec, dict) else {}
    technical = _nested(rec, "vehicleSpecification", "technicalAndEmission")
    technical_d = cast("dict[str, Any]", technical) if isinstance(technical, dict) else {}
    lifecycle = rec.get("vehicleLifeCycle")
    lifecycle_d = cast("dict[str, Any]", lifecycle) if isinstance(lifecycle, dict) else {}
    ordering = rec.get("ordering")
    ordering_d = cast("dict[str, Any]", ordering) if isinstance(ordering, dict) else {}
    retail = _nested(ordering_d, "retailData")
    retail_d = cast("dict[str, Any]", retail) if isinstance(retail, dict) else {}
    distribution = _nested(ordering_d, "distributionData")
    distribution_d = cast("dict[str, Any]", distribution) if isinstance(distribution, dict) else {}
    production = _nested(ordering_d, "productionData")
    production_d = cast("dict[str, Any]", production) if isinstance(production, dict) else {}
    price_d = cast("dict[str, Any]", rec.get("price")) if isinstance(rec.get("price"), dict) else {}

    model_info = spec_d.get("model")
    model_d = cast("dict[str, Any]", model_info) if isinstance(model_info, dict) else {}
    model_name = str(
        model_d.get("modelName")
        or _localized(model_d.get("modelDescription"))
        or _localized(_nested(spec_d, "modelRange", "description"))
        or "BMW"
    )
    model_range = _localized(_nested(spec_d, "modelRange", "description")) or model_name
    model = model_range.replace("BMW", "").strip() or model_name.split()[0]
    title = model_name if model_name.upper().startswith("BMW ") else f"BMW {model_name}"

    reg_date = parse_iso_date(
        retail_d.get("initialRegistrationDate")
        or _nested(technical_d, "registration", "date")
        or _g(rec, "firstRegistration", "registrationDate", "registration")
    )
    build_date = parse_iso_date(production_d.get("productionDate"))
    year = reg_date.year if reg_date else (build_date.year if build_date else None)

    mileage = parse_int(_nested(lifecycle_d, "mileage", "km"))
    if mileage is None:
        mileage = parse_int(_technical_value(technical_d, "mileage"))

    dealer = distribution_d.get("destinationLocationDomesticDealerName")
    dealer_city = distribution_d.get("locationOutletNickname")
    postal = _nested(retail_d, "locationOutletAddress", "postalCode")
    location_parts = [str(p) for p in (dealer_city, postal) if p]
    location = ", ".join(location_parts) if location_parts else None

    equipments = spec_d.get("equipments")
    option_names = _equipment_names(equipments)
    raw_options = ", ".join(option_names) if option_names else None

    dq = DataQuality()
    price = _amount(_g(price_d, "grossSalesPrice", "vehicleGrossPrice", "grossListPrice"))
    if price is None:
        price = _amount(_nested(rec, "pricing", "price", "value"))
    if price is None:
        dq.warnings.append("price missing")
    if mileage is None:
        dq.warnings.append("mileage missing")
    accident = _accident_info(lifecycle_d)
    if accident:
        dq.warnings.append("accident/damage history reported")

    listing = VehicleListing(
        vehicle_type=VehicleType.CAR,
        source="bmw-de",
        source_listing_id=str(rec["vssId"]),
        url=_stolo_detail_url(rec, base_url),
        title=title,
        make="BMW",
        model=model,
        variant=str(model_d.get("derivative") or model_name),
        model_year=year,
        registration_date=reg_date,
        build_date=build_date,
        mileage_km=mileage,
        price=price,
        currency=str(price_d.get("listPriceCurrency") or "EUR"),
        seller_type=SellerType.DEALER,
        seller_name=str(dealer) if dealer else None,
        location=location,
        country=str(rec.get("country") or "DE"),
        displacement_cc=parse_int(_nested(technical_d, "technicalData", "cylinderCapacity", "cm³"))
        or parse_int(_technical_value(technical_d, "C_HUBRAUM")),
        power_hp=parse_int(_technical_value(technical_d, "C_LEIST_GES_PS"))
        or parse_int(_technical_value(technical_d, "C_LEISTUNG_PS")),
        power_kw=parse_int(_technical_value(technical_d, "C_LEIST_GES"))
        or parse_int(_technical_value(technical_d, "C_LEISTUNG")),
        colour=normalize_colour(_localized(_nested(spec_d, "color", "clusterRough"))),
        owners=parse_int(lifecycle_d.get("numberOfPreviousOwners")),
        warranty=_warranty(lifecycle_d),
        accident_info=accident,
        vat_status="vat_deductible" if lifecycle_d.get("taxDeductible") is True else None,
        vin=production_d.get("vin17"),
        description=raw_options,
        raw_options_text=raw_options,
        image_urls=_extract_images(rec),
        raw_payload=rec,
        body_style=str(spec_d.get("bodyType")) if spec_d.get("bodyType") else None,
        doors=parse_int(_nested(technical_d, "technicalData", "doorCount")),
        seats=parse_int(_technical_value(technical_d, "N_SITZE")),
        transmission=normalize_transmission(spec_d.get("transmission")),
        drivetrain=_drivetrain(spec_d.get("driveType")),
        fuel_type=normalize_fuel(spec_d.get("baseFuelType")),
        co2_g_km=parse_int(_technical_value(technical_d, "V_CO2")),
        search_id=search_id,
    )
    text = " ".join(p for p in (listing.description, listing.title, listing.variant) if p)
    listing.set_features(
        EquipmentNormalizer().normalize_text(
            text, source="bmw-de", confidence=FeatureConfidence.HIGH
        )
    )
    listing.set_data_quality(dq)
    return listing


def parse_offer(rec: dict[str, Any], base_url: str, search_id: str | None) -> VehicleListing | None:
    """Map one offer record to a normalized listing (tolerant of unknown field names)."""
    if rec.get("vssId") and isinstance(rec.get("vehicleSpecification"), dict):
        return _parse_stolo_vehicle(rec, base_url, search_id)

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
    records = _extract_records(data)
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
            build_filter_param(
                marketing_range,
                target.min_year,
                target.max_year,
                engine_type=_bmw_engine_type(target, codes),
                max_mileage=parse_int(codes.get("max_mileage")) or target.max_mileage,
                equipment_groups=cast(
                    "dict[str, list[str]] | None", codes.get("equipment_groups")
                ),
            ),
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
        if target.max_year and listing.model_year and listing.model_year > target.max_year:
            return False
        if target.max_mileage and listing.mileage_km and listing.mileage_km > target.max_mileage:
            return False
        if target.min_price and listing.price and listing.price < target.min_price:
            return False
        if target.max_price and listing.price and listing.price > target.max_price:
            return False
        if target.fuel_type and listing.fuel_type:
            wanted = normalize_fuel(target.fuel_type)
            if wanted.value != "unknown" and listing.fuel_type != wanted:
                return False
        if not target.variant_allowed(f"{listing.variant or ''} {listing.title or ''}"):
            return False
        text = " ".join(
            p for p in (listing.title, listing.description, listing.raw_options_text) if p
        )
        if any(term.lower() in text.lower() for term in target.excluded_terms):
            return False
        excluded_colours = {c.lower() for c in target.excluded_colours}
        return not (listing.colour and listing.colour.lower() in excluded_colours)

    def _render(self, url: str, headless: bool) -> tuple[Any, str, str]:
        """Drive a real browser (accept consent, scroll to lazy-load), capturing the offers
        JSON. Returns (payload, html, title). Raises RuntimeError on a missing browser binary.

        bmw.de is a SPA backed by BMW's STOLO API (``stolo-data-service…/vehiclesearch/…``);
        a cookie-consent overlay gates content, so we accept it before scrolling.
        """
        from playwright.sync_api import Request, Response, sync_playwright

        captured: list[dict[str, Any]] = []
        search_requests: list[tuple[str, str]] = []

        def _on_request(request: Request) -> None:
            low = request.url.lower()
            if "stolo-data-service" not in low or "/vehiclesearch/search/" not in low:
                return
            post_data = request.post_data
            if request.method == "POST" and post_data:
                search_requests.append((request.url, post_data))

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
                page.on("request", _on_request)
                page.on("response", _on_response)
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2500)
                self._accept_consent(page)
                for _ in range(_SCROLL_STEPS):
                    page.mouse.wheel(0, 4000)
                    page.wait_for_timeout(1200)
                self._click_load_more_pages(page)
                self._fetch_additional_search_pages(page, search_requests, captured)
                html = page.content()
                title = page.title()
                browser.close()
        except Exception as exc:
            raise RuntimeError(
                f"bmw-de: browser run failed ({type(exc).__name__}). If Chromium is missing, "
                "run `uv run playwright install chromium`. Verify on an NL network."
            ) from exc

        # Dump raw captures so the real STOLO field names can be validated on first run.
        # NOTE: write the FULL valid JSON — never slice the string (that corrupts it).
        if captured:
            raw_dir = REPO_ROOT / "data" / "raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            (raw_dir / "bmwde_last_capture.json").write_text(
                json.dumps(captured, indent=1), encoding="utf-8"
            )

        best = _combined_hits_payload(captured) or max(
            (c for c in captured), key=lambda c: len(_extract_records(c)), default=None
        )
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

    @staticmethod
    def _fetch_additional_search_pages(
        page: Any, search_requests: list[tuple[str, str]], captured: list[dict[str, Any]]
    ) -> None:
        if not search_requests:
            return
        first_url, post_data = search_requests[-1]
        page_size = _max_results(first_url)
        if page_size <= 0:
            return
        for page_num in range(1, _MAX_SEARCH_PAGES):
            next_url = with_start_index(first_url, page_num * page_size)
            try:
                response = page.request.post(
                    next_url,
                    data=post_data,
                    headers={"content-type": "application/json"},
                    timeout=45000,
                )
                if not response.ok:
                    return
                body = response.json()
            except Exception:
                return
            if not isinstance(body, dict):
                return
            captured.append(cast("dict[str, Any]", body))
            records = _extract_records(body)
            if len(records) < page_size:
                return
            page.wait_for_timeout(800)

    @staticmethod
    def _click_load_more_pages(page: Any) -> None:
        for _ in range(_MAX_SEARCH_PAGES - 1):
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(800)
                button = page.locator('neo-button:has-text("Mehr anzeigen")').last
                if button.count() == 0:
                    button = page.get_by_text("Mehr anzeigen", exact=True).last
                if button.count() == 0 or not button.is_visible(timeout=1500):
                    return
                button.scroll_into_view_if_needed(timeout=5000)
                button.click(timeout=10000)
                page.wait_for_timeout(2500)
            except Exception:
                return


def register_adapters() -> None:
    for _source_id, cfg in load_sources().items():
        if cfg.adapter != "bmw_de" or not cfg.enabled:
            continue
        register(BmwDeAdapter(cfg.base_url, cfg.request_uri or "/de-de/sl/gebrauchtwagen/results"))
