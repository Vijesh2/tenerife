#!/usr/bin/env python3
"""Convert GPX cycling routes into app-ready GeoJSON and route metrics."""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

try:
    import gpxpy
except ImportError as exc:  # pragma: no cover - depends on local environment
    raise SystemExit(
        "Missing dependency: gpxpy. Install it with `uv pip install gpxpy` "
        "or `pip install gpxpy`."
    ) from exc


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_GPX_DIR = PROJECT_ROOT / "data" / "raw_gpx"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
ROUTES_GEOJSON_PATH = PROCESSED_DIR / "routes.geojson"
ROUTES_INDEX_PATH = PROCESSED_DIR / "routes_index.json"
PER_ROUTE_DIR = PROCESSED_DIR / "routes"
PROFILES_DIR = PROCESSED_DIR / "profiles"
SEGMENTS_DIR = PROCESSED_DIR / "segments"
CLIMBS_DIR = PROCESSED_DIR / "climbs"
ROUTES_PREVIEW_DIR = PROCESSED_DIR / "routes_preview"
ROUTES_DETAIL_DIR = PROCESSED_DIR / "routes_detail"
FRONTEND_DIR = PROCESSED_DIR / "frontend"
BUILD_MANIFEST_PATH = PROCESSED_DIR / "build_manifest.json"
BUILD_REPORT_JSON_PATH = PROCESSED_DIR / "build_report.json"
BUILD_REPORT_MD_PATH = PROCESSED_DIR / "build_report.md"

EARTH_RADIUS_M = 6_371_000.0
MANIFEST_VERSION = 2
ELEVATION_SMOOTHING_WINDOW = 5
ELEVATION_THRESHOLD_M = 3.0
# Decimal degrees; roughly 11 m at the equator. Used only for display geometry.
SIMPLIFICATION_TOLERANCE = 0.0001
PREVIEW_SIMPLIFICATION_TOLERANCE = 0.0008
DETAIL_SIMPLIFICATION_TOLERANCE = 0.00005
MIN_SIMPLIFIED_POINTS = 2
LOOP_CLOSURE_THRESHOLD_M = 150.0
OUT_AND_BACK_ENDPOINT_THRESHOLD_M = 300.0
OUT_AND_BACK_MIN_ROUTE_DISTANCE_KM = 2.0
PROFILE_TARGET_POINTS = 200
PROFILE_MIN_SPACING_KM = 0.05

SEGMENT_GRADE_THRESHOLD_PCT = 3.0
MIN_SEGMENT_LENGTH_KM = 0.2
CLIMB_MIN_LENGTH_KM = 0.3
CLIMB_MIN_GAIN_M = 20.0
CLIMB_MIN_AVG_GRADIENT_PCT = 3.0
DUPLICATE_DISTANCE_RATIO = 0.03
DUPLICATE_GAIN_RATIO = 0.12
DUPLICATE_ENDPOINT_THRESHOLD_M = 350.0
DUPLICATE_CENTROID_THRESHOLD_M = 600.0

VALIDATION_MIN_POINTS = 2
VALIDATION_LOW_POINT_WARNING = 10
VALIDATION_MIN_DISTANCE_KM = 0.2
VALIDATION_STATIONARY_RATIO_WARNING = 0.35
VALIDATION_DUPLICATE_RATIO_WARNING = 0.5
VALIDATION_MAX_CLIMBING_RATE_M_PER_KM = 120.0

DIFFICULTY_THRESHOLDS = {
    "easy": {"max_distance_km": 25.0, "max_gain_m": 300},
    "moderate": {"max_distance_km": 70.0, "max_gain_m": 1200},
    "hard": {"max_distance_km": 130.0, "max_gain_m": 2500},
}

TERRAIN_THRESHOLDS_M_PER_KM = {
    "flat": 10.0,
    "rolling": 25.0,
    "hilly": 45.0,
}


class RoutePoint(TypedDict):
    lat: float
    lon: float
    ele: float | None
    time: str | None


