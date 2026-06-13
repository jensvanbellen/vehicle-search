# Vehicle Finder — Architecture & Implementation Plan

A local, free, self-hosted tool to find, track, compare and rank used **cars and
motorcycles** in NL/DE, with cross-platform duplicate merging and explainable scoring.

Status: **implemented.** This document records the investigation and plan; the build
followed it (see the README and git history for the delivered system).

---

## 1. Source investigation findings

I fetched each site's `robots.txt` and the example search URLs, decoded the BMW
base64 filter, downloaded and read the BMW NL JS bundle, and **made live test
requests** to characterise how listing data is actually exposed. Summary:

| Source | Vehicle | Mechanism found | Verdict | robots.txt |
|---|---|---|---|---|
| `occasions.bmw.nl` | cars | Internal JSON POST API (verified live) | **Clean automated** ✅ | allows search paths |
| `occasions.bmw-motorrad.nl` | bikes | Same platform/API, different `requestUri`/`serie` | **Clean automated** ✅ | allows search paths |
| `dasimport.nl` | cars | Server-rendered HTML cards | **Polite HTML** ✅ | allows `/aanbod` |
| `bmw.de` Gebrauchtwagen | cars | Modern SPA; robots-clean; WAF-blocks this env | **Fixtures + Playwright** 🧪 | only Sitemap, no Disallow |
| `marktplaats.nl` | both | Search API disallowed; **listing pages allowed** | **Single-URL import + manual** ✅ | `/lrp/api/search*` only |
| `mobile.de` | both | Listing pages disallowed by robots | **Manual entry only** 🚫fetch | disallows `fahrzeuge`, `/svc/`, `/consumer/api/` |

### 1.1 BMW NL / BMW Motorrad NL — the primary source (verified working)

`robots.txt` only disallows `/swf/`, `/js/`, `/css/`. The search result pages are
permitted. The page is a jQuery app: the HTML is a shell with a hidden
`.vehicle.dummy` template; listings are injected client-side from a JSON response.

Reading the minified bundle, the frontend (`Filters.requestUpdate`) issues a single
**POST** that returns both filter facets and the vehicle list:

- **Endpoint (cars):** `POST https://occasions.bmw.nl/bmw/zoeken`
- **Endpoint (bikes):** `POST https://occasions.bmw-motorrad.nl/motorrad/zoeken`
- **Content-Type:** `application/json`
- **Body:**
  ```json
  {
    "action": "getFiltersVehicles",
    "mode": "",
    "formData": [
      {"name": "serie", "value": "BMW X Serie"},
      {"name": "model[X5]", "value": "1"},
      {"name": "datePartOne[min]", "value": "2021"},
      {"name": "datePartOne[max]", "value": "2023"}
    ],
    "sort": "",
    "page": 1,
    "xssEnabler": "",
    "parentDomain": ""
  }
  ```
  **Key finding:** `formData` must be an **array of `{name, value}` pairs** (an
  object is silently ignored — a config-mapping gotcha). `xssEnabler` is empty on
  this platform (no CSRF token required). Verified live: filtering to
  `serie="BMW X Serie"` dropped the result set and returned only X-Serie cars.

- **Response (JSON):** `{ count, filters, map, vehicles: { vehicles: [...] }, hash }`
  - `count` = total site inventory (NOT the filtered count — ignore for paging).
  - 18 vehicles per page; paginate by incrementing `page` until empty.
  - Each vehicle object carries ~33 fields, e.g.: `vehicleId, name, serie, model,
    chassis, price, datePartOne` (first registration date), `builtDate, mileage,
    fuel, transmission, cylinderCount, cylinderVolume, powerHp, powerKw, engine,
    color, garantuee, dealerName, dealerId, images` (pipe-separated paths under
    `/Static/Media/carImages/...`), `monthlyPrice, condition, description,
    prepareCost, licensePlateScreen, discountPrice, stockDiscount, financialData,
    thumbnails`.
- **Detail page URL:** `<base>/<bmw|motorrad>/zoeken/resultaten/details/id/<vehicleId>`.
- **Filter field names** (extracted from the form): `serie` (string),
  `model[<Model>]=1`, `datePartOne[min|max]`, `price[min|max]`,
  `mileage[min|max]`, `fuel[Benzine|Diesel|Elektrisch|Plug-in Hybride]`,
  `chassis[...]`, `garantuee`.
