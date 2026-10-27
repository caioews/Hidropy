"""Geometria de apoio (coordenadas do MODELO, em metros): segmentos, pontos notáveis,
distâncias e interseções. Sem dependência de Qt."""

from __future__ import annotations

import math

Point = tuple[float, float]


def arc_points(cx, cy, r, a0, a1, n=48) -> list[Point]:
    """Pontos de um arco (graus, sentido anti-horário de a0 a a1)."""
    if a1 <= a0:
        a1 += 360.0
    steps = max(2, int(n * (a1 - a0) / 360.0) + 1)
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * k / steps)),
             cy + r * math.sin(math.radians(a0 + (a1 - a0) * k / steps)))
            for k in range(steps + 1)]


def text_box(e) -> list[Point]:
    """Retângulo aproximado de um texto (para seleção)."""
    x, y = e.points[0]
    w = max(1, len(e.text)) * e.height * 0.6
    h = e.height
    a = math.radians(e.rotation)
    ca, sa = math.cos(a), math.sin(a)
    corners = [(0, 0), (w, 0), (w, h), (0, h)]
    return [(x + cx * ca - cy * sa, y + cx * sa + cy * ca) for cx, cy in corners]


def cad_polyline(e) -> list[Point]:
    """Representação poligonal de uma entidade CAD."""
    if e.geom in ('line', 'polyline', 'dimension'):
        pts = [tuple(p[:2]) for p in e.points]
        if e.closed and len(pts) > 2:
            pts.append(pts[0])
        return pts
    if e.geom == 'circle':
        cx, cy = e.points[0]
        return arc_points(cx, cy, e.radius, 0, 360)
    if e.geom == 'arc':
        cx, cy = e.points[0]
        return arc_points(cx, cy, e.radius, e.start_angle, e.end_angle)
    if e.geom == 'text':
        b = text_box(e)
        return b + [b[0]]
    if e.geom == 'point':
        return [tuple(e.points[0])]
    return []


def element_polyline(project, e) -> list[Point]:
    if e.COLLECTION == 'node':
        return [(e.x, e.y)]
    if e.COLLECTION == 'link':
        return project.network.link_points(e)
    if e.COLLECTION == 'cad':
        return cad_polyline(e)
    return []


def snap_points(project, e) -> list[tuple[str, Point]]:
    """Pontos notáveis: ('node'|'end'|'mid'|'center', ponto)."""
    out = []
    if e.COLLECTION == 'node':
        out.append(('node', (e.x, e.y)))
    elif e.COLLECTION == 'link':
        pts = project.network.link_points(e)
        for p in pts[1:-1]:
            out.append(('end', p))
        for i in range(len(pts) - 1):
            out.append(('mid', mid(pts[i], pts[i + 1])))
    elif e.COLLECTION == 'cad':
        if e.geom in ('line', 'polyline', 'dimension'):
            pts = cad_polyline(e)
            for p in pts:
                out.append(('end', p))
            for i in range(len(pts) - 1):
                out.append(('mid', mid(pts[i], pts[i + 1])))
        elif e.geom in ('circle', 'arc'):
            out.append(('center', tuple(e.points[0])))
            if e.geom == 'arc':
                pa = arc_points(*e.points[0], e.radius, e.start_angle, e.end_angle)
                out += [('end', pa[0]), ('end', pa[-1]), ('mid', pa[len(pa) // 2])]
        elif e.geom in ('text', 'point'):
            out.append(('end', tuple(e.points[0])))
    return out


def mid(a: Point, b: Point) -> Point:
    return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)


def seg_distance(p: Point, a: Point, b: Point) -> tuple[float, float, Point]:
    """(distância, parâmetro t, ponto projetado)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return math.dist(p, a), 0.0, a
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    q = (a[0] + t * dx, a[1] + t * dy)
    return math.dist(p, q), t, q


def polyline_distance(p: Point, pts: list[Point]) -> tuple[float, int, Point]:
    """(distância, índice do segmento, ponto mais próximo)."""
    if len(pts) == 1:
        return math.dist(p, pts[0]), 0, pts[0]
    best = (math.inf, -1, p)
    for i in range(len(pts) - 1):
        d, _, q = seg_distance(p, pts[i], pts[i + 1])
        if d < best[0]:
            best = (d, i, q)
    return best


def seg_intersection(a: Point, b: Point, c: Point, d: Point) -> Point | None:
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-12:
        return None
    t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / den
    u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den
    if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9:
        return (a[0] + t * r[0], a[1] + t * r[1])
    return None


def polyline_length(pts: list[Point]) -> float:
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def point_at_fraction(pts: list[Point], f: float) -> tuple[Point, float]:
    """Ponto a uma fração do comprimento e o ângulo (graus) do segmento."""
    total = polyline_length(pts)
    if total == 0 or len(pts) < 2:
        return (pts[0] if pts else (0.0, 0.0)), 0.0
    target = total * f
    acc = 0.0
    for i in range(len(pts) - 1):
        L = math.dist(pts[i], pts[i + 1])
        if acc + L >= target or i == len(pts) - 2:
            t = 0 if L == 0 else (target - acc) / L
            a, b = pts[i], pts[i + 1]
            ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
            return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])), ang
        acc += L
    return pts[-1], 0.0


def bbox(pts: list[Point]):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def rect_contains(rect, pts) -> bool:
    x0, y0, x1, y1 = rect
    return all(x0 <= p[0] <= x1 and y0 <= p[1] <= y1 for p in pts)


def rect_intersects(rect, pts) -> bool:
    x0, y0, x1, y1 = rect
    if any(x0 <= p[0] <= x1 and y0 <= p[1] <= y1 for p in pts):
        return True
    edges = [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)),
             ((x0, y1), (x0, y0))]
    for i in range(len(pts) - 1):
        for c, d in edges:
            if seg_intersection(pts[i], pts[i + 1], c, d):
                return True
    return False
