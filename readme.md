# GPX → GeoJSON Preprocessing Pipeline

A lightweight Python tool to convert cycling routes stored as GPX files into **GeoJSON + route metrics**, ready for use in web mapping applications (e.g. Leaflet).

Designed for simplicity, transparency, and easy iteration.

---

## Overview

This tool takes a folder of `.gpx` files and produces:

- a single **GeoJSON file** for map rendering
- a **route index JSON** for fast UI loading (lists, filters, metadata)
- one **GeoJSON file per route** for lazy-loading detailed map geometry
- optional per-route **elevation profile JSON** for charting
- per-route **segment and climb JSON** for route detail pages
- **preview/detail geometry** exports for different frontend views
- frontend-ready list, map, and lookup JSON artefacts
- JSON and Markdown build reports for quick data QA
- a lightweight **build manifest** for incremental rebuilds

It is particularly suited to applications such as:

- cycling route maps (e.g. Tenerife routes)
- route visualisation dashboards
- lightweight GIS workflows without heavy dependencies

---

## Features

- Parses GPX tracks and routes
- Flattens multi-segment tracks into a single route
- Prefers GPX track/route names when available
- Smooths elevation before ascent/descent calculations
- Simplifies display geometry while preserving full-resolution metrics
- Computes key cycling metrics:
  - distance (km)
  - elevation gain/loss (m)
  - min/max elevation (m)
- Adds cycling-friendly route card metadata:
  - difficulty (`easy`, `moderate`, `hard`, `extreme`)
  - terrain type (`flat`, `rolling`, `hilly`, `mountainous`)
  - loop/direction detection
  - normalized search text
- Flags route quality issues such as invalid coordinates, missing elevation, very short routes, and duplicate-heavy data
- Adds route bounds and centroid metadata
- Adds frontend-friendly spatial metadata such as start/end/mid/high/low points, loop closure, spatial extent, and bearing
- Extracts coarse route segments and notable climbs with transparent heuristics
- Groups likely duplicate or variant routes without changing stable route IDs
- Emits multi-resolution geometry and frontend lookup artefacts
- Writes build reports in JSON and Markdown
- Supports cached incremental rebuilds with `data/processed/build_manifest.json`
- Can write downsampled elevation profiles to `data/processed/profiles/`
- Outputs clean, Leaflet-ready GeoJSON
- Writes one GeoJSON file per route for lazy loading
- Handles malformed GPX files gracefully
- Minimal dependencies (no heavy GIS stack)

---

## Example Output

### GeoJSON (for maps)

Each GPX file becomes a GeoJSON `Feature`:

```json
{
  "type": "Feature",
  "properties": {
    "route_id": "masca_loop",
    "name": "Masca Loop",
    "distance_km": 82.4,
    "elevation_gain_m": 2150,
    "elevation_loss_m": 2147,
    "difficulty": "hard",
    "terrain_type": "hilly",
    "validation_status": "ok",
    "has_profile": true,
    "profile_file": "profiles/masca_loop.json"
  },
  "geometry": {
    "type": "LineString",
    "coordinates": [
      [-16.757, 28.291, 120],
      [-16.758, 28.292, 126]
    ]
  }
}
````

### Route index (for UI)

A lightweight JSON file with only metadata:

```json
[
  {
    "route_id": "masca_loop",
    "name": "Masca Loop",
    "distance_km": 82.4,
    "elevation_gain_m": 2150,
    "difficulty": "hard",
    "terrain_type": "hilly",
    "is_loop": true,
    "validation_status": "ok"
  }
]
```

---

## Project Structure

```text
project/
  data/
    raw_gpx/           # input GPX files
    processed/         # generated outputs
      routes.geojson
      routes_index.json
      build_manifest.json
      profiles/
        masca_loop.json
      routes/
        masca_loop.geojson
  scripts/
    preprocess_gpx.py  # main pipeline
```

---

## Installation

This project uses a minimal Python setup.

Install dependencies:

```bash
pip install gpxpy
```

or (if using `uv`):

```bash
uv pip install gpxpy
```

---

## Usage

Place your `.gpx` files in:

```text
data/raw_gpx/
```

Then run:

```bash
python scripts/preprocess_gpx.py
```

or:

```bash
uv run python scripts/preprocess_gpx.py
```

Useful v0.3 options:

```bash
uv run python scripts/preprocess_gpx.py --full-rebuild
uv run python scripts/preprocess_gpx.py --only masca_loop
uv run python scripts/preprocess_gpx.py --skip-profiles
uv run python scripts/preprocess_gpx.py --raw-dir data/raw_gpx --processed-dir data/processed --verbose
```

Useful v0.4 options:

```bash
uv run python scripts/preprocess_gpx.py --validate-only
uv run python scripts/preprocess_gpx.py --only-group trf_1_adeje_west_coast_and_masca_valley
uv run python scripts/preprocess_gpx.py --no-emit-frontend-artifacts
uv run python scripts/preprocess_gpx.py --no-emit-segments --no-emit-climbs
uv run python scripts/preprocess_gpx.py --geometry-mode preview
uv run python scripts/preprocess_gpx.py --no-build-report
```

Developer shortcuts:

```bash
make build
make rebuild
make test
make validate
```

Repeat runs use the manifest to skip unchanged GPX files while still refreshing the combined outputs.

---

## Output

After running, you will find:

```text
data/processed/routes.geojson
data/processed/routes_index.json
data/processed/build_manifest.json
data/processed/build_report.json
data/processed/build_report.md
data/processed/routes/<route_id>.geojson
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

## How it works

### 1. Parse GPX

* Extracts points from:

  * tracks → segments → points
  * falls back to routes if needed

### 2. Clean data

* removes invalid or duplicate points
* ensures consistent coordinate structure

### 3. Compute metrics

* distance via haversine formula
* elevation gain/loss from smoothed elevation values with noise thresholding
* summary statistics (min/max elevation, bbox, centroid, etc.)
* frontend metadata for difficulty, climbiness, route direction, search, and quality flags

### 4. Build GeoJSON

* converts each route into a simplified display `LineString`
* attaches computed metrics as properties
* writes both combined and per-route GeoJSON files

---

## Design Principles

* **Simple over complex** — no heavy GIS dependencies
* **Deterministic** — same input produces same output
* **Transparent** — metrics are easy to inspect and verify
* **Extensible** — easy to add new metrics or transformations

---

## Limitations

* Elevation data in GPX can still be imperfect after smoothing
* Geometry simplification uses a lightweight display tolerance, not a full GIS stack
* Assumes one route per GPX file

---

## Roadmap

Possible future improvements:

* optional elevation profile generation
* richer route categorisation and tags
* frontend lazy-loading based on selected route cards

---

## Example Leaflet Usage

```javascript
fetch("/data/processed/routes.geojson")
  .then(r => r.json())
  .then(data => {
    L.geoJSON(data, {
      onEachFeature: (feature, layer) => {
        const p = feature.properties;
        layer.bindPopup(`
          <strong>${p.name}</strong><br>
          Distance: ${p.distance_km} km<br>
          Elevation gain: ${p.elevation_gain_m} m
        `);
      }
    }).addTo(map);
  });
```

---

## Contributing

Contributions are welcome, especially around:

* improving elevation accuracy
* performance optimisation
* additional route analytics
* testing and validation

---

## License

MIT License (or specify your preferred license)

---

## Summary

This tool provides a clean bridge between:

**GPX (raw cycling data)** → **GeoJSON (map-ready format)**

with useful metrics included, making it a solid foundation for building cycling route applications.

```
