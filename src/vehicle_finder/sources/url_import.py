"""Single-URL listing import (e.g. a pasted Marktplaats listing page).

PLACEHOLDER — implemented in milestone 5. Will fetch one *allowed* listing page,
strip tracking params, and parse JSON-LD / Open Graph / visible fields into the
normalized model. Never used for robots-disallowed paths (mobile.de => manual entry).
"""

from __future__ import annotations

from typing import NoReturn


def import_single_url(url: str) -> NoReturn:
    """Import one listing from a URL. PLACEHOLDER — implemented in milestone 5."""
    raise NotImplementedError("import_single_url is implemented in milestone 5.")
