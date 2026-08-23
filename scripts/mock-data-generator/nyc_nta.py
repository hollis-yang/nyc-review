#!/usr/bin/env python3
"""Fetch, validate and query the pinned NYC 2020 NTA GeoJSON snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

DEFAULT_MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "sources"
    / "nyc-nta-2020-26b.manifest.json"
)
MAX_DOWNLOAD_BYTES = 32 * 1024 * 1024
REQUIRED_PROPERTIES = {"nta2020", "ntaname", "boroname", "ntatype", "cdta2020"}


@dataclass(frozen=True)
class NtaAssignment:
    code: str | None
    name: str | None
    method: str


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, dict):
        raise TypeError(f"NTA manifest must be an object: {path}")
    for key in ("downloadUrl", "sha256", "contentLength", "featureCount", "datasetVersion"):
        if not manifest.get(key):
            raise ValueError(f"NTA manifest is missing {key}: {path}")
    return manifest


def validate_snapshot_bytes(payload: bytes, manifest: dict[str, Any]) -> dict[str, Any]:
    expected_size = int(manifest["contentLength"])
    if len(payload) != expected_size:
        raise ValueError(
            f"NTA snapshot size mismatch: expected {expected_size}, received {len(payload)}"
        )
    actual_sha256 = sha256_bytes(payload)
    if actual_sha256 != manifest["sha256"]:
        raise ValueError(
            "NTA snapshot SHA-256 mismatch; the upstream dataset changed. "
            "Review and pin a new manifest instead of silently accepting it."
        )
    document = json.loads(payload)
    if not isinstance(document, dict) or document.get("type") != "FeatureCollection":
        raise ValueError("NTA snapshot must be a GeoJSON FeatureCollection")
    features = document.get("features")
    if not isinstance(features, list) or len(features) != int(manifest["featureCount"]):
        raise ValueError("NTA snapshot feature count does not match the pinned manifest")
    codes: list[str] = []
    for feature in features:
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        if not REQUIRED_PROPERTIES.issubset(properties):
            raise ValueError("NTA feature is missing a required official property")
        if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            raise ValueError(f"Unsupported NTA geometry: {geometry.get('type')}")
        codes.append(str(properties["nta2020"]))
    if len(codes) != len(set(codes)):
        raise ValueError("NTA snapshot contains duplicate nta2020 codes")
    return document


def load_snapshot(
    path: Path,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = read_manifest(manifest_path)
    payload = path.read_bytes()
    return validate_snapshot_bytes(payload, manifest), manifest


def fetch_snapshot(
    output: Path,
    manifest_path: Path = DEFAULT_MANIFEST,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    manifest = read_manifest(manifest_path)
    request = urllib.request.Request(
        str(manifest["downloadUrl"]),
        headers={"User-Agent": "hm-dianping-nyc-data/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        payload = response.read(MAX_DOWNLOAD_BYTES + 1)
    if len(payload) > MAX_DOWNLOAD_BYTES:
        raise ValueError("NTA snapshot exceeds the safety download limit")
    document = validate_snapshot_bytes(payload, manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=output.parent, delete=False) as handle:
        handle.write(payload)
        temporary_path = Path(handle.name)
    os.replace(temporary_path, output)
    return {
        "datasetId": manifest["datasetId"],
        "datasetVersion": manifest["datasetVersion"],
        "features": len(document["features"]),
        "output": str(output),
        "sha256": manifest["sha256"],
        "status": "ok",
    }


def iter_features(document: dict[str, Any]) -> Iterable[dict[str, Any]]:
    return sorted(
        document["features"],
        key=lambda feature: str(feature["properties"]["nta2020"]),
    )


def geometry_bounds(geometry: dict[str, Any]) -> tuple[float, float, float, float]:
    points = list(_iter_points(geometry))
    if not points:
        raise ValueError("NTA geometry contains no coordinates")
    longitudes = [point[0] for point in points]
    latitudes = [point[1] for point in points]
    return min(longitudes), min(latitudes), max(longitudes), max(latitudes)


def geometry_centroid(geometry: dict[str, Any]) -> tuple[float, float]:
    weighted_x = 0.0
    weighted_y = 0.0
    total_weight = 0.0
    polygons = (
        [geometry["coordinates"]]
        if geometry["type"] == "Polygon"
        else geometry["coordinates"]
    )
    for polygon in polygons:
        if not polygon:
            continue
        area, centroid_x, centroid_y = _ring_area_centroid(polygon[0])
        weight = abs(area)
        if weight:
            weighted_x += centroid_x * weight
            weighted_y += centroid_y * weight
            total_weight += weight
    if total_weight:
        return weighted_x / total_weight, weighted_y / total_weight
    min_x, min_y, max_x, max_y = geometry_bounds(geometry)
    return (min_x + max_x) / 2, (min_y + max_y) / 2


def contains_point(geometry: dict[str, Any], longitude: float, latitude: float) -> bool:
    polygons = (
        [geometry["coordinates"]]
        if geometry["type"] == "Polygon"
        else geometry["coordinates"]
    )
    for polygon in polygons:
        if not polygon or not _ring_contains(polygon[0], longitude, latitude):
            continue
        if not any(_ring_contains(hole, longitude, latitude) for hole in polygon[1:]):
            return True
    return False


def normalized_neighborhoods(
    document: dict[str, Any],
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for feature in iter_features(document):
        properties = feature["properties"]
        geometry = feature["geometry"]
        min_x, min_y, max_x, max_y = geometry_bounds(geometry)
        centroid_x, centroid_y = geometry_centroid(geometry)
        result.append(
            {
                "code": str(properties["nta2020"]),
                "name": str(properties["ntaname"]),
                "borough": str(properties["boroname"]),
                "ntaType": str(properties["ntatype"]),
                "cdtaCode": str(properties["cdta2020"]),
                "centroidX": round(centroid_x, 7),
                "centroidY": round(centroid_y, 7),
                "minX": round(min_x, 7),
                "minY": round(min_y, 7),
                "maxX": round(max_x, 7),
                "maxY": round(max_y, 7),
                "geometry": geometry,
                "sourceDatasetId": manifest["datasetId"],
                "sourceVersion": manifest["datasetVersion"],
                "sourceUrl": manifest["sourcePageUrl"],
                "sourceRevisionDate": manifest["revisionDate"],
                "sourceSha256": manifest["sha256"],
            }
        )
    return result


def assign_point(
    neighborhoods: list[dict[str, Any]],
    longitude: float,
    latitude: float,
    borough: str | None = None,
) -> NtaAssignment:
    candidates: list[dict[str, Any]] = []
    for neighborhood in neighborhoods:
        if borough and neighborhood["borough"] != borough:
            continue
        if not (
            neighborhood["minX"] <= longitude <= neighborhood["maxX"]
            and neighborhood["minY"] <= latitude <= neighborhood["maxY"]
        ):
            continue
        if contains_point(neighborhood["geometry"], longitude, latitude):
            candidates.append(neighborhood)
    if not candidates:
        return NtaAssignment(None, None, "UNASSIGNED")
    # Boundary points can match twice. Prefer a residential NTA, then the smallest shape.
    selected = min(
        candidates,
        key=lambda item: (
            item["ntaType"] != "0",
            (item["maxX"] - item["minX"]) * (item["maxY"] - item["minY"]),
            item["code"],
        ),
    )
    return NtaAssignment(selected["code"], selected["name"], "POINT_IN_POLYGON")


def _iter_points(geometry: dict[str, Any]) -> Iterable[tuple[float, float]]:
    def walk(value: Any) -> Iterable[tuple[float, float]]:
        if (
            isinstance(value, list)
            and len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
        ):
            yield float(value[0]), float(value[1])
            return
        if isinstance(value, list):
            for child in value:
                yield from walk(child)

    yield from walk(geometry["coordinates"])


def _ring_contains(ring: list[list[float]], x: float, y: float) -> bool:
    inside = False
    for index, current in enumerate(ring):
        previous = ring[index - 1]
        x1, y1 = float(previous[0]), float(previous[1])
        x2, y2 = float(current[0]), float(current[1])
        if _point_on_segment(x, y, x1, y1, x2, y2):
            return True
        if (y1 > y) != (y2 > y):
            intersection_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < intersection_x:
                inside = not inside
    return inside


def _point_on_segment(
    x: float,
    y: float,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> bool:
    epsilon = 1e-10
    cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
    if abs(cross) > epsilon:
        return False
    return (
        min(x1, x2) - epsilon <= x <= max(x1, x2) + epsilon
        and min(y1, y2) - epsilon <= y <= max(y1, y2) + epsilon
    )


def _ring_area_centroid(ring: list[list[float]]) -> tuple[float, float, float]:
    twice_area = 0.0
    centroid_x_sum = 0.0
    centroid_y_sum = 0.0
    for index, current in enumerate(ring):
        previous = ring[index - 1]
        x1, y1 = float(previous[0]), float(previous[1])
        x2, y2 = float(current[0]), float(current[1])
        cross = x1 * y2 - x2 * y1
        twice_area += cross
        centroid_x_sum += (x1 + x2) * cross
        centroid_y_sum += (y1 + y2) * cross
    if abs(twice_area) < 1e-16:
        points = [(float(point[0]), float(point[1])) for point in ring]
        return 0.0, sum(point[0] for point in points) / len(points), sum(
            point[1] for point in points
        ) / len(points)
    return (
        twice_area / 2,
        centroid_x_sum / (3 * twice_area),
        centroid_y_sum / (3 * twice_area),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    subparsers = parser.add_subparsers(dest="command", required=True)
    fetch_parser = subparsers.add_parser("fetch", help="Download the pinned official snapshot")
    fetch_parser.add_argument("--output", type=Path, required=True)
    fetch_parser.add_argument("--timeout", type=int, default=60)
    validate_parser = subparsers.add_parser("validate", help="Validate an existing snapshot")
    validate_parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "fetch":
        report = fetch_snapshot(args.output.resolve(), args.manifest.resolve(), args.timeout)
    else:
        document, manifest = load_snapshot(args.input.resolve(), args.manifest.resolve())
        report = {
            "datasetId": manifest["datasetId"],
            "datasetVersion": manifest["datasetVersion"],
            "features": len(document["features"]),
            "sha256": manifest["sha256"],
            "status": "ok",
        }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
