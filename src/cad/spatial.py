"""Índice espacial simples (grade de baldes) sobre os elementos visíveis do projeto."""

from __future__ import annotations

import math

from . import geometry as G


class SpatialIndex:
    def __init__(self, project):
        self.project = project
        self.dirty = True
        self.cell = 50.0
        self.buckets: dict[tuple[int, int], set[str]] = {}
        self.polys: dict[str, list] = {}
        self.points: dict[str, list] = {}

    def invalidate(self):
        self.dirty = True

    def _key(self, x, y):
        return int(math.floor(x / self.cell)), int(math.floor(y / self.cell))

    def rebuild(self):
        p = self.project
        self.buckets.clear()
        self.polys.clear()
        self.points.clear()
        b = p.bounds()
        if b:
            span = max(b[2] - b[0], b[3] - b[1], 1.0)
            self.cell = max(span / 256.0, 0.5)
        elems = list(p.network.nodes.values()) + list(p.network.links.values()) + \
            list(p.cad.values())
        for e in elems:
            if not p.layer_visible(e.layer):
                continue
            pts = G.element_polyline(p, e)
            if not pts:
                continue
            self.polys[e.uid] = pts
            self.points[e.uid] = G.snap_points(p, e)
            x0, y0, x1, y1 = G.bbox(pts)
            k0, k1 = self._key(x0, y0), self._key(x1, y1)
            # entidades muito grandes: amostra ao longo dos segmentos
            if (k1[0] - k0[0] + 1) * (k1[1] - k0[1] + 1) > 400:
                keys = set()
                for i in range(len(pts) - 1):
                    a, c = pts[i], pts[i + 1]
                    n = int(math.dist(a, c) / self.cell) + 2
                    for s in range(n + 1):
                        keys.add(self._key(a[0] + (c[0] - a[0]) * s / n,
                                           a[1] + (c[1] - a[1]) * s / n))
                if len(pts) == 1:
                    keys.add(k0)
            else:
                keys = {(i, j) for i in range(k0[0], k1[0] + 1) for j in range(k0[1], k1[1] + 1)}
            for k in keys:
                self.buckets.setdefault(k, set()).add(e.uid)
        self.dirty = False

    def query(self, x0, y0, x1, y1) -> set[str]:
        if self.dirty:
            self.rebuild()
        k0, k1 = self._key(x0, y0), self._key(x1, y1)
        n = (k1[0] - k0[0] + 1) * (k1[1] - k0[1] + 1)
        if n > 20000:
            return set(self.polys)
        out = set()
        for i in range(k0[0], k1[0] + 1):
            for j in range(k0[1], k1[1] + 1):
                s = self.buckets.get((i, j))
                if s:
                    out |= s
        return out

    def near(self, x, y, r) -> set[str]:
        return self.query(x - r, y - r, x + r, y + r)
