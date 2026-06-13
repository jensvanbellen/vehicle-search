"""BMW Premium Selection adapter — serves BOTH occasions.bmw.nl (cars) and
occasions.bmw-motorrad.nl (motorcycles), which share one platform.

Mechanism (reverse-engineered + verified live): the site POSTs JSON to
``<base_url><request_uri>`` and receives ``{vehicles: {vehicles: [...]}}``.

    body = {
      "action": "getFiltersVehicles", "mode": "", "sort": "", "page": N,
      "xssEnabler": "", "parentDomain": "",
      "formData": [{"name": "serie", "value": "BMW X Serie"},
                   {"name": "model", "value": "X5"},                  # names joined by '|'
                   {"name": "datePartOne", "value": "min:2021|max:2023"}],
    }

CRITICAL gotcha: ``formData`` is an **array of {name, value}**; range fields use the
``"min:..|max:.."`` string form and multi-select fields join values with ``'|'``. An
object or bracketed keys are silently ignored (return unfiltered results).
"""

from __future__ import annotations

from typing import Any, cast

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

log = get_logger("bmw_nl")

MAX_PAGES = 60  # safety cap; real searches terminate far sooner
_BIKE_DISPLACEMENT_X100_THRESHOLD = 10000  # bikes report cc x100 (e.g. 99900 -> 999)


def _images_from(v: dict[str, Any], base_url: str) -> list[str]:
    thumbs = v.get("thumbnails")
    if isinstance(thumbs, list) and thumbs:
        return [str(u) for u in cast("list[Any]", thumbs)]
    raw = str(v.get("images") or "")
    out: list[str] = []
    for part in raw.split("|"):
        p = part.strip()
        if not p:
            continue
        out.append(f"{base_url}{p}" if p.startswith("/") else p)
    return out


def parse_vehicle(
    v: dict[str, Any],
    *,
    source_id: str,
    vehicle_type: VehicleType,
    base_url: str,
    details_uri: str,
    search_id: str | None = None,
    normalizer: EquipmentNormalizer | None = None,
) -> VehicleListing | None:
    """Parse one raw vehicle dict into a normalized listing. Pure; fixture-tested."""
    vid = str(v.get("vehicleId") or "").strip()
    if not vid:
        return None

    dq = DataQuality()
    reg_date = parse_iso_date(v.get("datePartOne"))
    built = parse_iso_date(v.get("builtDate"))
    year = reg_date.year if reg_date else (built.year if built else None)

    displacement = parse_int(v.get("cylinderVolume"))
    if (
        vehicle_type is VehicleType.MOTORCYCLE
        and displacement
        and displacement >= _BIKE_DISPLACEMENT_X100_THRESHOLD
    ):
        displacement = round(displacement / 100)
        dq.warnings.append("displacement normalized from x100 source encoding")

    price = parse_int(v.get("price"))
    mileage = parse_int(v.get("mileage"))
    if price is None:
        dq.warnings.append("price missing")
    if mileage is None:
        dq.warnings.append("mileage missing")
    if year is None:
        dq.warnings.append("registration/build year missing")

    plate = (str(v.get("licensePlateScreen") or "")).strip() or None
    desc = (str(v.get("description") or "")).strip() or None
    raw_colour = (str(v.get("color") or "")).strip() or None

    listing = VehicleListing(
        vehicle_type=vehicle_type,
        source=source_id,
        source_listing_id=vid,
        url=f"{base_url}{details_uri}/id/{vid}",
        title=(str(v.get("name") or "")).strip() or f"BMW {v.get('model') or ''}".strip(),
        make="BMW",
        model=(str(v.get("model")).strip() or None) if v.get("model") else None,
        variant=(str(v.get("engine")).strip() or None) if v.get("engine") else None,
        model_year=year,
        registration_date=reg_date,
        mileage_km=mileage,
        price=price,
        currency="EUR",
        seller_type=SellerType.DEALER,
        seller_name=(str(v.get("dealerName")).strip() or None) if v.get("dealerName") else None,
        country="NL",
        displacement_cc=displacement,
        power_hp=parse_int(v.get("powerHp")),
        power_kw=parse_int(v.get("powerKw")),
        colour=normalize_colour(raw_colour) or raw_colour,
        warranty=(str(v.get("garantuee")).strip() or None) if v.get("garantuee") else None,
        kenteken=plate,
        description=desc,
        raw_options_text=desc,
        fuel_type=normalize_fuel(v.get("fuel")),
        transmission=normalize_transmission(v.get("transmission")),
        image_urls=_images_from(v, base_url),
        raw_payload=v,
        search_id=search_id,
    )

    if vehicle_type is VehicleType.CAR:
        listing.body_style = (str(v.get("chassis")).strip() or None) if v.get("chassis") else None
    else:
        listing.bike_category = (str(v.get("serie")).strip() or None) if v.get("serie") else None

    norm = normalizer or EquipmentNormalizer()
    text = " ".join(p for p in (desc, str(v.get("name") or ""), str(v.get("engine") or "")) if p)
    listing.set_features(norm.normalize_text(text, source=source_id))
    listing.set_data_quality(dq)
    return listing


