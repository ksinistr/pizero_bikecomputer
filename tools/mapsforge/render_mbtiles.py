import argparse
import io
import math
import sqlite3
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

EARTH_RADIUS_M = 6371000.0


def tile_xy(lat, lon, zoom):
    n = 2**zoom
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def padded_bbox(bbox, pad_km):
    south, west, north, east = bbox
    dlat = math.degrees(pad_km * 1000 / EARTH_RADIUS_M)
    dlon = dlat / math.cos(math.radians((south + north) / 2))
    return south - dlat, west - dlon, north + dlat, east + dlon


def tiles_in_bbox(bbox, zoom):
    south, west, north, east = bbox
    x0, y0 = tile_xy(north, west, zoom)
    x1, y1 = tile_xy(south, east, zoom)
    return [(zoom, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]


def to_one_bit(png, threshold):
    gray = Image.open(io.BytesIO(png)).convert("L")
    mono = gray.point(lambda v: 255 if v >= threshold else 0).convert("1")
    out = io.BytesIO()
    mono.save(out, "PNG", optimize=True)
    return out.getvalue()


def fetch(url_template, tile):
    z, x, y = tile
    with urllib.request.urlopen(url_template.format(z=z, x=x, y=y), timeout=120) as r:
        return r.read()


def open_mbtiles(path, name, bbox, zooms):
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS tiles (
            zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB,
            PRIMARY KEY (zoom_level, tile_column, tile_row)
        );
        """
    )
    south, west, north, east = bbox
    metadata = {
        "name": name,
        "format": "png",
        "type": "baselayer",
        "bounds": f"{west},{south},{east},{north}",
        "minzoom": str(min(zooms)),
        "maxzoom": str(max(zooms)),
    }
    db.executemany("INSERT OR REPLACE INTO metadata VALUES (?, ?)", metadata.items())
    return db


def parse_zooms(text):
    low, _, high = text.partition("-")
    return list(range(int(low), int(high or low) + 1))


def parse_bbox(text):
    south, west, north, east = (float(v) for v in text.split(","))
    return south, west, north, east


def main():
    parser = argparse.ArgumentParser(description="Render XYZ tiles from a tile server into MBTiles.")
    parser.add_argument("--url", required=True, help="template with {z} {x} {y}")
    parser.add_argument("--bbox", required=True, type=parse_bbox, help="south,west,north,east")
    parser.add_argument("--pad-km", type=float, default=0.0)
    parser.add_argument("--zooms", default="10-16", type=parse_zooms)
    parser.add_argument("--one-bit", type=int, metavar="THRESHOLD")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--name", required=True)
    parser.add_argument("output")
    args = parser.parse_args()

    bbox = padded_bbox(args.bbox, args.pad_km)
    tiles = [t for z in args.zooms for t in tiles_in_bbox(bbox, z)]
    db = open_mbtiles(args.output, args.name, bbox, args.zooms)

    def render(tile):
        png = fetch(args.url, tile)
        return tile, to_one_bit(png, args.one_bit) if args.one_bit else png

    with ThreadPoolExecutor(args.workers) as pool:
        for done, ((z, x, y), png) in enumerate(pool.map(render, tiles), 1):
            db.execute(
                "INSERT OR REPLACE INTO tiles VALUES (?, ?, ?, ?)",
                (z, x, 2**z - 1 - y, png),
            )
            if done % 200 == 0 or done == len(tiles):
                db.commit()
                print(f"{done}/{len(tiles)} tiles", flush=True)
    db.close()


if __name__ == "__main__":
    main()