class PreprocessConfig(TypedDict):
    raw_dir: Path
    processed_dir: Path
    routes_geojson_path: Path
    routes_index_path: Path
    per_route_dir: Path
    profiles_dir: Path
    segments_dir: Path
    climbs_dir: Path
    routes_preview_dir: Path
    routes_detail_dir: Path
    frontend_dir: Path
    build_manifest_path: Path
    build_report_json_path: Path
    build_report_md_path: Path
    full_rebuild: bool
    only: str | None
    only_group: str | None
    skip_profiles: bool
    emit_frontend_artifacts: bool
    emit_segments: bool
    emit_climbs: bool
    geometry_mode: str
    validate_only: bool
    build_report: bool
    verbose: bool


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the haversine distance between two WGS84 points in metres."""
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_M * c


def slugify(value: str) -> str:
    """Create a stable, readable route id from a filename stem."""
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "route"


def name_from_filename(gpx_path: Path) -> str:
    """Create a human-readable route name from a filename stem."""
    words = re.sub(r"[_-]+", " ", gpx_path.stem).strip()
    return words.title() if words else "Route"


def normalize_search_text(value: str) -> str:
    """Return a small normalized string useful for frontend search."""
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return re.sub(r"\s+", " ", normalized)


def meaningful_name(value: str | None) -> str | None:
    """Return a stripped GPX name when it contains visible text."""
    if value is None:
        return None

    name = value.strip()
    return name or None


def extract_route_name(gpx: Any, gpx_path: Path) -> str:
    """Prefer GPX track/route metadata, falling back to the filename title."""
    for track in gpx.tracks:
        name = meaningful_name(track.name)
        if name is not None:
            return name

    for route in gpx.routes:
        name = meaningful_name(route.name)
        if name is not None:
            return name

    return name_from_filename(gpx_path)


def point_time_iso(point: Any) -> str | None:
    """Return an ISO timestamp string when the GPX point has a timestamp."""
    if point.time is None:
        return None
    return point.time.isoformat()


def point_to_route_point(point: Any) -> RoutePoint | None:
    """Convert a gpxpy point object to the internal point representation."""
    if point.latitude is None or point.longitude is None:
        return None

    elevation = None if point.elevation is None else float(point.elevation)
    return {
        "lat": float(point.latitude),
        "lon": float(point.longitude),
        "ele": elevation,
        "time": point_time_iso(point),
    }


def parse_gpx(gpx_path: Path) -> Any:
    """Parse a GPX file with consistent file handling."""
    with gpx_path.open("r", encoding="utf-8") as file:
        return gpxpy.parse(file)


def extract_points(gpx: Any) -> list[RoutePoint]:
    """Extract flattened track points, falling back to route points if needed."""
    track_points: list[RoutePoint] = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                route_point = point_to_route_point(point)
                if route_point is not None:
                    track_points.append(route_point)

    if track_points:
        return track_points

    route_points: list[RoutePoint] = []
    for route in gpx.routes:
        for point in route.points:
            route_point = point_to_route_point(point)
            if route_point is not None:
                route_points.append(route_point)

    return route_points


def remove_consecutive_duplicates(points: list[RoutePoint]) -> list[RoutePoint]:
    """Remove adjacent points with the same latitude and longitude."""
    deduped: list[RoutePoint] = []

    for point in points:
        if deduped and point["lat"] == deduped[-1]["lat"] and point["lon"] == deduped[-1]["lon"]:
            continue
        deduped.append(point)

    return deduped


def is_valid_coordinate(point: RoutePoint) -> bool:
    """Return whether a point has a plausible WGS84 latitude/longitude."""
    return -90 <= point["lat"] <= 90 and -180 <= point["lon"] <= 180


def count_duplicate_points(points: list[RoutePoint]) -> int:
    """Count repeated coordinates after their first occurrence."""
    seen: set[tuple[float, float]] = set()
    duplicates = 0
    for point in points:
        key = (point["lat"], point["lon"])
        if key in seen:
            duplicates += 1
        seen.add(key)
    return duplicates


def smooth_elevations(
    points: list[RoutePoint], window_size: int = ELEVATION_SMOOTHING_WINDOW
) -> list[float | None]:
    """Smooth elevation values with a small moving average for metrics only."""
    if not points:
        return []

    if window_size < 1:
        window_size = 1
    if window_size % 2 == 0:
        window_size += 1

    radius = window_size // 2
    elevations = [point["ele"] for point in points]
    smoothed: list[float | None] = []

    for index, elevation in enumerate(elevations):
        if elevation is None:
            smoothed.append(None)
            continue

        start = max(0, index - radius)
        end = min(len(elevations), index + radius + 1)
        window_values = [
            value for value in elevations[start:end] if value is not None
        ]
        if not window_values:
            smoothed.append(elevation)
            continue

        smoothed.append(sum(window_values) / len(window_values))

    return smoothed


def compute_elevation_metrics(
    points: list[RoutePoint],
    elevation_threshold_m: float = ELEVATION_THRESHOLD_M,
    smoothing_window: int = ELEVATION_SMOOTHING_WINDOW,
) -> dict[str, Any]:
    """Compute elevation metrics from smoothed elevation values."""
    smoothed_elevations = smooth_elevations(points, smoothing_window)
    elevation_gain_m = 0.0
    elevation_loss_m = 0.0

    for previous, current in zip(smoothed_elevations, smoothed_elevations[1:]):
        if previous is None or current is None:
            continue

        delta_ele = current - previous
        if abs(delta_ele) >= elevation_threshold_m:
            if delta_ele > 0:
                elevation_gain_m += delta_ele
            else:
                elevation_loss_m += abs(delta_ele)

    valid_elevations = [
        elevation for elevation in smoothed_elevations if elevation is not None
    ]

    return {
        "elevation_gain_m": round(elevation_gain_m),
        "elevation_loss_m": round(elevation_loss_m),
        "min_elevation_m": round(min(valid_elevations)) if valid_elevations else None,
        "max_elevation_m": round(max(valid_elevations)) if valid_elevations else None,
        "start_elevation_m": round(valid_elevations[0]) if valid_elevations else None,
        "end_elevation_m": round(valid_elevations[-1]) if valid_elevations else None,
        "has_elevation": bool(valid_elevations),
    }


def classify_difficulty(distance_km: float, elevation_gain_m: int | float) -> str:
    """Classify route difficulty with deliberately simple cycling heuristics.

    This first-pass rule treats distance and climbing as independent ways a
    route can become harder: short/low-climb rides are easy, medium rides are
    moderate, long or climb-heavy rides are hard, and anything beyond those
    practical card-filter bands is extreme.
    """
    if (
        distance_km <= DIFFICULTY_THRESHOLDS["easy"]["max_distance_km"]
        and elevation_gain_m <= DIFFICULTY_THRESHOLDS["easy"]["max_gain_m"]
    ):
        return "easy"
    if (
        distance_km <= DIFFICULTY_THRESHOLDS["moderate"]["max_distance_km"]
        and elevation_gain_m <= DIFFICULTY_THRESHOLDS["moderate"]["max_gain_m"]
    ):
        return "moderate"
    if (
        distance_km <= DIFFICULTY_THRESHOLDS["hard"]["max_distance_km"]
        and elevation_gain_m <= DIFFICULTY_THRESHOLDS["hard"]["max_gain_m"]
    ):
        return "hard"
    return "extreme"


def classify_terrain(climbing_rate_m_per_km: float | None) -> str:
    """Classify climbiness from metres gained per kilometre."""
    if climbing_rate_m_per_km is None:
        return "unknown"
    if climbing_rate_m_per_km <= TERRAIN_THRESHOLDS_M_PER_KM["flat"]:
        return "flat"
    if climbing_rate_m_per_km <= TERRAIN_THRESHOLDS_M_PER_KM["rolling"]:
        return "rolling"
    if climbing_rate_m_per_km <= TERRAIN_THRESHOLDS_M_PER_KM["hilly"]:
        return "hilly"
    return "mountainous"


def is_loop_route(
    points: list[RoutePoint], threshold_m: float = LOOP_CLOSURE_THRESHOLD_M
) -> bool:
    """Return whether the route ends close to where it started."""
    if len(points) < 2:
        return False
    return (
        haversine_m(
            points[0]["lat"],
            points[0]["lon"],
            points[-1]["lat"],
            points[-1]["lon"],
        )
        <= threshold_m
    )


def detect_route_direction(
    points: list[RoutePoint],
    distance_km: float,
    loop_threshold_m: float = LOOP_CLOSURE_THRESHOLD_M,
) -> str:
    """Return a lightweight direction label for route filtering."""
    if len(points) < 2:
        return "unknown"
    if is_loop_route(points, loop_threshold_m):
        return "loop"

    endpoint_distance_m = haversine_m(
        points[0]["lat"], points[0]["lon"], points[-1]["lat"], points[-1]["lon"]
    )
    if (
        distance_km >= OUT_AND_BACK_MIN_ROUTE_DISTANCE_KM
        and endpoint_distance_m <= OUT_AND_BACK_ENDPOINT_THRESHOLD_M
    ):
        return "out_and_back"
    return "point_to_point"


def perpendicular_distance(point: RoutePoint, start: RoutePoint, end: RoutePoint) -> float:
    """Return point-to-line distance in coordinate degrees for RDP."""
    delta_lon = end["lon"] - start["lon"]
    delta_lat = end["lat"] - start["lat"]

    if delta_lon == 0 and delta_lat == 0:
        return math.hypot(point["lon"] - start["lon"], point["lat"] - start["lat"])

    numerator = abs(
        delta_lat * point["lon"]
        - delta_lon * point["lat"]
        + end["lon"] * start["lat"]
        - end["lat"] * start["lon"]
    )
    denominator = math.hypot(delta_lon, delta_lat)
    return numerator / denominator


def simplify_points(
    points: list[RoutePoint], tolerance: float = SIMPLIFICATION_TOLERANCE
) -> list[RoutePoint]:
    """Simplify display geometry with the Ramer-Douglas-Peucker algorithm."""
    if tolerance <= 0 or len(points) <= 2:
        return points.copy()

    max_distance = 0.0
    split_index = 0
    start = points[0]
    end = points[-1]

    for index in range(1, len(points) - 1):
        distance = perpendicular_distance(points[index], start, end)
        if distance > max_distance:
            max_distance = distance
            split_index = index

    if max_distance <= tolerance:
        return [start, end]

    left = simplify_points(points[: split_index + 1], tolerance)
    right = simplify_points(points[split_index:], tolerance)
    return left[:-1] + right


def compute_centroid(points: list[RoutePoint]) -> tuple[float, float]:
    """Return a simple average-coordinate centroid as (lat, lon)."""
    return (
        sum(point["lat"] for point in points) / len(points),
        sum(point["lon"] for point in points) / len(points),
    )


def compute_total_distance_m(points: list[RoutePoint]) -> float:
    """Return cumulative route distance in metres."""
    total_distance_m = 0.0
    for previous, current in zip(points, points[1:]):
        total_distance_m += haversine_m(
            previous["lat"], previous["lon"], current["lat"], current["lon"]
        )
    return total_distance_m


def cumulative_distances_km(points: list[RoutePoint]) -> list[float]:
    """Return cumulative distance at each route point in kilometres."""
    distances = [0.0]
    for previous, current in zip(points, points[1:]):
        distances.append(
            distances[-1]
            + haversine_m(
                previous["lat"], previous["lon"], current["lat"], current["lon"]
            )
            / 1000
        )
    return distances


def point_summary(point: RoutePoint, distance_km: float | None = None) -> dict[str, Any]:
    """Return a compact frontend point object."""
    summary: dict[str, Any] = {
        "lat": round(point["lat"], 6),
        "lon": round(point["lon"], 6),
        "elevation_m": round(point["ele"], 1) if point["ele"] is not None else None,
    }
    if distance_km is not None:
        summary["distance_km"] = round(distance_km, 3)
    return summary


def compute_midpoint(
    points: list[RoutePoint], distances_km: list[float] | None = None
) -> dict[str, Any]:
    """Return the point nearest half cumulative distance."""
    if not points:
        return {}
    distances = distances_km or cumulative_distances_km(points)
    target = distances[-1] / 2
    index = min(range(len(points)), key=lambda item: abs(distances[item] - target))
    return point_summary(points[index], distances[index])


def compute_extrema_points(
    points: list[RoutePoint], distances_km: list[float] | None = None
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return highest and lowest elevation points with route distance."""
    distances = distances_km or cumulative_distances_km(points)
    indexed = [
        (index, point)
        for index, point in enumerate(points)
        if point["ele"] is not None
    ]
    if not indexed:
        return None, None
    highest_index, highest = max(indexed, key=lambda item: item[1]["ele"] or 0)
    lowest_index, lowest = min(indexed, key=lambda item: item[1]["ele"] or 0)
    return (
        point_summary(highest, distances[highest_index]),
        point_summary(lowest, distances[lowest_index]),
    )


