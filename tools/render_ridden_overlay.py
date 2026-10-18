import argparse
import io
import math
import sqlite3
from collections import defaultdict

import numpy as np
from PIL import Image, ImageDraw

TILE = 256
SUPERSAMPLE = 2
LINE_WIDTHS = {8: 2, 9: 2, 10: 2, 11: 3, 12: 3, 13: 4, 14: 4, 15: 5, 16: 6, 17: 7, 18: 8}


def world_pixels(lon, lat, zoom):
    scale = TILE * 2**zoom
    x = (lon + 180.0) / 360.0 * scale
    y = (1.0 - np.arcsinh(np.tan(np.radians(lat))) / math.pi) / 2.0 * scale
    return x, y


def chunks_by_tile(x, y, offsets, margin):
    tiles = defaultdict(list)
    for i in range(len(offsets) - 1):
        start, end = offsets[i], offsets[i + 1]
        cx, cy = x[start:end], y[start:end]
        x0, x1 = int((cx.min() - margin) // TILE), int((cx.max() + margin) // TILE)
        y0, y1 = int((cy.min() - margin) // TILE), int((cy.max() + margin) // TILE)
        for tx in range(x0, x1 + 1):
            for ty in range(y0, y1 + 1):
                tiles[(tx, ty)].append(i)
    return tiles


def render_tile(tx, ty, chunk_ids, x, y, offsets, width, color):
    size = TILE * SUPERSAMPLE
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    ox, oy = tx * TILE, ty * TILE
    for i in chunk_ids:
        start, end = offsets[i], offsets[i + 1]
        points = list(
            zip(
                ((x[start:end] - ox) * SUPERSAMPLE).tolist(),
                ((y[start:end] - oy) * SUPERSAMPLE).tolist(),
            )
        )
        draw.line(points, fill=color, width=width * SUPERSAMPLE, joint="curve")
    image = image.resize((TILE, TILE), Image.Resampling.LANCZOS)
    if image.getchannel("A").getbbox() is None:
        return None
    out = io.BytesIO()
    image.save(out, "PNG", optimize=True)
    return out.getvalue()


def open_mbtiles(path, name, lon, lat, zooms):
    db = sqlite3.connect(path)
    db.executescript(
        """
        DROP TABLE IF EXISTS metadata;
        DROP TABLE IF EXISTS tiles;
        CREATE TABLE metadata (name TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE tiles (
            zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB,
            PRIMARY KEY (zoom_level, tile_column, tile_row)
        );
        """
    )
    metadata = {
        "name": name,
        "format": "png",
        "type": "overlay",
        "bounds": f"{lon.min()},{lat.min()},{lon.max()},{lat.max()}",
        "minzoom": str(min(zooms)),
        "maxzoom": str(max(zooms)),
    }
    db.executemany("INSERT INTO metadata VALUES (?, ?)", metadata.items())
    return db


def parse_zooms(text):
    low, _, high = text.partition("-")
    return list(range(int(low), int(high or low) + 1))


def parse_color(text):
    text = text.lstrip("#")
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4)) + (255,)


def main():
    parser = argparse.ArgumentParser(description="Render ridden roads into a transparent MBTiles overlay.")
    parser.add_argument("layer", help="ridden_roads.npz from build_ridden_layer.py")
    parser.add_argument("output")
    parser.add_argument("--zooms", default="8-16", type=parse_zooms)
    parser.add_argument("--color", default="#E0007A", type=parse_color)
    parser.add_argument("--name", default="Ridden roads")
    args = parser.parse_args()

    with np.load(args.layer) as data:
        lon, lat, offsets = data["lon"], data["lat"], data["offsets"]
    db = open_mbtiles(args.output, args.name, lon, lat, args.zooms)

    for zoom in args.zooms:
        width = LINE_WIDTHS.get(zoom, 6)
        x, y = world_pixels(lon, lat, zoom)
        candidates = chunks_by_tile(x, y, offsets, margin=width)
        written = 0
        for (tx, ty), chunk_ids in candidates.items():
            png = render_tile(tx, ty, chunk_ids, x, y, offsets, width, args.color)
            if png is None:
                continue
            db.execute(
                "INSERT INTO tiles VALUES (?, ?, ?, ?)",
                (zoom, tx, 2**zoom - 1 - ty, png),
            )
            written += 1
        db.commit()
        print(f"z{zoom}: {written} tiles", flush=True)
    db.close()


if __name__ == "__main__":
    main()
