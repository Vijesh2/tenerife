# Tenerife Cycling Routes

A lightweight Python-first web app for browsing preprocessed Tenerife cycling routes on a Leaflet map.

The project has two parts:

- a **FastHTML + Leaflet route browser** in `app.py`, `ui.py`, and `static/`
- a **GPX preprocessing pipeline** in `scripts/preprocess_gpx.py`

The current app uses the already generated data in `data/processed/routes.geojson` and displays it as selectable, toggleable routes on a map.

---

## Web App

The v0.1 web app is a single-page route browser for Tenerife cycling routes.

It supports:

- Leaflet map centred on Tenerife
- route polylines loaded from `data/processed/routes.geojson`
- one colour per route
- route selection by clicking the map or route list
- highlighted selected route
- map zoom-to-route on selection
- per-route checkboxes for showing or hiding routes
- select all / deselect all route control
- draggable divider between the map and route list
- compact selected-route summary with distance and elevation gain
- map key listing visible route IDs, colours, distance, and elevation gain

Run the app:

```bash
uv run python app.py
```

Then open:

```text
http://localhost:5001
```

The app serves:

- `/static/app.css`
- `/static/app.js`
- `/data/processed/routes.geojson`

Leaflet itself is loaded from the public unpkg CDN.

---

## Project Structure

```text
project/
  app.py                 # FastHTML app entrypoint
  ui.py                  # server-rendered page structure and shared styles
  static/
    app.css              # app and Leaflet fallback styles
    app.js               # map, route selection, toggles, resizing
  data/
    raw_gpx/             # input GPX files
    processed/           # generated app-ready outputs
      routes.geojson
      routes_index.json
      routes/
        <route_id>.geojson
      routes_preview/
      routes_detail/
      profiles/
      segments/
      climbs/
      frontend/
  scripts/
    preprocess_gpx.py    # GPX preprocessing pipeline
  tests/
```

---

## Installation

This project uses `uv`.

Install dependencies and create the environment:

```bash
uv sync
```

If you are not using `uv`, install the core dependencies manually:

```bash
pip install gpxpy python-fasthtml pytest
```

---

## Development

Run the web app:

```bash
uv run python app.py
```

Run tests:

```bash
uv run pytest -s
```

Run a quick syntax check for the app modules:

```bash
uv run python -m py_compile app.py ui.py tests/test_app.py
node --check static/app.js
```

Developer shortcuts:

```bash
make build
make rebuild
make test
make validate
```

---

## Data Flow

The browser currently loads the combined GeoJSON file directly:

```text
data/processed/routes.geojson
```

Each GeoJSON feature is expected to include route properties such as:

- `route_id`
- `name`
- `distance_km`
- `elevation_gain_m`
- `elevation_loss_m`
- `difficulty`
- `terrain_type`
- `bbox`
- `centroid_lat`
- `centroid_lon`

The frontend handles missing optional properties defensively.

---

## Preprocessing Pipeline

The preprocessing pipeline converts cycling GPX files into GeoJSON and route metadata for the app.

It produces:

- a single combined GeoJSON file for map rendering
- a route index JSON for metadata
- one GeoJSON file per route for future lazy loading
- optional elevation profile JSON
- route segment and climb JSON
- preview/detail geometry exports
- frontend-ready lookup artefacts
- JSON and Markdown build reports
- a build manifest for incremental rebuilds

Run the pipeline:

```bash
uv run python scripts/preprocess_gpx.py
```

Useful options:

```bash
uv run python scripts/preprocess_gpx.py --full-rebuild
uv run python scripts/preprocess_gpx.py --only trf_1_adeje_west_coast_and_masca_valley
uv run python scripts/preprocess_gpx.py --skip-profiles
uv run python scripts/preprocess_gpx.py --validate-only
uv run python scripts/preprocess_gpx.py --geometry-mode preview
uv run python scripts/preprocess_gpx.py --no-build-report
```

Repeat runs use `data/processed/build_manifest.json` to skip unchanged GPX files while still refreshing combined outputs.

---

## Generated Outputs

After preprocessing, the app expects these files to exist:

```text
data/processed/routes.geojson
data/processed/routes_index.json
data/processed/routes/<route_id>.geojson
```

The pipeline may also generate:

```text
data/processed/build_manifest.json
data/processed/build_report.json
data/processed/build_report.md
data/processed/profiles/<route_id>.json
data/processed/segments/<route_id>.json
data/processed/climbs/<route_id>.json
data/processed/routes_preview/<route_id>.geojson
data/processed/routes_detail/<route_id>.geojson
data/processed/frontend/routes_list.json
data/processed/frontend/routes_map_index.json
data/processed/frontend/route_lookup.json
```

---

## Preprocessing Features

- Parses GPX tracks and routes
- Flattens multi-segment tracks into a single route
- Prefers GPX track/route names when available
- Smooths elevation before ascent/descent calculations
- Simplifies display geometry while preserving full-resolution metrics
- Computes distance, elevation gain/loss, min/max elevation, bounds, and centroid
- Adds difficulty, terrain type, loop/direction metadata, and search text
- Flags route quality issues
- Extracts coarse route segments and notable climbs
- Groups likely duplicate or variant routes without changing stable route IDs
- Emits Leaflet-ready GeoJSON

---

## Testing

The test suite covers:

- GPX parsing and route metric helpers
- route validation and simplification behavior
- frontend artefact shape
- full preprocessing output generation
- FastHTML home page smoke rendering

Run:

```bash
uv run pytest -s
```

---

## Roadmap

Possible next steps:

- lazy-load per-route geometry from `data/processed/routes/<route_id>.geojson`
- add elevation profile charts
- add climb visualisation
- add route filtering and search
- improve mobile layout
- add deployment configuration

---

## Summary

This repository provides a small end-to-end foundation for a Tenerife cycling route browser:

```text
raw GPX files -> processed GeoJSON and metrics -> FastHTML + Leaflet web app
```
