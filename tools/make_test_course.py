import argparse
import datetime
import json
import time
import urllib.error
import math
import urllib.parse
import urllib.request
from xml.sax.saxutils import escape

ROUTER_URL = "https://routing.openstreetmap.de/routed-bike/route/v1/driving/{coords}"
ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
ELEVATION_BATCH = 100
EARTH_RADIUS_M = 6371000.0
NOMINAL_SPEED_MPS = 20 / 3.6
COURSE_START = datetime.datetime(2026, 1, 1, 8, 0, 0, tzinfo=datetime.timezone.utc)

TURN_TYPES = {
    "left": "Left",
    "right": "Right",
    "slight left": "Slight Left",
    "slight right": "Slight Right",
    "sharp left": "Sharp Left",
    "sharp right": "Sharp Right",
    "uturn": "Uturn Left",
}


def fetch_json(url, attempts=6):
    request = urllib.request.Request(url, headers={"User-Agent": "pizero-course-maker"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == attempts - 1:
                raise
            time.sleep(5 * (attempt + 1))


def haversine_m(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def fetch_route(waypoints):
    coords = ";".join(f"{lon},{lat}" for lat, lon in waypoints)
    query = urllib.parse.urlencode(
        {"overview": "full", "geometries": "geojson", "steps": "true"}
    )
    data = fetch_json(ROUTER_URL.format(coords=coords) + "?" + query)
    route = data["routes"][0]
    points = [(lat, lon) for lon, lat in route["geometry"]["coordinates"]]
    turns = [
        (step["maneuver"]["location"][1], step["maneuver"]["location"][0],
         TURN_TYPES[step["maneuver"].get("modifier", "")], step.get("name") or "")
        for leg in route["legs"]
        for step in leg["steps"]
        if step["maneuver"]["type"] in ("turn", "end of road", "fork", "on ramp", "off ramp")
        and step["maneuver"].get("modifier", "") in TURN_TYPES
    ]
    return points, turns


def resample(points, spacing_m):
    result = [points[0]]
    carry = 0.0
    for a, b in zip(points, points[1:]):
        segment = haversine_m(a, b)
        position = spacing_m - carry
        while position <= segment:
            t = position / segment
            result.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            position += spacing_m
        carry = (carry + segment) % spacing_m
    result.append(points[-1])
    return result


def fetch_elevations(points):
    elevations = []
    for start in range(0, len(points), ELEVATION_BATCH):
        batch = points[start:start + ELEVATION_BATCH]
        query = urllib.parse.urlencode({
            "latitude": ",".join(f"{lat:.6f}" for lat, _ in batch),
            "longitude": ",".join(f"{lon:.6f}" for _, lon in batch),
        })
        elevations.extend(fetch_json(f"{ELEVATION_URL}?{query}")["elevation"])
        time.sleep(1.5)
    return elevations


def cumulative_distances(points):
    distances = [0.0]
    for a, b in zip(points, points[1:]):
        distances.append(distances[-1] + haversine_m(a, b))
    return distances


def nominal_time(distance_m):
    moment = COURSE_START + datetime.timedelta(seconds=round(distance_m / NOMINAL_SPEED_MPS))
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def nearest_index(points, location):
    return min(range(len(points)), key=lambda i: haversine_m(points[i], location))


def render_tcx(name, points, elevations, distances, turns):
    times = [nominal_time(d) for d in distances]
    trackpoints = "\n".join(
        "        <Trackpoint>"
        f"<Time>{time}</Time>"
        f"<Position><LatitudeDegrees>{lat:.6f}</LatitudeDegrees>"
        f"<LongitudeDegrees>{lon:.6f}</LongitudeDegrees></Position>"
        f"<AltitudeMeters>{ele:.1f}</AltitudeMeters>"
        f"<DistanceMeters>{dist:.1f}</DistanceMeters>"
        "</Trackpoint>"
        for (lat, lon), ele, dist, time in zip(points, elevations, distances, times)
    )
    snapped = [
        (points[i], times[i], turn_type, road)
        for i, turn_type, road in sorted(
            (nearest_index(points, (lat, lon)), turn_type, road)
            for lat, lon, turn_type, road in turns
        )
    ]
    course_points = "\n".join(
        "      <CoursePoint>"
        f"<Name>{escape(turn_type)}</Name>"
        f"<Time>{time}</Time>"
        f"<Position><LatitudeDegrees>{lat:.6f}</LatitudeDegrees>"
        f"<LongitudeDegrees>{lon:.6f}</LongitudeDegrees></Position>"
        f"<PointType>{escape(turn_type)}</PointType>"
        f"<Notes>{escape(road or turn_type)}</Notes>"
        "</CoursePoint>"
        for (lat, lon), time, turn_type, road in snapped
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
{course_points}
    </Course>
  </Courses>
</TrainingCenterDatabase>
"""


def parse_waypoint(text):
    lat, lon = text.split(",")
    return float(lat), float(lon)


def main():
    parser = argparse.ArgumentParser(description="Build a TCX test course from routed waypoints.")
    parser.add_argument("--name", required=True)
    parser.add_argument("--spacing", type=float, default=25.0)
    parser.add_argument("--output", required=True)
    parser.add_argument("waypoints", nargs="+", type=parse_waypoint, help="lat,lon")
    args = parser.parse_args()

    raw_points, turns = fetch_route(args.waypoints)
    points = resample(raw_points, args.spacing)
    elevations = fetch_elevations(points)
    distances = cumulative_distances(points)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(render_tcx(args.name, points, elevations, distances, turns))
    print(
        f"{args.output}: {distances[-1] / 1000:.1f} km, {len(points)} points, "
        f"{len(turns)} turns, elevation {min(elevations):.0f}-{max(elevations):.0f} m"
    )


if __name__ == "__main__":
    main()
