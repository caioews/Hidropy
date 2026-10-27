"""Análise de conectividade da rede (sem cálculo hidráulico)."""

from __future__ import annotations

import math
from collections import deque

from .network import Network

SOURCE_KINDS = ('reservoir', 'tank')


def components(net: Network) -> list[set[str]]:
    """Componentes conexos (conjuntos de uids de nós), considerando ligações válidas."""
    adj: dict[str, set[str]] = {u: set() for u in net.nodes}
    for l in net.links.values():
        if l.start in adj and l.end in adj:
            adj[l.start].add(l.end)
            adj[l.end].add(l.start)
    seen: set[str] = set()
    comps = []
    for u in adj:
        if u in seen:
            continue
        comp = set()
        q = deque([u])
        seen.add(u)
        while q:
            v = q.popleft()
            comp.add(v)
            for w in adj[v]:
                if w not in seen:
                    seen.add(w)
                    q.append(w)
        comps.append(comp)
    return comps


def isolated_nodes(net: Network) -> list[str]:
    adj = net.adjacency()
    return [u for u, links in adj.items() if not links]


def nodes_without_source(net: Network) -> list[str]:
    """Nós em componentes que não contêm reservatório nem tanque."""
    out = []
    for comp in components(net):
        if not any(net.nodes[u].KIND in SOURCE_KINDS for u in comp):
            out.extend(sorted(comp))
    return out


def coincident_nodes(net: Network, tol: float) -> list[tuple[str, str]]:
    """Pares de nós distintos a menos de `tol` metros (provável duplicidade)."""
    cell = max(tol, 1e-9)
    grid: dict[tuple[int, int], list[str]] = {}
    pairs = []
    for n in net.nodes.values():
        key = (int(math.floor(n.x / cell)), int(math.floor(n.y / cell)))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other in grid.get((key[0] + dx, key[1] + dy), []):
                    o = net.nodes[other]
                    if math.dist((n.x, n.y), (o.x, o.y)) <= tol:
                        pairs.append((other, n.uid))
        grid.setdefault(key, []).append(n.uid)
    return pairs


def _point_segment_distance(p, a, b) -> tuple[float, float]:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return math.dist(p, a), 0.0
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return math.dist(p, (ax + t * dx, ay + t * dy)), t


def nodes_on_links_not_connected(net: Network, tol: float) -> list[tuple[str, str]]:
    """Nós que tocam visualmente uma ligação sem estar conectados a ela.

    Devolve pares (uid do nó, uid da ligação). Não cria conexão — apenas aponta.
    """
    out = []
    for link in net.links.values():
        pts = net.link_points(link)
        if len(pts) < 2:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        bx0, bx1, by0, by1 = min(xs) - tol, max(xs) + tol, min(ys) - tol, max(ys) + tol
        for n in net.nodes.values():
            if n.uid in (link.start, link.end):
                continue
            if not (bx0 <= n.x <= bx1 and by0 <= n.y <= by1):
                continue
            for i in range(len(pts) - 1):
                d, _ = _point_segment_distance((n.x, n.y), pts[i], pts[i + 1])
                if d <= tol:
                    out.append((n.uid, link.uid))
                    break
    return out


def nearest_node(net: Network, x: float, y: float, tol: float,
                 exclude: set[str] | None = None) -> list[str]:
    """Nós dentro de `tol` de (x, y), do mais próximo ao mais distante."""
    cand = []
    for n in net.nodes.values():
        if exclude and n.uid in exclude:
            continue
        d = math.dist((x, y), (n.x, n.y))
        if d <= tol:
            cand.append((d, n.uid))
    return [u for _, u in sorted(cand)]