- **Model/serie mapping gotcha:** BMW NL uses human strings — cars
  `serie="BMW X Serie"`, `model[X5]`; bikes `serie="BMW Sport"`,
  `model[S 1000 XR]`. These go in per-source config (§5). The base64 `filters`
  query param is only needed for the human-facing URL we store, not for the API call.

This is the cleanest source: structured JSON, no auth, no CAPTCHA, no anti-bot,
robots-permitted. **It is the first vertical slice and serves both cars and bikes.**

### 1.2 dasimport.nl — polite HTML

Single importer of German cars to NL. `robots.txt` disallows only `/iframe/` and a
few SEO bots. `/aanbod` is server-rendered HTML: cards expose title
(`BMW X5 xDrive45e`), price (`€ 40.935 incl. BPM, BTW en import` — already
NL-landed), build year (`08/2022`), mileage, fuel, and a detail URL
(`/auto-importeren/bmw/x5/<variant>-importeren-<id>`). Filters are query-string:
`brand=3500&model=49&year_s=2021&year_e=2023&km_s&km_e&price_s&price_e`. Numeric
brand/model IDs go in a config lookup table. Low volume. Parse with `selectolax`.

### 1.3 bmw.de — build now against fixtures, live transport via Playwright

Modern SPA; the filter is double-URL-encoded JSON with marketing-range codes
(`X5_G05`). `robots.txt` is **fully permissive** (declares only a Sitemap, no
`Disallow`) — confirmed by the user from an NL machine. The HTTP/transport failure
seen here (no response from direct HTTPS; the markdown fetcher timed out) is a
**WAF/TLS-fingerprint block of this build environment, not a permission issue**, and
the site is reachable from the user's own NL network.

Therefore bmw.de is **implemented now**, not deferred:
- **Adapter + parser are built and unit-tested against saved fixtures** so the
  interface and parsing logic are complete and correct regardless of this env.
- **Live transport = Playwright** (a real browser is genuinely required for this SPA),
  run **polite, non-headless, at a low request rate**, to be **verified from the
  user's NL network** rather than this environment.
- **Escalation guardrail:** if a polite browser still hits a bot challenge /
  interstitial, **stop** and treat bmw.de as **URL-import only** (robots-clean here).
  Do **not** escalate to proxy rotation or fingerprint spoofing.
- Diagnostics records its live status as **"unverified in build env"** until the
  user confirms a successful live fetch.

### 1.4 marktplaats.nl — single-URL import (+ manual)

`robots.txt` disallows the internal search API (`/lrp/api/search*`, `/search?q=*`)
and tracking-parameterised listing URLs (`?c=*`, `*correlationId=*`) — **but plain
individual listing pages (`/v/...`, `/a/...`) are allowed**. So we do **not** automate
search, but a **user-pasted single-listing URL is fetched politely** (tracking params
like `c=` / `correlationId=` stripped first) and parsed via JSON-LD / Open Graph /
visible fields. Manual entry is also available. ToS still restricts bulk automated
collection, which we do not do.

### 1.5 mobile.de — manual entry only (no auto-fetch)

`robots.txt` disallows the German listing pages themselves (`fahrzeuge`, `motorrad`,
…) plus `/consumer/api/` and `/svc/`; the official API is partner-gated. Because the
listing path itself is disallowed, we **do not auto-fetch any mobile.de URL**. The
fallback is **pure manual entry / paste-the-saved-page**: the user copies fields (or
pastes saved page text) into a form that maps onto the normalized model.

Together these keep cross-platform merging useful (the same dealer car often appears
on its own site + Marktplaats + mobile.de) **without violating any site's robots.**

---

## 2. Technology stack

Python 3.12, `uv`, Pydantic v2, SQLModel (SQLAlchemy + SQLite), `httpx`,
`selectolax`, FastAPI + Jinja2 + HTMX, `structlog`, `Pillow` + `imagehash`
(perceptual hashing), `rapidfuzz` (description similarity), Typer (CLI). Tests:
`pytest`; lint/format `ruff`; types `pyright --strict`. **Playwright only if a
source genuinely needs it and works without fighting anti-bot — not needed for the
confirmed sources** (BMW NL is a direct JSON call). No paid services anywhere.

