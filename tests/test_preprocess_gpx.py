import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import preprocess_gpx as p


def point(lat, lon, ele=None):
    return {"lat": lat, "lon": lon, "ele": ele, "time": None}


def synthetic_climb_route():
    elevations = [0, 40, 85, 130, 170, 210, 250, 245, 230, 180, 120, 60]
    return [point(0, index * 0.005, ele) for index, ele in enumerate(elevations)]


def fake_feature(route_id, name, distance=10.0, gain=400, lon_offset=0.0):
    props = {
        "route_id": route_id,
        "name": name,
        "distance_km": distance,
        "elevation_gain_m": gain,
        "start_lat": 0.0,
        "start_lon": lon_offset,
        "end_lat": 0.0,
        "end_lon": lon_offset + 0.1,
        "centroid_lat": 0.0,
        "centroid_lon": lon_offset + 0.05,
        "difficulty": "moderate",
        "terrain_type": "hilly",
        "validation_status": "ok",
        "validation_messages": [],
        "quality_score": 100,
        "bbox": [lon_offset, 0.0, lon_offset + 0.1, 0.0],
    }
    return {"type": "Feature", "properties": props, "geometry": {"type": "LineString", "coordinates": []}}


def write_gpx(path, coords):
    points = "\n".join(
        f'<trkpt lat="{lat}" lon="{lon}"><ele>{ele}</ele></trkpt>'
        for lat, lon, ele in coords
    )
    path.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><name>{path.stem}</name><trkseg>{points}</trkseg></trk>
