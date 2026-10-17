"""Previously ridden roads, loaded once and culled to the visible map area."""

import os

import numpy as np

from modules.app_logger import app_logger
from modules.utils.geo import get_mod_lat_np

EMPTY = np.array([], dtype=np.float64)


class RiddenRoads:
    def __init__(self, lon, lat, offsets):
        self.x = np.asarray(lon, dtype=np.float64)
        lat = np.asarray(lat, dtype=np.float64)
        self.y = get_mod_lat_np(lat)
        self.offsets = np.asarray(offsets, dtype=np.int64)
        starts = self.offsets[:-1]
        if len(starts):
            self.bounds = np.column_stack(
                (
                    np.minimum.reduceat(self.x, starts),
                    np.maximum.reduceat(self.x, starts),
                    np.minimum.reduceat(lat, starts),
                    np.maximum.reduceat(lat, starts),
                )
            )
        else:
            self.bounds = np.empty((0, 4))

    @classmethod
    def from_file(cls, path):
        if not path or not os.path.exists(path):
            return cls(EMPTY, EMPTY, [0])
        with np.load(path) as data:
            roads = cls(data["lon"], data["lat"], data["offsets"])
        app_logger.info(f"ridden roads: {len(roads.bounds)} chunks from {path}")
        return roads

    @property
    def is_empty(self):
        return not len(self.bounds)

    def visible(self, lon_start, lon_end, lat_start, lat_end):
        """Return plot coordinates (lon, projected lat) of chunks in the view."""
        hits = np.flatnonzero(
            (self.bounds[:, 1] >= lon_start)
            & (self.bounds[:, 0] <= lon_end)
            & (self.bounds[:, 3] >= lat_start)
            & (self.bounds[:, 2] <= lat_end)
        )
        if not len(hits):
            return EMPTY, EMPTY
        xs, ys = [], []
        for i in hits:
            start, end = self.offsets[i], self.offsets[i + 1]
            xs.extend((self.x[start:end], [np.nan]))
            ys.extend((self.y[start:end], [np.nan]))
        return np.concatenate(xs), np.concatenate(ys)
