# CLAUDE.md — conventions for the vehicle-finder project

Pinned conventions for this repo. Keep yourself consistent with these across sessions.

## Language & tooling
- **Python 3.12**, managed with **uv** (`uv sync`, `uv run ...`). Never call `pip` directly.
- **Ruff** for lint + format (`uv run ruff check .` / `uv run ruff format .`). Config in `pyproject.toml`.
- **pyright in strict mode** (`uv run pyright`). New code must type-check clean.
- **pytest** (`uv run pytest`).

## Hard rules
- **The automated test suite NEVER hits live websites.** All parser/adapter tests use
  sanitized fixtures under `tests/fixtures/`. Live HTTP belongs only in real `fetch` runs.
- **No paid services** anywhere (no paid scrapers/proxies/geocoding). Free/local/self-hosted only.
- **No MCP in the fetch/data-collection path.** MCP is agent-facing only; the pipeline
  calls HTTP/parse code directly with no LLM in the loop.
- **Respect robots.txt, ToS, and rate limits.** Do not bypass CAPTCHAs/auth/anti-bot.
  If a source can't be collected cleanly, fall back to URL-import / manual entry and document it.
- **Never commit secrets, cookies, browser profiles, credentials, or the listings DB.**
- Distance is **offline** (postcode centroid + haversine), labelled **straight-line**.

## Code style
- Pydantic v2 for validation models; SQLModel for persistence.
- **structlog** for all logging — structured key/value events, no bare `print` in library code.
- Type everything; prefer explicit return types. Discriminate vehicle types with a
  `vehicle_type` field (`car` | `motorcycle`) on a single flat model with nullable extensions.
- Keep source adapters behind the common `SourceAdapter` protocol in `sources/base.py`.
- Config (model codes, synonyms, scoring weights, thresholds) lives in `config/*.yaml`,
  **never hard-coded** in logic. Postcode `2548 AE` is a default in config, not a constant.

## Git / commits
- **Conventional commits** (`feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`).
- **Commit at each milestone** (architecture doc, scaffold, vertical slice, each adapter,
  merge logic, UI, tests) so progress is reviewable and revertable — not just at start/end.

## Layout
See `docs/architecture.md` §3. Package is `vehicle_finder` under `src/`; CLI entry point
is `vehicle-search`.
