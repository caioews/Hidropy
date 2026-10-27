"""Seleção por clique e por janela, calculada no espaço do MODELO."""

from __future__ import annotations

import math

from . import geometry as G

_PRIORITY = {'node': 0, 'link': 1, 'cad': 2}


def selectable(project, e) -> bool:
    return project.layer_visible(e.layer) and not project.layer_locked(e.layer)


def pick(project, index, x, y, tol, only: set | None = None) -> str | None:
    """Elemento mais próximo de (x, y) dentro de `tol`. Nós têm prioridade."""
    best = None
    for uid in index.near(x, y, tol):
        e = project.get(uid)
        if e is None or not selectable(project, e):
            continue
        if only and e.COLLECTION not in only:
            continue
        pts = index.polys.get(uid)
        if not pts:
            continue
        if e.COLLECTION == 'cad' and e.geom == 'text':
            d = 0.0 if G.rect_contains(G.bbox(pts), [(x, y)]) else \
                G.polyline_distance((x, y), pts)[0]
        elif e.COLLECTION == 'cad' and e.geom == 'circle' and e.closed:
            d = abs(math.dist((x, y), e.points[0]) - e.radius)
        else:
            d = G.polyline_distance((x, y), pts)[0]
        if d <= tol:
            key = (_PRIORITY[e.COLLECTION], d)
            if best is None or key < best[0]:
                best = (key, uid)
    return best[1] if best else None


def window(project, index, x0, y0, x1, y1, crossing: bool) -> list[str]:
    """Janela (contido) ou captura (cruzando), como nos CADs usuais."""
    rect = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    out = []
    for uid in index.query(*rect):
        e = project.get(uid)
        if e is None or not selectable(project, e):
            continue
        pts = index.polys.get(uid, [])
        if not pts:
            continue
        ok = G.rect_intersects(rect, pts) if crossing else G.rect_contains(rect, pts)
        if ok:
            out.append(uid)
    return out