def compute_bearing_deg(start: RoutePoint, end: RoutePoint) -> float:
    """Return initial bearing from start to end in degrees."""
    lat1 = math.radians(start["lat"])
    lat2 = math.radians(end["lat"])
    delta_lon = math.radians(end["lon"] - start["lon"])
    x = math.sin(delta_lon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - (
        math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon)
    )
    return round((math.degrees(math.atan2(x, y)) + 360) % 360, 1)


def compute_spatial_extent_km(points: list[RoutePoint]) -> float:
    """Approximate route footprint as the diagonal of its bounding box."""
    if not points:
        return 0.0
    min_lat = min(point["lat"] for point in points)
    max_lat = max(point["lat"] for point in points)
    min_lon = min(point["lon"] for point in points)
    max_lon = max(point["lon"] for point in points)
    return round(haversine_m(min_lat, min_lon, max_lat, max_lon) / 1000, 2)


def compute_clockwise_hint(points: list[RoutePoint]) -> str | None:
    """Return a rough clockwise/counterclockwise hint for loop routes."""
    if len(points) < 4 or not is_loop_route(points):
        return None
    area = 0.0
    for previous, current in zip(points, points[1:]):
        area += (current["lon"] - previous["lon"]) * (
            current["lat"] + previous["lat"]
        )
    if abs(area) < 1e-12:
        return None
    return "clockwise" if area > 0 else "counterclockwise"


def compute_route_spatial_metadata(points: list[RoutePoint]) -> dict[str, Any]:
    """Compute route-level spatial metadata for frontend UX."""
    distances = cumulative_distances_km(points)
    highest, lowest = compute_extrema_points(points, distances)
    loop_closure_distance_m = haversine_m(
        points[0]["lat"], points[0]["lon"], points[-1]["lat"], points[-1]["lon"]
    )
    is_loop = loop_closure_distance_m <= LOOP_CLOSURE_THRESHOLD_M
    metadata = {
        "start_point": point_summary(points[0], 0.0),
        "end_point": point_summary(points[-1], distances[-1]),
        "mid_point": compute_midpoint(points, distances),
        "highest_point": highest,
        "lowest_point": lowest,
        "estimated_moving_bearing_deg": None
        if is_loop
        else compute_bearing_deg(points[0], points[-1]),
        "spatial_extent_km": compute_spatial_extent_km(points),
        "loop_closure_distance_m": round(loop_closure_distance_m, 1),
        "clockwise_hint": compute_clockwise_hint(points) if is_loop else None,
        "start_finish_cluster_id": cluster_id_for_point(points[0]) if is_loop else None,
    }
    return metadata


def cluster_id_for_point(point: RoutePoint, precision: int = 2) -> str:
    """Return a coarse stable start/finish area id."""
    return f"cluster_{round(point['lat'], precision)}_{round(point['lon'], precision)}"


def compute_metrics(
    points: list[RoutePoint],
    display_points: list[RoutePoint],
    raw_point_count: int | None = None,
) -> dict[str, Any]:
    """Compute summary route metrics from a cleaned route point list."""
    total_distance_m = compute_total_distance_m(points)
    distance_km = round(total_distance_m / 1000, 2)
    elevation_metrics = compute_elevation_metrics(points)
    elevation_gain_m = elevation_metrics["elevation_gain_m"]
    min_elevation_m = elevation_metrics["min_elevation_m"]
    max_elevation_m = elevation_metrics["max_elevation_m"]
    elevation_range_m = (
        max_elevation_m - min_elevation_m
        if max_elevation_m is not None and min_elevation_m is not None
        else None
    )
    climbing_rate_m_per_km = (
        round(elevation_gain_m / distance_km, 1) if distance_km > 0 else None
    )

    lats = [point["lat"] for point in points]
    lons = [point["lon"] for point in points]
    centroid_lat, centroid_lon = compute_centroid(points)
    is_loop = is_loop_route(points)

    return {
        "distance_km": distance_km,
        **elevation_metrics,
        "elevation_range_m": elevation_range_m,
        "climbing_rate_m_per_km": climbing_rate_m_per_km,
        "difficulty": classify_difficulty(distance_km, elevation_gain_m),
        "terrain_type": classify_terrain(climbing_rate_m_per_km),
        "is_loop": is_loop,
        "route_direction": detect_route_direction(points, distance_km),
        "start_lat": points[0]["lat"],
        "start_lon": points[0]["lon"],
        "end_lat": points[-1]["lat"],
        "end_lon": points[-1]["lon"],
        "num_points": len(points),
        "num_points_original": raw_point_count if raw_point_count is not None else len(points),
        "num_points_display": len(display_points),
        "bbox": [min(lons), min(lats), max(lons), max(lats)],
        "centroid_lat": centroid_lat,
        "centroid_lon": centroid_lon,
    }


def validate_route(
    points: list[RoutePoint],
    metrics: dict[str, Any] | None = None,
    raw_point_count: int | None = None,
) -> dict[str, Any]:
    """Return lightweight quality metadata for a route."""
    messages: list[str] = []
    errors: list[str] = []

    if len(points) < VALIDATION_MIN_POINTS:
        errors.append("too few valid points")

    invalid_count = sum(1 for point in points if not is_valid_coordinate(point))
    if invalid_count:
        errors.append(f"{invalid_count} point(s) have invalid lat/lon")

    if len(points) < VALIDATION_LOW_POINT_WARNING:
        messages.append("low point count")

    if points:
        lats = [point["lat"] for point in points]
        lons = [point["lon"] for point in points]
        if min(lats) < -90 or max(lats) > 90 or min(lons) < -180 or max(lons) > 180:
            errors.append("bbox contains invalid coordinate range")

    has_elevation = any(point["ele"] is not None for point in points)
    if not has_elevation:
        messages.append("missing elevation data")

    if metrics is not None:
        distance_km = metrics.get("distance_km", 0) or 0
        climbing_rate = metrics.get("climbing_rate_m_per_km")
        if distance_km < VALIDATION_MIN_DISTANCE_KM:
            messages.append("extremely short route")
        if (
            climbing_rate is not None
            and climbing_rate > VALIDATION_MAX_CLIMBING_RATE_M_PER_KM
        ):
            messages.append("suspiciously high climbing rate")
        bbox = metrics.get("bbox")
        if bbox and (bbox[0] == bbox[2] and bbox[1] == bbox[3]):
            messages.append("stationary bbox")

    duplicate_ratio = 0.0
    if raw_point_count:
        duplicate_ratio = max(raw_point_count - len(points), 0) / raw_point_count
        if duplicate_ratio >= VALIDATION_DUPLICATE_RATIO_WARNING:
            messages.append("duplicate-heavy route")

    unique_ratio = 1.0
    if points:
        unique_ratio = len({(point["lat"], point["lon"]) for point in points}) / len(points)
        if unique_ratio <= VALIDATION_STATIONARY_RATIO_WARNING:
            messages.append("mostly stationary route")

    validation_messages = errors + messages
    if errors:
        status = "error"
    elif len(messages) >= 2:
        status = "warning"
    elif messages:
        status = "review"
    else:
        status = "ok"

    penalty = len(errors) * 35 + len(messages) * 10
    if duplicate_ratio >= VALIDATION_DUPLICATE_RATIO_WARNING:
        penalty += 10
    if unique_ratio <= VALIDATION_STATIONARY_RATIO_WARNING:
        penalty += 10

    return {
        "validation_status": status,
        "validation_messages": validation_messages,
        "has_elevation": has_elevation,
        "quality_score": max(0, min(100, 100 - penalty)),
    }


