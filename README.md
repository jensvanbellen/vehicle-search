# Vehicle Finder

A local, free, self-hosted tool to find, track, compare and rank used **cars and
motorcycles** available in the Netherlands (German listings included, since importing
can be worthwhile). It collects listings from several marketplaces, normalizes them
into one data model, detects when the same physical vehicle is cross-posted on
multiple platforms and **merges duplicates into one consolidated vehicle**, and ranks
results with **explainable** scoring.

> Personal tool. No paid services. Respects robots.txt / ToS / rate limits.
> See [`docs/architecture.md`](docs/architecture.md) for design and per-source findings.

## Status

Under active construction — see the architecture doc for the build order. Setup and
full usage instructions land with the final milestone.

## Quick start (preview)

```bash
uv sync                      # create the environment
uv run vehicle-search --help
uv run vehicle-search init-db
uv run vehicle-search fetch --source bmw-nl
uv run vehicle-search serve  # local web UI at http://127.0.0.1:8000
```

## Development

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run pyright               # strict type-check
uv run pytest                # tests (never hit live sites — fixtures only)
```