</gpx>
""",
        encoding="utf-8",
    )


def test_haversine_distance_sanity():
    distance = p.haversine_m(0, 0, 0, 1)
    assert 111_000 <= distance <= 112_000


def test_elevation_smoothing_uses_local_average():
    points = [point(0, 0, 0), point(0, 0.001, 30), point(0, 0.002, 60)]
    assert p.smooth_elevations(points, window_size=3) == [15, 30, 45]


def test_ascent_descent_thresholding():
    points = [
        point(0, 0, 0),
        point(0, 0.001, 2),
        point(0, 0.002, 6),
        point(0, 0.003, 3),
    ]
    metrics = p.compute_elevation_metrics(
        points, elevation_threshold_m=3, smoothing_window=1
    )
    assert metrics["elevation_gain_m"] == 4
    assert metrics["elevation_loss_m"] == 3


def test_loop_detection():
    points = [point(51.5, -0.1), point(51.501, -0.101), point(51.5, -0.1005)]
    assert p.is_loop_route(points, threshold_m=100)
    assert p.detect_route_direction(points, distance_km=5, loop_threshold_m=100) == "loop"


def test_route_difficulty_classification():
    assert p.classify_difficulty(20, 200) == "easy"
    assert p.classify_difficulty(60, 900) == "moderate"
    assert p.classify_difficulty(100, 1800) == "hard"
    assert p.classify_difficulty(180, 3200) == "extreme"


def test_geometry_simplification_keeps_safe_minimum():
    points = [point(0, 0), point(0, 0.001), point(0, 0.002), point(0, 0.003)]
    simplified = p.simplify_points(points, tolerance=1)
    assert len(simplified) >= p.MIN_SIMPLIFIED_POINTS
    assert simplified[0] == points[0]
    assert simplified[-1] == points[-1]


def test_validation_catches_invalid_coordinates():
    points = [point(91, 0, 10), point(91.1, 0.1, 20)]
    validation = p.validate_route(points)
    assert validation["validation_status"] == "error"
    assert any("invalid lat/lon" in message for message in validation["validation_messages"])


def test_manifest_change_detection(tmp_path):
    gpx_path = tmp_path / "sample_route.gpx"
    gpx_path.write_text("<gpx></gpx>", encoding="utf-8")
    manifest = {
        "version": p.MANIFEST_VERSION,
        "routes": {
            p.slugify(gpx_path.stem): {
                "source": p.source_manifest_entry(gpx_path),
                "feature": {},
            }
        },
    }

    assert not p.route_needs_rebuild(gpx_path, manifest)

    gpx_path.write_text("<gpx><trk /></gpx>", encoding="utf-8")
    os.utime(gpx_path, ns=(gpx_path.stat().st_atime_ns, gpx_path.stat().st_mtime_ns + 1))

    assert p.route_needs_rebuild(gpx_path, manifest)


def test_route_segmentation_classifies_climb_and_descent():
    segments = p.segment_route("test_route", synthetic_climb_route(), min_segment_length_km=0.05)
    segment_types = {segment["type"] for segment in segments["segments"]}
    assert "climb" in segment_types
    assert "descent" in segment_types
    assert all(segment["length_km"] > 0 for segment in segments["segments"])


def test_climb_extraction_finds_main_climb():
    climbs = p.extract_climbs(
        "test_route",
        synthetic_climb_route(),
        min_length_km=0.2,
        min_gain_m=50,
        min_avg_gradient_pct=2,
    )
    assert len(climbs["climbs"]) == 1
    climb = climbs["climbs"][0]
    assert climb["elevation_gain_m"] >= 180
    assert climb["category"] in {"short", "medium", "major"}


def test_duplicate_detection_groups_near_identical_routes():
    features = [
        fake_feature("route_a", "Masca Loop"),
        fake_feature("route_b", "Masca Loop Copy", distance=10.1, gain=410, lon_offset=0.0002),
        fake_feature("route_c", "Far Ride", distance=30, gain=100, lon_offset=1.0),
    ]
    p.apply_route_variant_metadata(features)
    by_id = {feature["properties"]["route_id"]: feature["properties"] for feature in features}
    assert by_id["route_b"]["duplicate_of"] == "route_a"
    assert by_id["route_a"]["is_primary_variant"]
    assert by_id["route_c"]["duplicate_of"] is None


def test_midpoint_and_extrema_use_distance_and_elevation():
    points = [
        point(0, 0, 10),
        point(0, 0.01, 50),
        point(0, 0.02, 5),
        point(0, 0.03, 30),
    ]
    midpoint = p.compute_midpoint(points)
    highest, lowest = p.compute_extrema_points(points)
    assert midpoint["distance_km"] > 0
    assert highest["elevation_m"] == 50
    assert lowest["elevation_m"] == 5


def test_loop_spatial_metadata_has_closure_and_clockwise_hint():
    points = [
        point(0, 0, 10),
        point(0, 0.001, 20),
        point(0.001, 0.001, 30),
        point(0.001, 0, 15),
        point(0, 0, 10),
    ]
    metadata = p.compute_route_spatial_metadata(points)
    assert metadata["loop_closure_distance_m"] == 0
    assert metadata["estimated_moving_bearing_deg"] is None
    assert metadata["clockwise_hint"] in {"clockwise", "counterclockwise"}


def test_frontend_artifact_generation_shape():
    feature = fake_feature("route_a", "Masca Loop")
    feature["properties"].update(
        {
            "num_climbs": 1,
            "main_climb_gain_m": 220,
            "route_group_id": "route_a",
            "is_primary_variant": True,
            "profile_file": "profiles/route_a.json",
            "preview_geometry_file": "routes_preview/route_a.geojson",
            "segments_file": "segments/route_a.json",
            "climbs_file": "climbs/route_a.json",
            "detail_geometry_file": "routes_detail/route_a.geojson",
        }
    )
    artifacts = p.build_frontend_artifacts([feature])
    assert artifacts["routes_list"][0]["route_id"] == "route_a"
    assert artifacts["routes_map_index"][0]["preview_geometry_file"]
    assert artifacts["route_lookup"]["route_a"]["segments_file"] == "segments/route_a.json"


def test_pipeline_writes_v04_artifacts_and_report(tmp_path):
    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    raw_dir.mkdir()
    write_gpx(
        raw_dir / "sample_loop.gpx",
        [
            (0, 0, 0),
            (0, 0.004, 50),
            (0.004, 0.004, 120),
            (0.004, 0, 40),
            (0, 0, 0),
        ],
    )
    config = p.default_config()
    config.update(
        {
            "raw_dir": raw_dir,
            "processed_dir": processed_dir,
            "routes_geojson_path": processed_dir / "routes.geojson",
            "routes_index_path": processed_dir / "routes_index.json",
            "per_route_dir": processed_dir / "routes",
            "profiles_dir": processed_dir / "profiles",
            "segments_dir": processed_dir / "segments",
            "climbs_dir": processed_dir / "climbs",
            "routes_preview_dir": processed_dir / "routes_preview",
            "routes_detail_dir": processed_dir / "routes_detail",
            "frontend_dir": processed_dir / "frontend",
            "build_manifest_path": processed_dir / "build_manifest.json",
            "build_report_json_path": processed_dir / "build_report.json",
            "build_report_md_path": processed_dir / "build_report.md",
            "full_rebuild": True,
        }
    )
    p.run_pipeline(config)

    manifest = p.load_manifest(processed_dir / "build_manifest.json")
    route_index = __import__("json").loads((processed_dir / "routes_index.json").read_text())
    assert manifest["version"] == p.MANIFEST_VERSION
    assert route_index[0]["segments_file"] == "segments/sample_loop.json"
    assert (processed_dir / "segments" / "sample_loop.json").exists()
    assert (processed_dir / "climbs" / "sample_loop.json").exists()
    assert (processed_dir / "routes_preview" / "sample_loop.geojson").exists()
    assert (processed_dir / "frontend" / "route_lookup.json").exists()
    assert (processed_dir / "build_report.json").exists()
    assert (processed_dir / "build_report.md").read_text(encoding="utf-8").startswith("# GPX")