def geojson_coordinates(points: list[RoutePoint]) -> list[list[float]]:
    """Convert internal points to GeoJSON LineString coordinate order."""
    coordinates: list[list[float]] = []

    for point in points:
        coordinate = [point["lon"], point["lat"]]
        if point["ele"] is not None:
            coordinate.append(point["ele"])
        coordinates.append(coordinate)

    return coordinates


def feature_with_geometry(
    properties: dict[str, Any], points: list[RoutePoint]
) -> dict[str, Any]:
    """Build a GeoJSON feature from existing properties and route points."""
    return {
        "type": "Feature",
        "properties": properties,
        "geometry": {
            "type": "LineString",
            "coordinates": geojson_coordinates(points),
        },
    }


def build_profile_series(
    points: list[RoutePoint],
    target_points: int = PROFILE_TARGET_POINTS,
    min_spacing_km: float = PROFILE_MIN_SPACING_KM,
) -> list[dict[str, float]]:
    """Build a downsampled elevation profile using smoothed elevations."""
    smoothed_elevations = smooth_elevations(points)
    cumulative_distance_km = 0.0
    profile: list[dict[str, float]] = []

    previous_kept_distance_km: float | None = None
    for index, point in enumerate(points):
        if index > 0:
            previous = points[index - 1]
            cumulative_distance_km += (
                haversine_m(
                    previous["lat"], previous["lon"], point["lat"], point["lon"]
                )
                / 1000
            )

        elevation = smoothed_elevations[index]
        if elevation is None:
            continue

        if (
            previous_kept_distance_km is None
            or cumulative_distance_km - previous_kept_distance_km >= min_spacing_km
            or index == len(points) - 1
        ):
            profile.append(
                {
                    "distance_km": round(cumulative_distance_km, 3),
                    "elevation_m": round(elevation, 1),
                }
            )
            previous_kept_distance_km = cumulative_distance_km

    if target_points > 0 and len(profile) > target_points:
        step = (len(profile) - 1) / (target_points - 1)
        keep_indexes = {round(index * step) for index in range(target_points)}
        profile = [point for index, point in enumerate(profile) if index in keep_indexes]

    return profile


def classify_segment_grade(
    elevation_delta_m: float,
    length_km: float,
    grade_threshold_pct: float = SEGMENT_GRADE_THRESHOLD_PCT,
) -> str:
    """Classify a local route section using average gradient."""
    if length_km <= 0:
        return "flat_or_rolling"
    gradient = elevation_delta_m / (length_km * 1000) * 100
    if gradient >= grade_threshold_pct:
        return "climb"
    if gradient <= -grade_threshold_pct:
        return "descent"
    return "flat_or_rolling"


def segment_route(
    route_id: str,
    points: list[RoutePoint],
    min_segment_length_km: float = MIN_SEGMENT_LENGTH_KM,
) -> dict[str, Any]:
    """Split a route into coarse climb/descent/rolling segments."""
    if len(points) < 2:
        return {"route_id": route_id, "segments": []}

    distances = cumulative_distances_km(points)
    elevations = smooth_elevations(points)
    intervals: list[dict[str, Any]] = []
    for index in range(1, len(points)):
        previous_elevation = elevations[index - 1]
        current_elevation = elevations[index]
        length_km = distances[index] - distances[index - 1]
        elevation_delta = (
            0.0
            if previous_elevation is None or current_elevation is None
            else current_elevation - previous_elevation
        )
        intervals.append(
            {
                "start_index": index - 1,
                "end_index": index,
                "type": classify_segment_grade(elevation_delta, length_km),
            }
        )

    grouped: list[dict[str, int | str]] = []
    for interval in intervals:
        if grouped and grouped[-1]["type"] == interval["type"]:
            grouped[-1]["end_index"] = interval["end_index"]
        else:
            grouped.append(interval.copy())

    merged: list[dict[str, int | str]] = []
    for group in grouped:
        length_km = distances[int(group["end_index"])] - distances[int(group["start_index"])]
        if merged and length_km < min_segment_length_km:
            merged[-1]["end_index"] = group["end_index"]
        else:
            merged.append(group)

    segments: list[dict[str, Any]] = []
    for index, group in enumerate(merged, start=1):
        start_index = int(group["start_index"])
        end_index = int(group["end_index"])
        start_km = distances[start_index]
        end_km = distances[end_index]
        length_km = max(end_km - start_km, 0.0)
        start_ele = elevations[start_index]
        end_ele = elevations[end_index]
        elevation_delta = 0.0 if start_ele is None or end_ele is None else end_ele - start_ele
        avg_gradient = elevation_delta / (length_km * 1000) * 100 if length_km > 0 else 0.0
        segment_type = classify_segment_grade(elevation_delta, length_km)
        segments.append(
            {
                "segment_id": f"{route_id}_seg_{index:03d}",
                "start_km": round(start_km, 3),
                "end_km": round(end_km, 3),
                "length_km": round(length_km, 3),
                "elevation_delta_m": round(elevation_delta),
                "avg_gradient_pct": round(avg_gradient, 1),
                "type": segment_type,
            }
        )

    return {"route_id": route_id, "segments": segments}


def categorize_climb(length_km: float, gain_m: float) -> str:
    """Return a simple internal climb category."""
    if gain_m >= 700 or length_km >= 8:
        return "major"
    if gain_m >= 250 or length_km >= 3:
        return "medium"
    return "short"


def extract_climbs(
    route_id: str,
    points: list[RoutePoint],
    min_length_km: float = CLIMB_MIN_LENGTH_KM,
    min_gain_m: float = CLIMB_MIN_GAIN_M,
    min_avg_gradient_pct: float = CLIMB_MIN_AVG_GRADIENT_PCT,
) -> dict[str, Any]:
    """Extract notable uphill sections using transparent grade thresholds."""
    if len(points) < 2:
        return {"route_id": route_id, "climbs": []}

    distances = cumulative_distances_km(points)
    elevations = smooth_elevations(points)
    runs: list[dict[str, Any]] = []
    active: dict[str, Any] | None = None

    for index in range(1, len(points)):
        previous_elevation = elevations[index - 1]
        current_elevation = elevations[index]
        length_km = distances[index] - distances[index - 1]
        if previous_elevation is None or current_elevation is None or length_km <= 0:
            uphill = False
            gradient_pct = 0.0
            delta = 0.0
        else:
            delta = current_elevation - previous_elevation
            gradient_pct = delta / (length_km * 1000) * 100
            uphill = gradient_pct >= min_avg_gradient_pct or delta > 0

        if uphill:
            if active is None:
                active = {
                    "start_index": index - 1,
                    "end_index": index,
                    "gain_m": max(delta, 0.0),
                    "max_gradient_pct": gradient_pct,
                }
            else:
                active["end_index"] = index
                active["gain_m"] += max(delta, 0.0)
                active["max_gradient_pct"] = max(active["max_gradient_pct"], gradient_pct)
        elif active is not None:
            runs.append(active)
            active = None

    if active is not None:
        runs.append(active)

    climbs: list[dict[str, Any]] = []
    for run in runs:
        start_km = distances[run["start_index"]]
        end_km = distances[run["end_index"]]
        length_km = end_km - start_km
        gain_m = run["gain_m"]
        avg_gradient = gain_m / (length_km * 1000) * 100 if length_km > 0 else 0.0
        if (
            length_km < min_length_km
            or gain_m < min_gain_m
            or avg_gradient < min_avg_gradient_pct
        ):
            continue
        climbs.append(
            {
                "climb_id": f"{route_id}_climb_{len(climbs) + 1:03d}",
                "name": f"Climb {len(climbs) + 1}",
                "start_km": round(start_km, 3),
                "end_km": round(end_km, 3),
                "length_km": round(length_km, 3),
                "elevation_gain_m": round(gain_m),
                "avg_gradient_pct": round(avg_gradient, 1),
                "max_gradient_pct": round(run["max_gradient_pct"], 1),
                "category": categorize_climb(length_km, gain_m),
            }
        )

    return {"route_id": route_id, "climbs": climbs}


