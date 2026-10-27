"""Snap à grade, nós, extremidades, pontos médios, centros e interseções."""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import geometry as G

SNAP_LABELS = {'node': 'Nó', 'end': 'Extremidade', 'mid': 'Ponto médio',
               'center': 'Centro', 'int': 'Interseção', 'grid': 'Grade', 'free': ''}
_WEIGHT = {'node': 0.5, 'end': 0.7, 'center': 0.8, 'int': 0.8, 'mid': 1.0}


@dataclass
class SnapResult:
    x: float
    y: float
    kind: str = 'free'
    uid: str = ''


def snap(project, index, x, y, tol, extra: list | None = None,
         exclude: set | None = None) -> SnapResult:
    """`tol` em unidades do modelo. `extra`: pontos adicionais [(kind, (x, y))]."""
    s = project.settings
    best: tuple[float, SnapResult] | None = None

    def consider(kind, p, uid=''):
        nonlocal best
        d = math.dist((x, y), p)
        if d > tol:
            return
        score = d * _WEIGHT.get(kind, 1.0)
        if best is None or score < best[0]:
            best = (score, SnapResult(p[0], p[1], kind, uid))

    near = index.near(x, y, tol) if index is not None else set()
    if exclude:
        near -= exclude
    for uid in near:
        for kind, p in index.points.get(uid, []):
            if kind == 'node' and not s.snap_nodes:
                continue
            if kind in ('end', 'center') and not s.snap_endpoints:
                continue
            if kind == 'mid' and not s.snap_midpoints:
                continue
            consider(kind, p, uid)
    for kind, p in (extra or []):
        consider(kind, p)

    if s.snap_intersections and (best is None or best[1].kind == 'mid') and near:
        segs = []
        for uid in list(near)[:60]:
            pts = index.polys.get(uid, [])
            for i in range(len(pts) - 1):
                a, b = pts[i], pts[i + 1]
                if G.seg_distance((x, y), a, b)[0] <= tol:
                    segs.append((uid, a, b))
        for i in range(len(segs)):
            for j in range(i + 1, len(segs)):
                if segs[i][0] == segs[j][0]:
                    continue
                q = G.seg_intersection(segs[i][1], segs[i][2], segs[j][1], segs[j][2])
                if q is not None:
                    consider('int', q)

    if best is not None:
        return best[1]
    if s.snap_grid and s.grid_spacing > 0:
        g = s.grid_spacing
        return SnapResult(round(x / g) * g, round(y / g) * g, 'grid')
    return SnapResult(x, y, 'free')