---

## 3. Project layout

```
vehicle-search/
  pyproject.toml  CLAUDE.md  README.md  .gitignore  .env.example
  docs/architecture.md
  config/
    searches.yaml            # search targets (X5, S 1000 XR, R 1300 RS, R 12 nineT)
    sources.yaml             # per-source model-code maps & rate limits
    scoring/weights.yaml     # per-vehicle-type scoring weights
    scoring/features.yaml    # rare/desirable options + multilingual aliases
    equipment_synonyms.yaml  # canonical feature -> NL/DE/EN aliases
    import_costs.yaml        # German-import placeholders (clearly labelled)
  data/postcodes/            # offline NL+DE postcode->centroid (bundled, free)
  src/vehicle_finder/
    models/        # Pydantic + SQLModel: VehicleListing, VehicleGroup, PriceHistory, MergeDecision
    sources/       # base.py (adapter Protocol) + bmw_nl.py, dasimport.py, url_import.py, manual.py
    normalize/     # equipment normalization, make/model/colour canonicalisation
    dedup/         # blocking, fingerprint signals, clustering, manual-override store
    scoring/       # explainable scorer + rare-option boost + comparison metrics
    distance.py    # offline postcode centroid + haversine (labelled straight-line)
    persistence/   # repository, history diffing, grace-period inactivation
    pipeline.py    # fetch->parse->normalize->store->regroup->rescore->summary (idempotent)
    notify/        # notifier interface + console/markdown digest (no real sends by default)
    web/           # FastAPI app, routes, Jinja templates, HTMX partials
    cli.py         # vehicle-search fetch | serve | export | import-url | diagnostics
  tests/
    fixtures/      # sanitized JSON/HTML + precomputed image hashes (NEVER live)
    ...
```

---

## 4. Core data model

`VehicleListing` — single flat SQLModel with a `vehicle_type` discriminator
(`car|motorcycle`) and **nullable** type-specific fields (robust to missing data;
chosen over a strict discriminated union so partial scrapes never fail to persist).
Shared core: ids, source, source_listing_id, url, title, make, model, variant,
model_year, registration_date, mileage_km, price, currency, seller_type,
seller_name, location, country, distance_km, displacement_cc, power_kw, power_hp,
colour, owners, warranty, service_history, accident_info, vat_status, description,
raw_options_text, normalized_features (with provenance + confidence), image_urls,
first_seen, last_seen, status, vin, kenteken, raw_payload_ref, data_quality flags.
Car ext: body_style, doors, seats, transmission, drivetrain, fuel_type, EV fields,
co2. Motorcycle ext: bike-relevant extras.

`VehicleGroup` (consolidated vehicle) owns N listings: union of features (per-feature
provenance/confidence), best images, all source URLs with per-source price + status,
combined cross-source price-history timeline, physical location/country, and a
human-readable **merge explanation**. Canonical price configurable (default: lowest
active). `PriceHistory` rows per listing; `MergeDecision` stores sticky manual
overrides (confirm/split/not-duplicate). **Group IDs are stable and merges
deterministic given the same data; manual decisions are authoritative.**

---

## 5. Identity, dedup & cross-platform merging

- **Exact dedup:** unique `(source, source_listing_id)`.
- **Clustering:** (1) **blocking** by make+model+adjacent year; (2) **strong IDs**
  VIN/kenteken → decisive merge; (3) **fingerprint score** from weighted, configurable
  signals — mileage ±tol (strong), first-reg month/year (strong), same dealer
  (strong), perceptual-hash photo overlap ≥N (very strong), variant+power (medium),
  description similarity (medium), colour (weak), price proximity (weak); (4)
  thresholds: high→merge, mid→link & flag "possible duplicate", low→distinct;
  (5) **manual override** persists and wins. **Bias toward not merging when
  uncertain.** Scoring runs on the **group**, not duplicates.

---

## 6. Equipment normalization & scoring