def climb_summary(climbs_payload: dict[str, Any]) -> dict[str, Any]:
    """Return route-index fields summarising detected climbs."""
    climbs = climbs_payload.get("climbs", [])
    main_climb = max(climbs, key=lambda climb: climb["elevation_gain_m"], default=None)
    return {
        "num_climbs": len(climbs),
        "main_climb_length_km": main_climb["length_km"] if main_climb else None,
        "main_climb_gain_m": main_climb["elevation_gain_m"] if main_climb else None,
        "main_climb_avg_gradient_pct": main_climb["avg_gradient_pct"] if main_climb else None,
    }


def build_feature(
    gpx_path: Path, include_profile: bool = True
) -> tuple[
    dict[str, Any],
    list[dict[str, float]] | None,
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
] | None:
    """Build one GeoJSON feature from a GPX file, or return None if skipped."""
    try:
        gpx = parse_gpx(gpx_path)
        raw_points = extract_points(gpx)
    except Exception as exc:
        print(f"Skipped {gpx_path.name}: could not parse GPX ({exc})")
        return None

    points = remove_consecutive_duplicates(raw_points)
    if len(points) < VALIDATION_MIN_POINTS:
        print(f"Skipped {gpx_path.name}: fewer than 2 valid points")
        return None

    display_points = simplify_points(points)
    metrics = compute_metrics(points, display_points, len(raw_points))
    validation = validate_route(points, metrics, len(raw_points))
    if validation["validation_status"] == "error":
        print(
            f"Skipped {gpx_path.name}: "
            f"{'; '.join(validation['validation_messages'])}"
        )
        return None

    route_id = slugify(gpx_path.stem)
    route_name = extract_route_name(gpx, gpx_path)
    profile_file = f"profiles/{route_id}.json"
    profile = build_profile_series(points) if include_profile else None
    has_profile = bool(profile)
    segments_payload = segment_route(route_id, points)
    climbs_payload = extract_climbs(route_id, points)
    preview_points = simplify_points(points, PREVIEW_SIMPLIFICATION_TOLERANCE)
    detail_points = simplify_points(points, DETAIL_SIMPLIFICATION_TOLERANCE)

    properties = {
        "route_id": route_id,
        "name": route_name,
        "name_normalized": normalize_search_text(route_name),
        **metrics,
        **validation,
        **compute_route_spatial_metadata(points),
        **climb_summary(climbs_payload),
        "route_group_id": route_id,
        "variant_label": "primary",
        "is_primary_variant": True,
        "duplicate_of": None,
        "similar_routes": [],
        "source_file": gpx_path.name,
        "source_basename": gpx_path.stem,
        "has_profile": has_profile,
        "profile_file": profile_file if has_profile else None,
        "segments_file": f"segments/{route_id}.json",
        "climbs_file": f"climbs/{route_id}.json",
        "preview_geometry_file": f"routes_preview/{route_id}.geojson",
        "detail_geometry_file": f"routes_detail/{route_id}.geojson",
    }

    return (
        feature_with_geometry(properties, display_points),
        profile,
        segments_payload,
        climbs_payload,
        feature_with_geometry(properties, preview_points),
        feature_with_geometry(properties, detail_points),
    )


def write_json(path: Path, data: Any) -> None:
    """Write deterministic, human-readable JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def source_manifest_entry(gpx_path: Path) -> dict[str, Any]:
    """Return the source facts used for lightweight change detection."""
    stat = gpx_path.stat()
    return {
        "source_file": gpx_path.name,
        "source_path": str(gpx_path),
        "modified_ns": stat.st_mtime_ns,
        "size_bytes": stat.st_size,
    }


def load_manifest(path: Path) -> dict[str, Any]:
    """Load the build manifest, returning an empty manifest when absent."""
    if not path.exists():
        return {"version": MANIFEST_VERSION, "routes": {}}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"Ignoring unreadable manifest at {path}")
        return {"version": MANIFEST_VERSION, "routes": {}}
    manifest.setdefault("version", 1)
    manifest.setdefault("routes", {})
    return manifest


def save_manifest(path: Path, manifest: dict[str, Any]) -> None:
    """Save manifest data in a deterministic shape."""
    write_json(path, manifest)


def route_needs_rebuild(
    gpx_path: Path, previous_manifest: dict[str, Any], full_rebuild: bool = False
) -> bool:
    """Return whether a GPX source differs from the cached manifest entry."""
    if full_rebuild:
        return True
    if previous_manifest.get("version") != MANIFEST_VERSION:
        return True
    route_id = slugify(gpx_path.stem)
    cached = previous_manifest.get("routes", {}).get(route_id)
    if not cached:
        return True
    return cached.get("source") != source_manifest_entry(gpx_path)


def matches_only_filter(gpx_path: Path, only: str | None) -> bool:
    """Return whether a GPX file matches --only by route id, stem, or filename."""
    if only is None:
        return True
    needle = only.lower()
    return needle in {
        slugify(gpx_path.stem).lower(),
        gpx_path.stem.lower(),
        gpx_path.name.lower(),
    }


def write_route_file(feature: dict[str, Any], per_route_dir: Path = PER_ROUTE_DIR) -> Path:
    """Write one lazy-loadable GeoJSON Feature per route."""
    route_id = feature["properties"]["route_id"]
    route_path = per_route_dir / f"{route_id}.geojson"
    write_json(route_path, feature)
    return route_path


def write_profile_file(
    route_id: str,
    profile: list[dict[str, float]] | None,
    profiles_dir: Path = PROFILES_DIR,
) -> Path | None:
    """Write one route profile JSON file when profile data exists."""
    if not profile:
        return None
    profile_path = profiles_dir / f"{route_id}.json"
    write_json(profile_path, profile)
    return profile_path


def write_segments_file(
    route_id: str, payload: dict[str, Any], segments_dir: Path = SEGMENTS_DIR
) -> Path:
    """Write one route segment JSON file."""
    path = segments_dir / f"{route_id}.json"
    write_json(path, payload)
    return path


def write_climbs_file(
    route_id: str, payload: dict[str, Any], climbs_dir: Path = CLIMBS_DIR
) -> Path:
    """Write one route climbs JSON file."""
    path = climbs_dir / f"{route_id}.json"
    write_json(path, payload)
    return path


def write_geometry_file(
    feature: dict[str, Any], output_dir: Path
) -> Path:
    """Write a per-route GeoJSON feature to the given geometry directory."""
    route_id = feature["properties"]["route_id"]
    path = output_dir / f"{route_id}.geojson"
    write_json(path, feature)
    return path


def route_similarity_score(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Score likely duplicate or variant routes using lightweight heuristics."""
    pa = a["properties"]
    pb = b["properties"]
    distance_a = pa.get("distance_km") or 0
    distance_b = pb.get("distance_km") or 0
    gain_a = pa.get("elevation_gain_m") or 0
    gain_b = pb.get("elevation_gain_m") or 0
    distance_ratio = abs(distance_a - distance_b) / max(distance_a, distance_b, 0.1)
    gain_ratio = abs(gain_a - gain_b) / max(gain_a, gain_b, 1)
    start_m = haversine_m(pa["start_lat"], pa["start_lon"], pb["start_lat"], pb["start_lon"])
    end_m = haversine_m(pa["end_lat"], pa["end_lon"], pb["end_lat"], pb["end_lon"])
    reverse_start_m = haversine_m(pa["start_lat"], pa["start_lon"], pb["end_lat"], pb["end_lon"])
    reverse_end_m = haversine_m(pa["end_lat"], pa["end_lon"], pb["start_lat"], pb["start_lon"])
    centroid_m = haversine_m(
        pa["centroid_lat"], pa["centroid_lon"], pb["centroid_lat"], pb["centroid_lon"]
    )
    name_tokens_a = set(normalize_search_text(pa["name"]).split())
    name_tokens_b = set(normalize_search_text(pb["name"]).split())
    name_score = (
        len(name_tokens_a & name_tokens_b) / len(name_tokens_a | name_tokens_b)
        if name_tokens_a and name_tokens_b
        else 0.0
    )
    same_direction_endpoints = (
        start_m <= DUPLICATE_ENDPOINT_THRESHOLD_M
        and end_m <= DUPLICATE_ENDPOINT_THRESHOLD_M
    )
    reversed_endpoints = (
        reverse_start_m <= DUPLICATE_ENDPOINT_THRESHOLD_M
        and reverse_end_m <= DUPLICATE_ENDPOINT_THRESHOLD_M
    )

    score = 0.0
    if distance_ratio <= DUPLICATE_DISTANCE_RATIO:
        score += 0.3
    if gain_ratio <= DUPLICATE_GAIN_RATIO or abs(gain_a - gain_b) <= 75:
        score += 0.2
    if same_direction_endpoints or reversed_endpoints:
        score += 0.3
    if centroid_m <= DUPLICATE_CENTROID_THRESHOLD_M:
        score += 0.1
    if name_score >= 0.5:
        score += 0.1
    return round(score, 3)


