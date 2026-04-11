.PHONY: build rebuild test validate

build:
	uv run python scripts/preprocess_gpx.py

rebuild:
	uv run python scripts/preprocess_gpx.py --full-rebuild

test:
	uv run pytest -s

validate:
	uv run python scripts/preprocess_gpx.py --validate-only