def parse_response(
    data: dict[str, Any],
    *,
    source_id: str,
    vehicle_type: VehicleType,
    base_url: str,
    details_uri: str,
    search_id: str | None = None,
) -> tuple[list[VehicleListing], int, int, list[str], bool]:
    """Parse a full page response. Returns (listings, found, failures, warnings, layout_changed)."""
    container = data.get("vehicles")
    if not isinstance(container, dict):
        return [], 0, 0, ["response missing 'vehicles' object"], True
    raw_list = cast("dict[str, Any]", container).get("vehicles")
    if not isinstance(raw_list, list):
        return [], 0, 0, ["response missing vehicles[].vehicles list"], True
    vehicles = cast("list[Any]", raw_list)

    listings: list[VehicleListing] = []
    failures = 0
    warnings: list[str] = []
    normalizer = EquipmentNormalizer()
    for raw in vehicles:
        if not isinstance(raw, dict):
            failures += 1
            continue
        try:
            parsed = parse_vehicle(
                cast("dict[str, Any]", raw),
                source_id=source_id,
                vehicle_type=vehicle_type,
                base_url=base_url,
                details_uri=details_uri,
                search_id=search_id,
                normalizer=normalizer,
            )
        except Exception as exc:
            failures += 1
            warnings.append(f"parse error: {exc}")
            continue
        if parsed is None:
            failures += 1
        else:
            listings.append(parsed)
    return listings, len(vehicles), failures, warnings, False


class BmwPremiumSelectionAdapter:
    """One instance per BMW PS site (cars or motorcycles)."""

    def __init__(self, source_id: str, vehicle_type: VehicleType, base_url: str, request_uri: str):
        self.id = source_id
        self.vehicle_type = vehicle_type
        self.base_url = base_url.rstrip("/")
        self.request_uri = request_uri
        self.endpoint = f"{self.base_url}{request_uri}"
        self.details_uri = f"{request_uri}/resultaten/details"

    def supports(self, target: SearchTarget) -> bool:
        return target.vehicle_type is self.vehicle_type and bool(target.codes_for(self.id))

    def _build_formdata(self, target: SearchTarget, codes: dict[str, Any]) -> list[dict[str, str]]:
        fd: list[dict[str, str]] = [{"name": "serie", "value": str(codes["serie"])}]
        model = codes.get("model")
        if model:
            value = model if isinstance(model, str) else "|".join(str(m) for m in model)
            fd.append({"name": "model", "value": value})
        if target.min_year or target.max_year:
            fd.append(
                {
                    "name": "datePartOne",
                    "value": f"min:{target.min_year or ''}|max:{target.max_year or ''}",
                }
            )
        if target.min_price or target.max_price:
            fd.append(
                {
                    "name": "price",
                    "value": f"min:{target.min_price or ''}|max:{target.max_price or ''}",
                }
            )
        if target.max_mileage:
            fd.append({"name": "mileage", "value": f"min:|max:{target.max_mileage}"})
        return fd

    def _passes(self, target: SearchTarget, listing: VehicleListing) -> bool:
        """Client-side safety net — guarantees correctness if a server filter is ignored."""
        if not target.variant_allowed(f"{listing.variant or ''} {listing.title or ''}"):
            return False
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
        hay = f"{listing.title} {listing.description or ''}".lower()
        if any(term.lower() in hay for term in target.excluded_terms):
            return False
        excluded_colours = {c.lower() for c in target.excluded_colours}
        return not (listing.colour and listing.colour.lower() in excluded_colours)

    def fetch(self, target: SearchTarget, client: PoliteClient) -> FetchResult:
        codes = target.codes_for(self.id)
        result = FetchResult()
        if not codes.get("serie"):
            result.warnings.append(f"{self.id}: no source_codes.serie for search '{target.id}'")
            return result

        seen: set[str] = set()
        target_model = str(codes.get("model") or "").lower()
        model_mismatches = 0
        for page in range(1, MAX_PAGES + 1):
            body = {
                "action": "getFiltersVehicles",
                "mode": "",
                "formData": self._build_formdata(target, codes),
                "sort": "",
                "page": page,
                "xssEnabler": "",
                "parentDomain": "",
            }
            resp = client.request(
                "POST",
                self.endpoint,
                headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
                json_body=body,
            )
            try:
                data: dict[str, Any] = resp.json()
            except ValueError:
                result.warnings.append(f"page {page}: non-JSON response")
                result.layout_changed = True
                break

            listings, found, failures, warnings, layout = parse_response(
                data,
                source_id=self.id,
                vehicle_type=self.vehicle_type,
                base_url=self.base_url,
                details_uri=self.details_uri,
                search_id=target.id,
            )
            result.warnings.extend(f"p{page}: {w}" for w in warnings)
            result.layout_changed = result.layout_changed or layout
            if not listings:
                break
            fresh = [x for x in listings if x.source_listing_id not in seen]
            if not fresh:  # only repeats — pagination exhausted
                break
            for x in fresh:
                seen.add(x.source_listing_id)
                if target_model and x.model and target_model.split("|")[0] not in x.model.lower():
                    model_mismatches += 1
                if self._passes(target, x):
                    result.listings.append(x)
            result.found += found
            result.parse_failures += failures

        if model_mismatches and model_mismatches > len(seen) / 2:
            result.warnings.append(
                f"{model_mismatches}/{len(seen)} results did not match model '{target_model}' "
                "— check source_codes (silent filter mismatch?)"
            )
        log.info(
            "bmw_ps_fetch_done",
            source=self.id,
            search=target.id,
            kept=len(result.listings),
            seen=len(seen),
            failures=result.parse_failures,
        )
        return result


def register_adapters() -> None:
    """Register a BMW PS adapter for every config source with adapter == 'bmw_ps'."""
    for source_id, cfg in load_sources().items():
        if cfg.adapter != "bmw_ps" or not cfg.enabled:
            continue
        vtype = cfg.vehicle_types[0] if cfg.vehicle_types else VehicleType.CAR
        register(BmwPremiumSelectionAdapter(source_id, vtype, cfg.base_url, cfg.request_uri))
