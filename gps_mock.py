#!/usr/bin/env python3
"""Generate and inspect GPX files for Xcode location simulation.

This utility only creates GPX files. For USB device simulation use
iphone_control.py or gps_mock_app.py.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import os
import plistlib
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


GPX_NS = "http://www.topografix.com/GPX/1/1"
ET.register_namespace("", GPX_NS)


@dataclass(frozen=True)
class Point:
    lat: float
    lon: float
    elevation: float | None = None
    name: str | None = None


def fail(message: str) -> None:
    raise ValueError(message)


def parse_float(value: str, label: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be a number: {value!r}") from exc


def point_from_values(lat: str, lon: str, elevation: str | None = None, name: str | None = None) -> Point:
    point = Point(parse_float(lat, "latitude"), parse_float(lon, "longitude"),
                  parse_float(elevation, "elevation") if elevation is not None else None, name)
    if not -90 <= point.lat <= 90:
        fail(f"latitude must be between -90 and 90: {point.lat}")
    if not -180 <= point.lon <= 180:
        fail(f"longitude must be between -180 and 180: {point.lon}")
    if point.elevation is not None and point.elevation < -11000:
        fail(f"elevation is below the supported range: {point.elevation}")
    return point


def parse_point_arg(value: str) -> Point:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) not in (2, 3):
        fail("point must be LAT,LON or LAT,LON,ELEVATION")
    return point_from_values(parts[0], parts[1], parts[2] if len(parts) == 3 else None)


def load_points(path: Path) -> list[Point]:
    if not path.exists():
        fail(f"input file does not exist: {path}")
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            fail(f"invalid JSON: {exc}")
        if isinstance(data, dict):
            data = data.get("points")
        if not isinstance(data, list):
            fail("JSON input must be an array or an object with a 'points' array")
        points = []
        for item in data:
            if isinstance(item, dict):
                points.append(point_from_values(str(item["lat"]), str(item["lon"]),
                                               str(item["elevation"]) if item.get("elevation") is not None else None,
                                               str(item["name"]) if item.get("name") is not None else None))
            elif isinstance(item, (list, tuple)) and len(item) in (2, 3):
                points.append(parse_point_arg(",".join(map(str, item))))
            else:
                fail("each JSON point must be an object or [lat, lon, elevation]")
        return points
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    except OSError as exc:
        fail(str(exc))
    if not rows or not {"lat", "lon"}.issubset(rows[0]):
        fail("CSV input must have lat and lon columns, with optional elevation and name")
    return [point_from_values(row["lat"], row["lon"], row.get("elevation") or None, row.get("name") or None)
            for row in rows]


def add_text(parent: ET.Element, tag: str, value: str) -> ET.Element:
    child = ET.SubElement(parent, f"{{{GPX_NS}}}{tag}")
    child.text = value
    return child


def create_gpx(points: list[Point], name: str) -> ET.ElementTree:
    if not points:
        fail("at least one point is required")
    root = ET.Element(f"{{{GPX_NS}}}gpx", {"version": "1.1", "creator": "gps-mock", "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
                                           "xsi:schemaLocation": f"{GPX_NS} http://www.topografix.com/GPX/1/1/gpx.xsd"})
    metadata = ET.SubElement(root, f"{{{GPX_NS}}}metadata")
    add_text(metadata, "name", name)
    if len(points) == 1:
        point = points[0]
        attrs = {"lat": f"{point.lat:.8f}", "lon": f"{point.lon:.8f}"}
        wpt = ET.SubElement(root, f"{{{GPX_NS}}}wpt", attrs)
        if point.elevation is not None:
            add_text(wpt, "ele", f"{point.elevation:.2f}")
        add_text(wpt, "name", point.name or name)
    else:
        route = ET.SubElement(root, f"{{{GPX_NS}}}rte")
        add_text(route, "name", name)
        track = ET.SubElement(root, f"{{{GPX_NS}}}trk")
        add_text(track, "name", name)
        segment = ET.SubElement(track, f"{{{GPX_NS}}}trkseg")
        for index, point in enumerate(points, 1):
            attrs = {"lat": f"{point.lat:.8f}", "lon": f"{point.lon:.8f}"}
            route_point = ET.SubElement(route, f"{{{GPX_NS}}}rtept", attrs)
            track_point = ET.SubElement(segment, f"{{{GPX_NS}}}trkpt", attrs)
            if point.elevation is not None:
                add_text(route_point, "ele", f"{point.elevation:.2f}")
                add_text(track_point, "ele", f"{point.elevation:.2f}")
            add_text(route_point, "name", point.name or f"Point {index}")
    return ET.ElementTree(root)


def write_gpx(points: list[Point], output: Path, name: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    tree = create_gpx(points, name)
    tree.write(output, encoding="utf-8", xml_declaration=True)


def validate_gpx(path: Path) -> int:
    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError) as exc:
        print(f"invalid GPX: {exc}", file=sys.stderr)
        return 1
    root = tree.getroot()
    if root.tag.rsplit("}", 1)[-1] != "gpx":
        print("invalid GPX: root element is not gpx", file=sys.stderr)
        return 1
    points = [element for element in root.iter() if element.tag.rsplit("}", 1)[-1] in ("wpt", "rtept", "trkpt")]
    try:
        for element in points:
            point_from_values(element.attrib["lat"], element.attrib["lon"])
    except (KeyError, ValueError) as exc:
        print(f"invalid GPX point: {exc}", file=sys.stderr)
        return 1
    print(f"valid GPX: {path} ({len(points)} point(s))")
    return 0


def device_status(_: argparse.Namespace) -> int:
    print("Xcode command line tools:", end=" ")
    try:
        result = subprocess.run(["xcode-select", "-p"], capture_output=True, text=True, check=False)
        print(result.stdout.strip() or "not found")
    except OSError:
        print("not found")
    print("For USB iPhone diagnostics run: .venv/bin/python iphone_control.py status")
    print("Real-device simulation requires Developer Mode and a compatible developer image.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gps-mock", description="Create GPX files for Xcode location simulation.")
    sub = parser.add_subparsers(dest="command", required=True)
    point = sub.add_parser("point", help="create a GPX file for one location")
    point.add_argument("--lat", required=True, help="latitude, -90..90")
    point.add_argument("--lon", required=True, help="longitude, -180..180")
    point.add_argument("--elevation", help="optional elevation in meters")
    point.add_argument("--name", default="Mock location")
    point.add_argument("-o", "--output", type=Path, default=Path("mock-location.gpx"))
    point.set_defaults(handler=lambda args: (write_gpx([point_from_values(args.lat, args.lon, args.elevation, args.name)], args.output, args.name), print(f"wrote {args.output}"))[1] or 0)
    route = sub.add_parser("route", help="create a GPX route from repeated points or JSON/CSV")
    route.add_argument("--point", action="append", help="LAT,LON[,ELEVATION], repeat in travel order")
    route.add_argument("--input", type=Path, help="JSON or CSV input")
    route.add_argument("--name", default="Mock route")
    route.add_argument("-o", "--output", type=Path, default=Path("mock-route.gpx"))
    def route_handler(args: argparse.Namespace) -> int:
        if bool(args.point) == bool(args.input):
            fail("route requires exactly one of --point or --input")
        points = [parse_point_arg(value) for value in args.point] if args.point else load_points(args.input)
        write_gpx(points, args.output, args.name)
        print(f"wrote {args.output} ({len(points)} point(s))")
        return 0
    route.set_defaults(handler=route_handler)
    check = sub.add_parser("validate", help="validate a GPX file")
    check.add_argument("file", type=Path)
    check.set_defaults(handler=lambda args: validate_gpx(args.file))
    device = sub.add_parser("device", help="show Xcode/device simulation guidance")
    device.set_defaults(handler=device_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        return int(args.handler(args))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
