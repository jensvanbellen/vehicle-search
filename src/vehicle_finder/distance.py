"""Offline straight-line distance from home, via postcode/city centroids + haversine.

NO network/geocoding. Reads ``data/geo/places.csv`` (NL PC4 + NL/DE city + DE PLZ-prefix
centroids — a starter set; extend the CSV freely). Distances are **straight-line**, not
road distance, and labelled as such everywhere they surface.
"""

from __future__ import annotations

import csv
import functools
import math
import re

from vehicle_finder.config import REPO_ROOT, get_settings

_PLACES_FILE = REPO_ROOT / "data" / "geo" / "places.csv"
Coord = tuple[float, float]


@functools.lru_cache(maxsize=1)
def _places() -> dict[str, dict[str, Coord]]:
    """Return {'pc4': {...}, 'plz': {...}, 'city': {name: coord}}."""
    out: dict[str, dict[str, Coord]] = {"pc4": {}, "plz": {}, "city": {}}
    if not _PLACES_FILE.exists():
        return out
    with _PLACES_FILE.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            kind = (row.get("kind") or "").strip()
            key = (row.get("key") or "").strip().lower()
            try:
                coord = (float(row["lat"]), float(row["lon"]))
            except (KeyError, ValueError):
                continue
            if kind in out and key:
                out[kind][key] = coord
    return out


def haversine_km(a: Coord, b: Coord) -> float:
    """Great-circle distance between two (lat, lon) points, in km."""
    r = 6371.0088
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def coords_for_postcode(postcode: str, country: str | None = None) -> Coord | None:
    """NL: first 4 digits -> PC4 centroid. DE: first 2 digits -> PLZ-area centroid."""
    digits = re.sub(r"\D", "", postcode or "")
    places = _places()
    if (country or "").upper() == "DE" or (not country and len(digits) == 5):
        return places["plz"].get(digits[:2]) if len(digits) >= 2 else None
    if len(digits) >= 4:
        return places["pc4"].get(digits[:4])
    return None


def coords_for_city(text: str) -> Coord | None:
    """Find a known city name as a whole word in free text (longest match wins)."""
    if not text:
        return None
    low = text.lower()
    cities = _places()["city"]
    best: tuple[int, Coord] | None = None
    for name, coord in cities.items():
        if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", low) and (
            best is None or len(name) > best[0]
        ):
            best = (len(name), coord)
    return best[1] if best else None


def home_coords(home_postcode: str | None = None) -> Coord | None:
    pc = home_postcode or get_settings().home_postcode
    return coords_for_postcode(pc, country="NL")


def distance_from_home_km(
    *,
    postcode: str | None = None,
    location: str | None = None,
    seller_name: str | None = None,
    country: str | None = None,
    home_postcode: str | None = None,
) -> float | None:
    """Best-effort straight-line km from home. None if no location signal resolves.

    Tries, in order: explicit postcode, then a city name found in ``location`` or
    ``seller_name`` (e.g. dealer "Ekris Maastricht" -> Maastricht).
    """
    home = home_coords(home_postcode)
    if home is None:
        return None
    target: Coord | None = None
    if postcode:
        target = coords_for_postcode(postcode, country)
    if target is None:
        for text in (location, seller_name):
            target = coords_for_city(text or "")
            if target is not None:
                break
    if target is None:
        return None
    return round(haversine_km(home, target), 1)
