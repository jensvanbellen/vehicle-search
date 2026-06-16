# Vehicle Finder

A local, free, self-hosted tool to find, track, compare and rank used **cars and
motorcycles** available in the Netherlands (German listings included, since importing
can be worthwhile). It collects listings from several marketplaces, normalizes them into
one data model, detects when the same physical vehicle is cross-posted on multiple
platforms and **merges duplicates into one consolidated vehicle**, and ranks results with
**explainable** scoring that rewards rare/desirable options.

> Personal tool. **No paid services.** Respects `robots.txt`, ToS, and rate limits.
> See [`docs/architecture.md`](docs/architecture.md) for design and per-source findings.

## What works

| Source | Vehicles | Mechanism | Status |
|---|---|---|---|
| `occasions.bmw.nl` | cars | Internal JSON API | ✅ **automated** (verified live) |
| `occasions.bmw-motorrad.nl` | motorcycles | Same platform | ✅ **automated** (verified live) |
| `dasimport.nl` | cars (DE imports) | Server-rendered HTML | ✅ **automated** (verified live) |
| `bmw.de` Gebrauchtwagen | cars | SPA via Playwright (STOLO API) | 🧪 **enabled**; page loads, results endpoint to validate on an NL network |
| `marktplaats.nl` | both | Single-listing URL import | ✅ listing pages allowed; **no automated search** |
| `mobile.de` | both | Manual entry | 🚫 listing pages robots-disallowed → **manual only** |

## Requirements

