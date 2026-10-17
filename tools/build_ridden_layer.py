import argparse
import math

import numpy as np

from gpx_to_tcx import read_gpx

EARTH_RADIUS_M = 6371000.0


def to_local_meters(lat, lon, lat0):
    x = np.radians(lon) * EARTH_RADIUS_M * math.cos(math.radians(lat0))
    y = np.radians(lat) * EARTH_RADIUS_M
    return x, y


def split_on_gaps(lat, lon, max_gap_m):
    x, y = to_local_meters(lat, lon, float(np.mean(lat)))
    gaps = np.hypot(np.diff(x), np.diff(y)) > max_gap_m
    cuts = np.flatnonzero(gaps) + 1
    return [
        (seg_lat, seg_lon)
        for seg_lat, seg_lon in zip(np.split(lat, cuts), np.split(lon, cuts))
        if len(seg_lat) > 1
    ]


def simplify(x, y, tolerance):
    keep = np.zeros(len(x), dtype=bool)
    keep[[0, -1]] = True
    stack = [(0, len(x) - 1)]
    while stack:
        start, end = stack.pop()
        if end - start < 2:
            continue
        dx, dy = x[end] - x[start], y[end] - y[start]
        length = math.hypot(dx, dy)
        px, py = x[start + 1 : end] - x[start], y[start + 1 : end] - y[start]
        if length == 0:
            distances = np.hypot(px, py)
        else:
            distances = np.abs(dx * py - dy * px) / length
        index = int(np.argmax(distances))
        if distances[index] > tolerance:
            middle = start + 1 + index
            keep[middle] = True
            stack.extend(((start, middle), (middle, end)))
    return keep


def chunk_bounds(length, chunk_size):
    starts = list(range(0, length - 1, chunk_size - 1))
    return [(start, min(start + chunk_size, length)) for start in starts]


def intersects(lat, lon, bbox):
    south, west, north, east = bbox
    return bool(
        np.any((lat >= south) & (lat <= north) & (lon >= west) & (lon <= east))
    )


def build_layer(paths, tolerance_m, max_gap_m, chunk_size, bbox):
    lon_parts, lat_parts, offsets = [], [], [0]
    for path in paths:
        _, points = read_gpx(path)
        lat = np.array([p[0] for p in points])
        lon = np.array([p[1] for p in points])
        if len(lat) < 2:
            continue
        for seg_lat, seg_lon in split_on_gaps(lat, lon, max_gap_m):
            x, y = to_local_meters(seg_lat, seg_lon, float(np.mean(seg_lat)))
            keep = simplify(x, y, tolerance_m)
            seg_lat, seg_lon = seg_lat[keep], seg_lon[keep]
            for start, end in chunk_bounds(len(seg_lat), chunk_size):
                chunk_lat, chunk_lon = seg_lat[start:end], seg_lon[start:end]
                if bbox and not intersects(chunk_lat, chunk_lon, bbox):
                    continue
                lat_parts.append(chunk_lat)
                lon_parts.append(chunk_lon)
                offsets.append(offsets[-1] + len(chunk_lat))
    return (
        np.concatenate(lon_parts) if lon_parts else np.array([]),
        np.concatenate(lat_parts) if lat_parts else np.array([]),
        np.array(offsets, dtype=np.int64),
    )


def parse_bbox(text):
    return tuple(float(v) for v in text.split(","))


def main():
    parser = argparse.ArgumentParser(description="Build the ridden-roads map layer from GPX files.")
    parser.add_argument("gpx", nargs="+")
    parser.add_argument("--output", required=True)
    parser.add_argument("--tolerance", type=float, default=4.0, help="simplification, metres")
    parser.add_argument("--max-gap", type=float, default=300.0, help="split tracks at jumps, metres")
    parser.add_argument("--chunk-size", type=int, default=32, help="points per culling chunk")
    parser.add_argument("--bbox", type=parse_bbox, help="south,west,north,east")
    args = parser.parse_args()

    lon, lat, offsets = build_layer(
        args.gpx, args.tolerance, args.max_gap, args.chunk_size, args.bbox
    )
    np.savez_compressed(args.output, lon=lon, lat=lat, offsets=offsets)
    print(f"{args.output}: {len(args.gpx)} tracks, {len(offsets) - 1} chunks, {len(lon)} points")


if __name__ == "__main__":
    main()