def apply_route_variant_metadata(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Annotate features with canonical group and duplicate metadata."""
    by_id = {feature["properties"]["route_id"]: feature for feature in features}
    similar: dict[str, list[dict[str, Any]]] = {route_id: [] for route_id in by_id}
    parent: dict[str, str] = {route_id: route_id for route_id in by_id}

    def find(route_id: str) -> str:
        while parent[route_id] != route_id:
            parent[route_id] = parent[parent[route_id]]
            route_id = parent[route_id]
        return route_id

    def union(a: str, b: str) -> None:
        root_a = find(a)
        root_b = find(b)
        if root_a != root_b:
            parent[max(root_a, root_b)] = min(root_a, root_b)

    for index, feature in enumerate(features):
        for other in features[index + 1 :]:
            route_id = feature["properties"]["route_id"]
            other_id = other["properties"]["route_id"]
            score = route_similarity_score(feature, other)
            if score >= 0.7:
                similar[route_id].append({"route_id": other_id, "score": score})
                similar[other_id].append({"route_id": route_id, "score": score})
                union(route_id, other_id)

    groups: dict[str, list[str]] = {}
    for route_id in sorted(by_id):
        groups.setdefault(find(route_id), []).append(route_id)

    for route_ids in groups.values():
        route_ids.sort(
            key=lambda route_id: (
                by_id[route_id]["properties"].get("validation_status") != "ok",
                -(by_id[route_id]["properties"].get("quality_score") or 0),
                route_id,
            )
        )
        primary = route_ids[0]
        for variant_index, route_id in enumerate(route_ids, start=1):
            props = by_id[route_id]["properties"]
            props["route_group_id"] = primary
            props["is_primary_variant"] = route_id == primary
            props["variant_label"] = "primary" if route_id == primary else f"variant {variant_index}"
            props["duplicate_of"] = None if route_id == primary else primary
            props["similar_routes"] = sorted(
                similar[route_id], key=lambda item: (-item["score"], item["route_id"])
            )

    return features


def build_frontend_artifacts(features: list[dict[str, Any]]) -> dict[str, Any]:
    """Build frontend-oriented list, map, and lookup payloads."""
    route_index = [feature["properties"] for feature in features]
    routes_list = [
        {
            "route_id": props["route_id"],
            "name": props["name"],
            "difficulty": props["difficulty"],
            "terrain_type": props["terrain_type"],
            "distance_km": props["distance_km"],
            "elevation_gain_m": props["elevation_gain_m"],
            "num_climbs": props.get("num_climbs", 0),
            "main_climb_gain_m": props.get("main_climb_gain_m"),
            "validation_status": props["validation_status"],
            "validation_messages": props["validation_messages"],
            "quality_score": props["quality_score"],
            "is_primary_variant": props.get("is_primary_variant", True),
            "route_group_id": props.get("route_group_id", props["route_id"]),
            "profile_file": props.get("profile_file"),
            "preview_geometry_file": props.get("preview_geometry_file"),
        }
        for props in route_index
    ]
    routes_map_index = [
        {
            "route_id": props["route_id"],
            "name": props["name"],
            "bbox": props["bbox"],
            "centroid": {
                "lat": round(props["centroid_lat"], 6),
                "lon": round(props["centroid_lon"], 6),
            },
            "preview_geometry_file": props.get("preview_geometry_file"),
            "is_primary_variant": props.get("is_primary_variant", True),
            "route_group_id": props.get("route_group_id", props["route_id"]),
            "validation_status": props["validation_status"],
        }
        for props in route_index
    ]
    route_lookup = {
        props["route_id"]: {
            "geometry_file": f"routes/{props['route_id']}.geojson",
            "profile_file": props.get("profile_file"),
            "segments_file": props.get("segments_file"),
            "climbs_file": props.get("climbs_file"),
            "preview_geometry_file": props.get("preview_geometry_file"),
            "detail_geometry_file": props.get("detail_geometry_file"),
        }
        for props in route_index
    }
    return {
        "routes_list": routes_list,
        "routes_map_index": routes_map_index,
        "route_lookup": route_lookup,
    }


def write_frontend_artifacts(features: list[dict[str, Any]], frontend_dir: Path) -> None:
    """Write frontend-specific derivative JSON files."""
    artifacts = build_frontend_artifacts(features)
    write_json(frontend_dir / "routes_list.json", artifacts["routes_list"])
    write_json(frontend_dir / "routes_map_index.json", artifacts["routes_map_index"])
    write_json(frontend_dir / "route_lookup.json", artifacts["route_lookup"])


def build_report_payload(
    features: list[dict[str, Any]],
    total_source_files: int,
    processed_count: int,
    skipped_count: int,
    build_mode: str,
    skipped_files: list[str],
) -> dict[str, Any]:
    """Build a structured preprocessing report."""
    route_summaries = [feature["properties"] for feature in features]
    warnings = [
        {"route_id": props["route_id"], "messages": props["validation_messages"]}
        for props in route_summaries
        if props["validation_status"] in {"review", "warning"}
    ]
    errors = [
        {"route_id": props["route_id"], "messages": props["validation_messages"]}
        for props in route_summaries
        if props["validation_status"] == "error"
    ]
    duplicate_candidates = [
        {
            "route_id": props["route_id"],
            "duplicate_of": props.get("duplicate_of"),
            "similar_routes": props.get("similar_routes", []),
        }
        for props in route_summaries
        if props.get("duplicate_of") or props.get("similar_routes")
    ]
    suspicious = [
        props["route_id"]
        for props in route_summaries
        if props["validation_status"] in {"review", "warning", "error"}
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "build_mode": build_mode,
        "total_source_gpx_files_seen": total_source_files,
        "routes_processed": processed_count,
        "routes_skipped": skipped_count,
        "warnings_count": len(warnings),
        "errors_count": len(errors),
        "duplicates_detected": sum(1 for props in route_summaries if props.get("duplicate_of")),
        "routes_missing_elevation": [
            props["route_id"] for props in route_summaries if not props.get("has_elevation")
        ],
        "routes_with_suspicious_stats": suspicious,
        "skipped_files": skipped_files,
        "warnings": warnings,
        "errors": errors,
        "duplicate_candidates": duplicate_candidates,
        "routes": [
            {
                "route_id": props["route_id"],
                "name": props["name"],
                "distance_km": props["distance_km"],
                "elevation_gain_m": props["elevation_gain_m"],
                "difficulty": props["difficulty"],
                "validation_status": props["validation_status"],
                "num_climbs": props.get("num_climbs", 0),
                "duplicate_of": props.get("duplicate_of"),
            }
            for props in route_summaries
        ],
    }


def build_report_markdown(report: dict[str, Any]) -> str:
    """Build a concise Markdown report for manual inspection."""
    routes = report["routes"]
    longest = sorted(routes, key=lambda route: route["distance_km"], reverse=True)[:5]
    hardest = sorted(routes, key=lambda route: route["elevation_gain_m"], reverse=True)[:5]
    lines = [
        "# GPX Preprocessing Report",
        "",
        "## Build summary",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Build mode: {report['build_mode']}",
        f"- Source GPX files seen: {report['total_source_gpx_files_seen']}",
        f"- Routes processed: {report['routes_processed']}",
        f"- Routes skipped: {report['routes_skipped']}",
        f"- Warnings: {report['warnings_count']}",
        f"- Errors: {report['errors_count']}",
        f"- Duplicates detected: {report['duplicates_detected']}",
        "",
        "## Duplicate candidates",
        "",
    ]
    duplicates = report["duplicate_candidates"]
    lines.extend(
        [
            f"- {item['route_id']} -> {item.get('duplicate_of') or 'similar'}"
            for item in duplicates
        ]
        or ["- None"]
    )
    lines.extend(["", "## Validation issues", ""])
    issues = report["warnings"] + report["errors"]
    lines.extend(
        [
            f"- {item['route_id']}: {'; '.join(item['messages'])}"
            for item in issues
        ]
        or ["- None"]
    )
    lines.extend(["", "## Top longest routes", ""])
    lines.extend(
        [
            f"- {route['name']}: {route['distance_km']} km"
            for route in longest
        ]
        or ["- None"]
    )
    lines.extend(["", "## Top hardest routes", ""])
    lines.extend(
        [
            f"- {route['name']}: {route['elevation_gain_m']} m gain"
            for route in hardest
        ]
        or ["- None"]
    )
    lines.extend(["", "## Routes with missing elevation", ""])
    lines.extend([f"- {route_id}" for route_id in report["routes_missing_elevation"]] or ["- None"])
    lines.extend(["", "## Skipped files", ""])
    lines.extend([f"- {filename}" for filename in report["skipped_files"]] or ["- None"])
    return "\n".join(lines) + "\n"


def write_build_report(json_path: Path, markdown_path: Path, report: dict[str, Any]) -> None:
    """Write JSON and Markdown build reports."""
    write_json(json_path, report)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(build_report_markdown(report), encoding="utf-8")


def remove_stale_outputs(
    route_id: str,
    per_route_dir: Path,
    profiles_dir: Path,
    segments_dir: Path,
    climbs_dir: Path,
    routes_preview_dir: Path,
    routes_detail_dir: Path,
) -> None:
    """Remove derived files for a source that no longer exists."""
    paths = [
        per_route_dir / f"{route_id}.geojson",
        profiles_dir / f"{route_id}.json",
        segments_dir / f"{route_id}.json",
        climbs_dir / f"{route_id}.json",
        routes_preview_dir / f"{route_id}.geojson",
        routes_detail_dir / f"{route_id}.geojson",
    ]
    for path in paths:
        if path.exists():
            path.unlink()
            print(f"Removed stale derived file {path}")


def default_config() -> PreprocessConfig:
    """Return default paths and switches for the CLI and tests."""
    return {
        "raw_dir": RAW_GPX_DIR,
        "processed_dir": PROCESSED_DIR,
        "routes_geojson_path": ROUTES_GEOJSON_PATH,
        "routes_index_path": ROUTES_INDEX_PATH,
        "per_route_dir": PER_ROUTE_DIR,
        "profiles_dir": PROFILES_DIR,
        "segments_dir": SEGMENTS_DIR,
        "climbs_dir": CLIMBS_DIR,
        "routes_preview_dir": ROUTES_PREVIEW_DIR,
        "routes_detail_dir": ROUTES_DETAIL_DIR,
        "frontend_dir": FRONTEND_DIR,
        "build_manifest_path": BUILD_MANIFEST_PATH,
        "build_report_json_path": BUILD_REPORT_JSON_PATH,
        "build_report_md_path": BUILD_REPORT_MD_PATH,
        "full_rebuild": False,
        "only": None,
        "only_group": None,
        "skip_profiles": False,
        "emit_frontend_artifacts": True,
        "emit_segments": True,
        "emit_climbs": True,
        "geometry_mode": "all",
        "validate_only": False,
        "build_report": True,
        "verbose": False,
    }


def config_from_args(args: argparse.Namespace) -> PreprocessConfig:
    """Create concrete output paths from parsed CLI arguments."""
    processed_dir = Path(args.processed_dir)
    return {
        "raw_dir": Path(args.raw_dir),
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
        "full_rebuild": args.full_rebuild,
        "only": args.only,
        "only_group": args.only_group,
        "skip_profiles": args.skip_profiles,
        "emit_frontend_artifacts": args.emit_frontend_artifacts,
        "emit_segments": args.emit_segments,
        "emit_climbs": args.emit_climbs,
        "geometry_mode": args.geometry_mode,
        "validate_only": args.validate_only,
        "build_report": args.build_report,
        "verbose": args.verbose,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the small preprocessing CLI."""
    parser = argparse.ArgumentParser(
        description="Convert raw GPX cycling routes into app-ready JSON outputs."
    )
    parser.add_argument("--full-rebuild", action="store_true", help="ignore manifest cache")
    parser.add_argument("--only", help="process one route id, filename stem, or filename")
    parser.add_argument("--only-group", help="write outputs for one route_group_id")
    parser.add_argument("--skip-profiles", action="store_true", help="do not write profiles")
    parser.add_argument(
        "--emit-frontend-artifacts",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="write frontend list/map/lookup artifacts",
    )
    parser.add_argument(
        "--emit-segments",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="write per-route segment JSON files",
    )
    parser.add_argument(
        "--emit-climbs",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="write per-route climb JSON files",
    )
    parser.add_argument(
        "--geometry-mode",
        choices=["preview", "detail", "all"],
        default="all",
        help="which multi-resolution geometry files to write",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="build and report validation metadata without writing route artifacts",
    )
    parser.add_argument(
        "--build-report",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="write JSON and Markdown build reports",
    )
    parser.add_argument("--raw-dir", default=str(RAW_GPX_DIR), help="input GPX directory")
    parser.add_argument(
        "--processed-dir", default=str(PROCESSED_DIR), help="processed output directory"
    )
    parser.add_argument("--verbose", action="store_true", help="print cache details")
    return parser.parse_args(argv)


def run_pipeline(config: PreprocessConfig) -> None:
    """Run preprocessing with optional manifest-based incremental rebuilds."""
    raw_dir = config["raw_dir"]
    processed_dir = config["processed_dir"]
    per_route_dir = config["per_route_dir"]
    profiles_dir = config["profiles_dir"]
    segments_dir = config["segments_dir"]
    climbs_dir = config["climbs_dir"]
    routes_preview_dir = config["routes_preview_dir"]
    routes_detail_dir = config["routes_detail_dir"]
    frontend_dir = config["frontend_dir"]
    manifest_path = config["build_manifest_path"]
    include_profiles = not config["skip_profiles"]

    all_gpx_files = sorted(raw_dir.glob("*.gpx"))
    gpx_files = all_gpx_files
    gpx_files = [path for path in gpx_files if matches_only_filter(path, config["only"])]
    selected_route_ids = {slugify(path.stem) for path in gpx_files}
    if not gpx_files:
        raise SystemExit(f"No GPX files found in {raw_dir}")

    processed_dir.mkdir(parents=True, exist_ok=True)
    if not config["validate_only"]:
        per_route_dir.mkdir(parents=True, exist_ok=True)
        if include_profiles:
            profiles_dir.mkdir(parents=True, exist_ok=True)
        if config["emit_segments"]:
            segments_dir.mkdir(parents=True, exist_ok=True)
        if config["emit_climbs"]:
            climbs_dir.mkdir(parents=True, exist_ok=True)
        if config["geometry_mode"] in {"preview", "all"}:
            routes_preview_dir.mkdir(parents=True, exist_ok=True)
        if config["geometry_mode"] in {"detail", "all"}:
            routes_detail_dir.mkdir(parents=True, exist_ok=True)
        if config["emit_frontend_artifacts"]:
            frontend_dir.mkdir(parents=True, exist_ok=True)

    previous_manifest = load_manifest(manifest_path)
    previous_routes = previous_manifest.get("routes", {})
    current_route_ids = {slugify(path.stem) for path in all_gpx_files}
    next_manifest: dict[str, Any] = {"version": MANIFEST_VERSION, "routes": {}}
    processed_count = 0
    skipped_count = 0
    skipped_files: list[str] = []

    if config["only"] is None and not config["validate_only"]:
        for route_id in sorted(set(previous_routes) - current_route_ids):
            remove_stale_outputs(
                route_id,
                per_route_dir,
                profiles_dir,
                segments_dir,
                climbs_dir,
                routes_preview_dir,
                routes_detail_dir,
            )

    features: list[dict[str, Any]] = []
    segments_by_route: dict[str, dict[str, Any]] = {}
    climbs_by_route: dict[str, dict[str, Any]] = {}
    preview_by_route: dict[str, dict[str, Any]] = {}
    detail_by_route: dict[str, dict[str, Any]] = {}
    profiles_by_route: dict[str, list[dict[str, float]] | None] = {}
    for gpx_path in gpx_files:
        route_id = slugify(gpx_path.stem)
        cached = previous_routes.get(route_id)
        needs_rebuild = route_needs_rebuild(
            gpx_path, previous_manifest, config["full_rebuild"]
        )
        if cached and cached.get("include_profiles") != include_profiles:
            needs_rebuild = True

        if not needs_rebuild and cached and cached.get("feature"):
            feature = cached["feature"]
            features.append(feature)
            segments_by_route[route_id] = cached.get("segments", {"route_id": route_id, "segments": []})
            climbs_by_route[route_id] = cached.get("climbs", {"route_id": route_id, "climbs": []})
            preview_by_route[route_id] = cached.get("preview_feature", feature)
            detail_by_route[route_id] = cached.get("detail_feature", feature)
            profiles_by_route[route_id] = None
            next_manifest["routes"][route_id] = cached
            skipped_count += 1
            skipped_files.append(gpx_path.name)
            if config["verbose"]:
                print(f"Skipped unchanged route {gpx_path.name}")
            continue

        if cached:
            print(f"Rebuilt changed route {gpx_path.name}")
        elif config["verbose"]:
            print(f"Processing new route {gpx_path.name}")

        result = build_feature(gpx_path, include_profile=include_profiles)
        if result is None:
            continue

        feature, profile, segments_payload, climbs_payload, preview_feature, detail_feature = result
        route_id = feature["properties"]["route_id"]
        features.append(feature)
        segments_by_route[route_id] = segments_payload
        climbs_by_route[route_id] = climbs_payload
        preview_by_route[route_id] = preview_feature
        detail_by_route[route_id] = detail_feature
        profiles_by_route[route_id] = profile
        processed_count += 1
        next_manifest["routes"][route_id] = {
            "source": source_manifest_entry(gpx_path),
            "feature": feature,
            "segments": segments_payload,
            "climbs": climbs_payload,
            "preview_feature": preview_feature,
            "detail_feature": detail_feature,
            "include_profiles": include_profiles,
        }

        properties = feature["properties"]
        print(
            f"Processed {gpx_path.name}: "
            f"{properties['distance_km']} km, "
            f"{properties['difficulty']}, "
            f"{properties['num_points_original']} -> "
            f"{properties['num_points_display']} display points"
        )
        if properties["validation_status"] in {"review", "warning"}:
            print(
                f"Warnings for {gpx_path.name}: "
                f"{'; '.join(properties['validation_messages'])}"
            )

    for route_id, cached in previous_routes.items():
        source_file = cached.get("source", {}).get("source_file")
        if (
            route_id in next_manifest["routes"]
            or route_id in selected_route_ids
            or route_id not in current_route_ids
        ):
            continue
        if source_file and (raw_dir / source_file).exists():
            next_manifest["routes"][route_id] = cached
            if cached.get("feature"):
                features.append(cached["feature"])
                segments_by_route[route_id] = cached.get("segments", {"route_id": route_id, "segments": []})
                climbs_by_route[route_id] = cached.get("climbs", {"route_id": route_id, "climbs": []})
                preview_by_route[route_id] = cached.get("preview_feature", cached["feature"])
                detail_by_route[route_id] = cached.get("detail_feature", cached["feature"])
                profiles_by_route[route_id] = None

    if not features:
        raise SystemExit("No valid GPX routes were processed.")

    features = sorted(features, key=lambda feature: feature["properties"]["route_id"])
    apply_route_variant_metadata(features)
    if config["only_group"] is not None:
        features = [
            feature
            for feature in features
            if feature["properties"].get("route_group_id") == config["only_group"]
        ]
        if not features:
            raise SystemExit(f"No routes found for group {config['only_group']}")

    feature_collection = {
        "type": "FeatureCollection",
        "features": features,
    }
    route_index = [feature["properties"] for feature in features]

    for feature in features:
        route_id = feature["properties"]["route_id"]
        if route_id in next_manifest["routes"]:
            next_manifest["routes"][route_id]["feature"] = feature
        if route_id in preview_by_route:
            preview_by_route[route_id]["properties"] = feature["properties"]
            next_manifest["routes"].setdefault(route_id, {})["preview_feature"] = preview_by_route[route_id]
        if route_id in detail_by_route:
            detail_by_route[route_id]["properties"] = feature["properties"]
            next_manifest["routes"].setdefault(route_id, {})["detail_feature"] = detail_by_route[route_id]

    build_mode = "full" if config["full_rebuild"] else "incremental"
    report = build_report_payload(
        features,
        total_source_files=len(all_gpx_files),
        processed_count=processed_count,
        skipped_count=skipped_count,
        build_mode=build_mode,
        skipped_files=skipped_files,
    )

    if config["validate_only"]:
        if config["build_report"]:
            write_build_report(
                config["build_report_json_path"],
                config["build_report_md_path"],
                report,
            )
            print(f"Wrote {config['build_report_json_path']}")
            print(f"Wrote {config['build_report_md_path']}")
        print("Validate-only run complete; route artifacts were not written.")
        return

    write_json(config["routes_geojson_path"], feature_collection)
    write_json(config["routes_index_path"], route_index)
    for feature in features:
        route_id = feature["properties"]["route_id"]
        write_route_file(feature, per_route_dir)
        write_profile_file(route_id, profiles_by_route.get(route_id), profiles_dir)
        if config["emit_segments"]:
            write_segments_file(route_id, segments_by_route[route_id], segments_dir)
        if config["emit_climbs"]:
            write_climbs_file(route_id, climbs_by_route[route_id], climbs_dir)
        if config["geometry_mode"] in {"preview", "all"}:
            write_geometry_file(preview_by_route[route_id], routes_preview_dir)
        if config["geometry_mode"] in {"detail", "all"}:
            write_geometry_file(detail_by_route[route_id], routes_detail_dir)
    if config["emit_frontend_artifacts"]:
        write_frontend_artifacts(features, frontend_dir)
    if config["build_report"]:
        write_build_report(
            config["build_report_json_path"],
            config["build_report_md_path"],
            report,
        )
    save_manifest(manifest_path, next_manifest)

    print(f"Wrote {config['routes_geojson_path']}")
    print(f"Wrote {config['routes_index_path']}")
    print(f"Wrote {len(features)} per-route GeoJSON file(s) to {per_route_dir}")
    if include_profiles:
        profile_count = sum(1 for feature in features if feature["properties"]["has_profile"])
        print(f"Wrote {profile_count} profile JSON file(s) to {profiles_dir}")
    if config["emit_segments"]:
        print(f"Wrote {len(features)} segment JSON file(s) to {segments_dir}")
    if config["emit_climbs"]:
        climb_count = sum(len(climbs_by_route[feature["properties"]["route_id"]]["climbs"]) for feature in features)
        print(f"Wrote {len(features)} climb JSON file(s) with {climb_count} climb(s) to {climbs_dir}")
    duplicate_count = report["duplicates_detected"]
    print(f"Found {duplicate_count} duplicate candidate(s)")
    if config["emit_frontend_artifacts"]:
        print(f"Wrote frontend artifacts to {frontend_dir}")
    if config["build_report"]:
        print(f"Wrote {config['build_report_json_path']}")
        print(f"Wrote {config['build_report_md_path']}")
    print(f"Wrote {manifest_path}")


def main(argv: list[str] | None = None) -> None:
    run_pipeline(config_from_args(parse_args(argv)))


if __name__ == "__main__":
    main()