- [uv](https://docs.astral.sh/uv/) (manages Python 3.12 and dependencies)

## Setup

```bash
uv sync                       # create the venv + install deps (Python 3.12 auto-provisioned)
cp .env.example .env          # optional: tweak postcode, rates, flags
uv run vehicle-search init-db # create the SQLite schema (data/vehicles.db)

# Only if you want the bmw.de source (Playwright browser, ~1x one-time download):
uv run playwright install chromium
```

### bmw.de note

bmw.de is **enabled** but **off at runtime unless `VF_BMWDE_ENABLED=true`** (it drives a
real browser). Its results come from BMW's STOLO API (`stolo-data-service…/vehiclesearch/`)
behind a cookie-consent overlay; the adapter accepts consent, scrolls to lazy-load, and
**dumps raw captures to `data/raw/bmwde_last_capture.json`** so you can validate the exact
offer field names on your first successful run. Run it on an NL network:

```bash
VF_BMWDE_ENABLED=true uv run vehicle-search fetch --source bmw-de --search x5-g05
```

## Usage

```bash
# Refresh listings from all enabled, supported sources for all searches
uv run vehicle-search fetch

# Scope a refresh
uv run vehicle-search fetch --source bmw-nl
uv run vehicle-search fetch --search x5-g05
uv run vehicle-search fetch --dry-run          # fetch+parse+score, no DB writes

# Local web UI  ->  http://127.0.0.1:8000
uv run vehicle-search serve

# Import one pasted Marktplaats listing URL (robots-checked; tracking params stripped)
uv run vehicle-search import-url "https://www.marktplaats.nl/v/auto-s/bmw/m2100000000-bmw-x5"

# Manual entry (mobile.de fallback) from a JSON file
uv run vehicle-search add-manual --file config/examples/manual_listing.example.json

# Export, diagnostics, notification digest
uv run vehicle-search export --format json --out data/exports/listings
uv run vehicle-search diagnostics
uv run vehicle-search notify
```

The web UI has a **dashboard** (counts, best matches, source health), a **listing table**
with one row per consolidated vehicle (per-source badges, price spread, filters/sort),
a **detail page** (per-source prices + links, combined price history, merge explanation,
explainable score breakdown, equipment with provenance/confidence, shortlist/reject/notes),
a **comparison view** (`/compare?ids=grp-a,grp-b`), and a **diagnostics** page.

## How a refresh works (idempotent)

`fetch` → parse & normalize → compute offline distance → score → upsert (recording new /
price-change / removed) → **recompute cross-platform groups** (manual merge decisions are
sticky) → score the consolidated vehicles → mark unseen listings inactive after a grace
period → print a run summary. Re-running with identical data is a no-op. Conservative
request rates, retries with backoff, and timeouts apply to every live fetch. **No external
scheduler in v1**, but `fetch` is structured so a cron job / GitHub Action could call it.

## Configuration

All tunables live in human-editable YAML under `config/` — nothing business-specific is
hard-coded:

- `config/searches.yaml` — search targets (X5 G05, S 1000 XR, R 1300 RS, R 12 nineT) with
  per-source model codes, year/price/mileage filters, preferred equipment, countries.
- `config/sources.yaml` — per-source adapter, base URL, enable flag, polite rate limit.
- `config/scoring/weights.yaml` — explainable scoring weights, **per vehicle type**.
- `config/scoring/features.yaml` — rare/desirable options: multilingual aliases, points,
  `rarity: auto`.
- `config/equipment_synonyms.yaml` — general feature normalization (NL/DE/EN).
- `config/dedup.yaml` — merge signals, weights, and thresholds.
- `config/import_costs.yaml` — German-import cost **placeholders** (clearly labelled).

Your home postcode is a default in `searches.yaml` / `.env` (set `home_postcode:` or `VF_HOME_POSTCODE`), never hard-coded.

### Add a vehicle model

Add an entry to `config/searches.yaml`. The only subtle part is the **per-source codes**
(these fail silently — a wrong code returns zero results, not an error):

```yaml
- id: m340i
  vehicle_type: car
  make: BMW
  model: M340i
  min_year: 2021
  preferred_equipment: [head_up_display, harman_kardon]
  source_codes:
    bmw-nl:        { serie: "BMW 3 Serie", model: "M340i" }   # human strings
    bmw-de:        { marketing_model_range: "M340I_G20" }      # internal range code
    dasimport:     { brand: 3500, model: 12 }                  # numeric IDs
```

To find codes: for **BMW NL/Motorrad**, POST an empty `formData` to the search endpoint and
read the `serie` facet, then select a serie to see its `model` values (the model facet only
populates after a serie is chosen). For **bmw.de**, the marketing range code appears in the
results-page URL filter. For **dasimport**, the numeric `brand`/`model` IDs are in its
`/aanbod` query string. Verify against the live lineup — strings change.

### Add a listing source

1. Implement an adapter in `src/vehicle_finder/sources/<name>.py` exposing `id`,
   `supports(target)`, and `fetch(target, client) -> FetchResult`. Keep a **pure parser**
   (`parse_*`) separate from transport so it can be fixture-tested.
2. Add a `register_adapters()` that reads `config/sources.yaml` and `register(...)`s your
   adapter; call it from `sources/base.py::_ensure_loaded`.
3. Add the source to `config/sources.yaml` (and per-source codes to `searches.yaml`).
4. Add a sanitized fixture under `tests/fixtures/<name>/` and a parser test. **The test
   suite must never hit the live site.**

## Development

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run pyright               # strict type-check
uv run pytest                # tests (fixtures only — never live)
```

Conventions are pinned in [`CLAUDE.md`](CLAUDE.md).

> **Schema changes during development:** there is no migration tool in v1. `init-db`
> (`SQLModel.metadata.create_all`) adds *new tables* but **cannot add columns to existing
> tables**. If you add a field to a model, delete `data/vehicles.db` and re-fetch (the DB is
> disposable, derived data). A real migration tool (Alembic) is a future extension.

## Privacy & safety

`.gitignore` excludes the listings DB, `.env`, exports, cookies, browser profiles, and the
Playwright profile. Notifications send **nothing** unless explicitly enabled. The German
import-cost figures are **labelled placeholders**, not an authoritative BPM calculation.
