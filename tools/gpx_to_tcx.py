import argparse
import math
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

GPX_NS = {"gpx": "http://www.topografix.com/GPX/1/1"}
EARTH_RADIUS_M = 6371000.0


def haversine_m(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def read_gpx(path):
    root = ET.parse(path).getroot()
    name = root.findtext("gpx:trk/gpx:name", default="GPX track", namespaces=GPX_NS)
    points = [
        (
            float(pt.get("lat")),
            float(pt.get("lon")),
            pt.findtext("gpx:ele", namespaces=GPX_NS),
            pt.findtext("gpx:time", namespaces=GPX_NS),
        )
        for pt in root.iterfind(".//gpx:trkpt", GPX_NS)
    ]
    return name.strip(), points


def drop_close_points(points, min_spacing_m):
    kept = [points[0]]
    for point in points[1:]:
        if haversine_m(kept[-1], point) >= min_spacing_m:
            kept.append(point)
    if kept[-1] is not points[-1]:
        kept.append(points[-1])
    return kept


def cumulative_distances(points):
    distances = [0.0]
    for a, b in zip(points, points[1:]):
        distances.append(distances[-1] + haversine_m(a, b))
    return distances


def render_trackpoint(point, distance):
    lat, lon, ele, time = point
    parts = ["        <Trackpoint>"]
    if time:
        parts.append(f"<Time>{escape(time)}</Time>")
    parts.append(
        f"<Position><LatitudeDegrees>{lat:.6f}</LatitudeDegrees>"
        f"<LongitudeDegrees>{lon:.6f}</LongitudeDegrees></Position>"
    )
    if ele:
        parts.append(f"<AltitudeMeters>{float(ele):.1f}</AltitudeMeters>")
    parts.append(f"<DistanceMeters>{distance:.1f}</DistanceMeters></Trackpoint>")
    return "".join(parts)


def render_tcx(name, points, distances):
    trackpoints = "\n".join(
        render_trackpoint(point, distance) for point, distance in zip(points, distances)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Courses>
    <Course>
      <Name>{escape(name)}</Name>
      <Lap><DistanceMeters>{distances[-1]:.1f}</DistanceMeters></Lap>
      <Track>
{trackpoints}
      </Track>
    </Course>
  </Courses>
</TrainingCenterDatabase>
"""


def main():
    parser = argparse.ArgumentParser(description="Convert a GPX track to a TCX course.")
    parser.add_argument("gpx")
    parser.add_argument("tcx")
    parser.add_argument("--name")
    parser.add_argument("--min-spacing", type=float, default=5.0, help="metres")
    args = parser.parse_args()

    name, raw_points = read_gpx(args.gpx)
    points = drop_close_points(raw_points, args.min_spacing)
    distances = cumulative_distances(points)
    with open(args.tcx, "w", encoding="utf-8") as f:
        f.write(render_tcx(args.name or name, points, distances))

    elevations = [float(p[2]) for p in points if p[2]]
    elevation = (
        f"elevation {min(elevations):.0f}-{max(elevations):.0f} m"
        if elevations
        else "no elevation"
    )
    print(
        f"{args.tcx}: {distances[-1] / 1000:.1f} km, "
        f"{len(raw_points)} -> {len(points)} points, {elevation}"
    )


if __name__ == "__main__":
    main()
