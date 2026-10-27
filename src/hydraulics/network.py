"""Rede hidráulica: coleção de nós, ligações, curvas, padrões e controles.

As conexões são armazenadas explicitamente (Link.start / Link.end = uid do nó).
A geometria das ligações é derivada das coordenadas dos nós + vértices.
"""

from __future__ import annotations

import math
from typing import Iterable

from .models import (Element, Node, Link, Pipe, Curve, Pattern, Control,
                     NAME_PREFIX, element_from_dict)


class Network:
    def __init__(self):
        self.nodes: dict[str, Node] = {}
        self.links: dict[str, Link] = {}
        self.curves: dict[str, Curve] = {}
        self.patterns: dict[str, Pattern] = {}
        self.controls: dict[str, Control] = {}
        self._adj: dict[str, list[str]] | None = None

    # ------------------------------------------------------------------ acesso
    def _store(self, collection: str) -> dict:
        return {'node': self.nodes, 'link': self.links, 'curve': self.curves,
                'pattern': self.patterns, 'control': self.controls}[collection]

    def get(self, uid: str) -> Element | None:
        for store in (self.nodes, self.links, self.curves, self.patterns, self.controls):
            if uid in store:
                return store[uid]
        return None

    def put(self, elem: Element):
        self._store(elem.COLLECTION)[elem.uid] = elem
        self._adj = None

    def remove(self, uid: str) -> Element | None:
        for store in (self.nodes, self.links, self.curves, self.patterns, self.controls):
            if uid in store:
                self._adj = None
                return store.pop(uid)
        return None

    def invalidate(self):
        self._adj = None

    def elements(self) -> Iterable[Element]:
        yield from self.nodes.values()
        yield from self.links.values()
        yield from self.curves.values()
        yield from self.patterns.values()
        yield from self.controls.values()

    def of_kind(self, kind: str) -> list[Element]:
        return [e for e in self.elements() if e.KIND == kind]

    def find_by_name(self, name: str, collection: str | None = None) -> Element | None:
        stores = [self._store(collection)] if collection else [
            self.nodes, self.links, self.curves, self.patterns, self.controls]
        for store in stores:
            for e in store.values():
                if e.name == name:
                    return e
        return None

    def unique_name(self, kind: str, taken: set[str] | None = None) -> str:
        prefix = NAME_PREFIX.get(kind, 'X')
        used = {e.name for e in self.elements()} | (taken or set())
        n = 1
        for e in self.elements():
            if e.KIND == kind and e.name.startswith(prefix) and e.name[len(prefix):].isdigit():
                n = max(n, int(e.name[len(prefix):]) + 1)
        while f'{prefix}{n}' in used:
            n += 1
        return f'{prefix}{n}'

    # -------------------------------------------------------------- topologia
    def adjacency(self) -> dict[str, list[str]]:
        """nó -> lista de uids das ligações conectadas."""
        if self._adj is None:
            adj = {uid: [] for uid in self.nodes}
            for link in self.links.values():
                for n in (link.start, link.end):
                    if n in adj:
                        adj[n].append(link.uid)
            self._adj = adj
        return self._adj

    def links_of_node(self, node_uid: str) -> list[Link]:
        return [self.links[u] for u in self.adjacency().get(node_uid, [])]

    # -------------------------------------------------------------- geometria
    def link_points(self, link: Link) -> list[tuple[float, float]]:
        pts = []
        a = self.nodes.get(link.start)
        b = self.nodes.get(link.end)
        if a is not None:
            pts.append((a.x, a.y))
        pts.extend((float(v[0]), float(v[1])) for v in link.vertices)
        if b is not None:
            pts.append((b.x, b.y))
        return pts

    def geometric_length(self, link: Link) -> float:
        pts = self.link_points(link)
        return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))

    def hydraulic_length(self, pipe: Pipe) -> float:
        """Comprimento enviado ao motor: geométrico se auto_length, senão o cadastrado."""
        return self.geometric_length(pipe) if pipe.auto_length else pipe.length

    def bounds(self):
        xs, ys = [], []
        for n in self.nodes.values():
            xs.append(n.x)
            ys.append(n.y)
        for l in self.links.values():
            for v in l.vertices:
                xs.append(v[0])
                ys.append(v[1])
        if not xs:
            return None
        return min(xs), min(ys), max(xs), max(ys)

    # -------------------------------------------------------------- persistência
    def to_dict(self) -> dict:
        return {
            'nodes': [e.to_dict() for e in self.nodes.values()],
            'links': [e.to_dict() for e in self.links.values()],
            'curves': [e.to_dict() for e in self.curves.values()],
            'patterns': [e.to_dict() for e in self.patterns.values()],
            'controls': [e.to_dict() for e in self.controls.values()],
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'Network':
        net = cls()
        for key in ('nodes', 'links', 'curves', 'patterns', 'controls'):
            for item in d.get(key, []):
                net.put(element_from_dict(item))
        return net

    def copy(self) -> 'Network':
        return Network.from_dict(self.to_dict())

    def counts(self) -> dict[str, int]:
        c: dict[str, int] = {}
        for e in self.elements():
            c[e.KIND] = c.get(e.KIND, 0) + 1
        return c
