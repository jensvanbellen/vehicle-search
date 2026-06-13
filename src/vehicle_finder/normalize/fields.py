"""Pure field-level normalizers: numbers, dates, fuel, transmission, colour.

Multilingual (NL/DE/EN) where the source language varies. These never touch the
network and are exhaustively unit-tested.
"""

from __future__ import annotations

import re
from datetime import date

from vehicle_finder.models.enums import FuelType, Transmission

_DIGITS = re.compile(r"[\d]+")


def parse_int(value: object) -> int | None:
    """Parse an int from a possibly-dirty string ('107.470 km', '48895', '', None)."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    s = str(value).strip()
    if not s:
        return None
    # Drop thousands separators and any unit suffix, keep leading digits run.
    cleaned = re.sub(r"[.,\s\u00a0]", "", s)
    m = _DIGITS.search(cleaned)
    return int(m.group()) if m else None


def parse_iso_date(value: object) -> date | None:
    """Parse 'YYYY-MM-DD' (BMW NL datePartOne) or 'YYYY-MM' / '' into a date."""
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    parts = s.split("-")
    try:
        if len(parts) >= 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        if len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1)
        if len(parts) == 1 and len(s) == 4:
            return date(int(s), 1, 1)
    except ValueError:
        return None
    return None


_FUEL_MAP: dict[str, FuelType] = {
    "benzine": FuelType.PETROL,
    "benzin": FuelType.PETROL,
    "petrol": FuelType.PETROL,
    "gasoline": FuelType.PETROL,
    "diesel": FuelType.DIESEL,
    "elektrisch": FuelType.ELECTRIC,
    "elektro": FuelType.ELECTRIC,
    "electric": FuelType.ELECTRIC,
    "plug-in hybride": FuelType.PLUGIN_HYBRID,
    "plug-in-hybrid": FuelType.PLUGIN_HYBRID,
    "plug-in": FuelType.PLUGIN_HYBRID,
    "plugin hybrid": FuelType.PLUGIN_HYBRID,
    "hybride": FuelType.HYBRID,
    "hybrid": FuelType.HYBRID,
    "waterstof": FuelType.HYDROGEN,
    "wasserstoff": FuelType.HYDROGEN,
    "hydrogen": FuelType.HYDROGEN,
}


def normalize_fuel(value: object) -> FuelType:
    if not value:
        return FuelType.UNKNOWN
    return _FUEL_MAP.get(str(value).strip().lower(), FuelType.OTHER)


_TRANSMISSION_MAP: dict[str, Transmission] = {
    "automaat": Transmission.AUTOMATIC,
    "automatic": Transmission.AUTOMATIC,
    "automatik": Transmission.AUTOMATIC,
    "automatisch": Transmission.AUTOMATIC,
    "handgeschakeld": Transmission.MANUAL,
    "handg_schakeld": Transmission.MANUAL,
    "manual": Transmission.MANUAL,
    "manueel": Transmission.MANUAL,
    "schaltgetriebe": Transmission.MANUAL,
    "manuell": Transmission.MANUAL,
}


def normalize_transmission(value: object) -> Transmission:
    if not value:
        return Transmission.UNKNOWN
    return _TRANSMISSION_MAP.get(str(value).strip().lower(), Transmission.UNKNOWN)


# Canonical English colour <- NL/DE/EN spellings. Raw colour is always preserved separately.
_COLOUR_MAP: dict[str, str] = {
    "zwart": "black",
    "schwarz": "black",
    "black": "black",
    "wit": "white",
    "weiss": "white",
    "weiß": "white",
    "white": "white",
    "grijs": "grey",
    "grau": "grey",
    "grey": "grey",
    "gray": "grey",
    "zilver": "silver",
    "silber": "silver",
    "silver": "silver",
    "blauw": "blue",
    "blau": "blue",
    "blue": "blue",
    "rood": "red",
    "rot": "red",
    "red": "red",
    "groen": "green",
    "grün": "green",
    "green": "green",
    "geel": "yellow",
    "gelb": "yellow",
    "yellow": "yellow",
    "oranje": "orange",
    "orange": "orange",
    "bruin": "brown",
    "braun": "brown",
    "brown": "brown",
    "beige": "beige",
    "goud": "gold",
    "gold": "gold",
    "paars": "purple",
    "lila": "purple",
    "purple": "purple",
}


def normalize_colour(value: object) -> str | None:
    """Map a raw colour word to a canonical English colour (first token wins)."""
    if not value:
        return None
    token = str(value).strip().lower().split()[0] if str(value).strip() else ""
    return _COLOUR_MAP.get(token)