Synonym map (config, multilingual NL/DE/EN) → canonical features, **preserving raw
text + a confidence per match**. Explainable scorer (all weights configurable,
per-vehicle-type): every score returns line-item breakdown. Rare-option boost from
`scoring/features.yaml` with `rarity: auto` (boost derived from frequency in the
current result set, shown transparently e.g. `+12 four-wheel steering (on 4% of
matches)`). **Confidence-gated:** only high-confidence features score; low-confidence
shown as "possibly equipped". Comparison metrics: price/year, price & mileage vs
similar, percentile, estimated acquisition cost. **German import-cost module** is a
separate, clearly-labelled estimate from `import_costs.yaml` placeholders — never
presented as an authoritative BPM calculation; keyed off physical country.

Distance: bundled **offline** NL+DE postcode→centroid table + haversine, labelled
**straight-line** (postcode `2548 AE`, configurable, never hard-coded).

---

## 7. Pipeline, UI, CLI

**Pipeline (idempotent):** fetch configured searches → parse → normalize → upsert
(new/changed/price-change) → recompute groups (manual decisions sticky) → rescore →
mark inactive after a **grace period** → run summary; per-source failures recorded
without corrupting existing data. Conservative rates, retries w/ exponential backoff,
timeouts, structured logs. No external scheduler in v1 (structured so cron/Actions
could call `fetch`). **No MCP in the fetch path** — pure HTTP/parse.

**UI (FastAPI + Jinja + HTMX):** dashboard (active/new/price-drops/removed/best new +
per-source health); listing table **one row per consolidated vehicle** with
per-source badges, representative price + spread, sorting/filter/search; detail page
(images, per-source links, normalized specs, score breakdown, per-source price +
combined history, merge explanation, data-quality warnings, notes, shortlist/reject);
comparison view; read-only search/scoring management (config stays source of truth).

**CLI:** `vehicle-search fetch [--source S] [--search ID] | serve | export | import-url URL | diagnostics`.

**Notifications:** notifier interface + console/markdown digest; **no real sends
without explicit config.**

---

## 8. Testing (always fixtures, never live)

Unit: parsers (incl. missing/malformed fields), equipment normalization, scoring,
price-history, dedup/merge. Merge cases required: true cross-post merges; distinct
same-spec vehicles do **not** merge; mid-confidence stays "possible duplicate";
manual merge/split persists across refresh; perceptual hashing uses fixture
images/precomputed hashes (offline). One FastAPI smoke test. Sanitized fixtures only.

---

## 9. Build order

1. Scaffold + `CLAUDE.md` + tooling, commit.
2. **Vertical slice:** BMW NL adapter (cars) → persistence → normalization → scoring
   → `fetch` CLI → basic listing UI, with fixtures; verify; commit.
3. BMW Motorrad NL (same adapter, bike config) + dasimport HTML adapter; commit each.
4. bmw.de adapter + parser against **saved fixtures**, Playwright wired as live
   transport (verify on user's NL network); commit.
5. Marktplaats single-URL import + mobile.de manual entry + generic manual entry; commit.
6. Cross-platform merging + manual overrides; commit.
7. Comparison, history views, shortlist, export, diagnostics, notifications; commit.
8. README + full lint/type/test pass; commit.

---

## 10. Key assumptions & limitations

- BMW model strings/codes (`R 1300 RS`, `S 1000 XR`, `BMW Sport`) and the desirable-
  option lists are **assumptions to verify** against the live lineup; all in config.
- BMW NL `count` is total inventory, not filtered — page until empty.
- **bmw.de**: robots-clean (per user, NL); built against fixtures with Playwright live
  transport, verified on the user's network. Live status starts "unverified in build
  env"; falls back to URL-import only if a polite browser is still challenged.
- **Marktplaats**: search API is robots-disallowed (not automated); single **listing
  URLs are allowed** and supported via URL-import (tracking params stripped).
- **mobile.de**: listing pages are robots-disallowed → **manual entry only, no
  auto-fetch.**
- dasimport prices are already NL-landed (incl. BPM/import); flagged so import-cost
  scoring isn't double-counted.
- Merge thresholds start **conservative**; tunable in config.
