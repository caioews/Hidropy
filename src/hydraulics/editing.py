"""Operações de edição do modelo. Todas devolvem listas de alterações
(uid, antes, depois) — dicionários serializados ou None — aplicadas pelo
controlador via pilha de desfazer/refazer. Nenhuma operação altera o projeto aqui.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field

from . import connectivity
from .models import Junction, Pipe, new_uid, element_from_dict
from .project import Project

Change = tuple[str, dict | None, dict | None]


def add(elems) -> list[Change]:
    return [(e.uid, None, e.to_dict()) for e in elems]


def update(project: Project, uid: str, **props) -> list[Change]:
    before = project.get_dict(uid)
    if before is None:
        return []
    after = copy.deepcopy(before)
    after.update(props)
    return [] if after == before else [(uid, before, after)]


def update_many(project: Project, items: list[tuple[str, dict]]) -> list[Change]:
    out = []
    for uid, props in items:
        out += update(project, uid, **props)
    return out


def delete(project: Project, uids) -> list[Change]:
    """Exclui elementos e as dependências (ligações dos nós, controles, referências)."""
    net = project.network
    uids = set(uids)
    for u in list(uids):
        if u in net.nodes:
            uids.update(l.uid for l in net.links_of_node(u))
    for c in net.controls.values():
        if c.link in uids or (c.node and c.node in uids):
            uids.add(c.uid)
    changes = [(u, project.get_dict(u), None) for u in uids if project.get(u) is not None]
    # referências a padrões/curvas excluídos são limpas (não deixam o modelo inválido)
    removed_refs = {u for u in uids if u in net.patterns or u in net.curves}
    if removed_refs:
        ref_fields = ('demand_pattern', 'head_pattern', 'pattern', 'curve', 'volume_curve',
                      'headloss_curve')
        for e in net.elements():
            if e.uid in uids:
                continue
            props = {f: '' for f in ref_fields if getattr(e, f, None) in removed_refs}
            if getattr(e, 'demand_categories', None):
                cats = [dict(c, pattern='' if c.get('pattern') in removed_refs else
                             c.get('pattern', '')) for c in e.demand_categories]
                if cats != e.demand_categories:
                    props['demand_categories'] = cats
            if props:
                changes += update(project, e.uid, **props)
    return changes


@dataclass
class MergePlan:
    changes: list = field(default_factory=list)
    moved_links: list = field(default_factory=list)     # nomes das ligações transferidas
    removed_links: list = field(default_factory=list)   # ligações que virariam laço (excluídas)
    parallel: list = field(default_factory=list)        # pares de ligações paralelas resultantes
    lost_demand: float = 0.0


def merge_nodes(project: Project, src_uid: str, dst_uid: str) -> MergePlan:
    """Une o nó `src` ao nó `dst`: as ligações e controles de `src` passam para `dst`, que
    conserva todas as suas características (posição, cota, demanda...); `src` é excluído.
    Ligações entre `src` e `dst` viram laço e são excluídas."""
    net = project.network
    plan = MergePlan()
    src, dst = net.nodes.get(src_uid), net.nodes.get(dst_uid)
    if src is None or dst is None or src_uid == dst_uid:
        return plan
    others = {}
    for l in net.links_of_node(dst_uid):
        others.setdefault(l.end if l.start == dst_uid else l.start, []).append(l.name)
    for l in net.links_of_node(src_uid):
        other = l.end if l.start == src_uid else l.start
        if other == dst_uid:
            plan.changes.append((l.uid, l.to_dict(), None))
            plan.removed_links.append(l.name)
            continue
        props = {'start': dst_uid} if l.start == src_uid else {'end': dst_uid}
        plan.changes += update(project, l.uid, **props)
        plan.moved_links.append(l.name)
        if other in others:
            plan.parallel.append((l.name, others[other][0]))
    removed = {c[0] for c in plan.changes if c[2] is None}
    for c in net.controls.values():
        if c.node == src_uid:
            plan.changes += update(project, c.uid, node=dst_uid)
        elif c.link in removed:
            plan.changes.append((c.uid, c.to_dict(), None))
    plan.lost_demand = getattr(src, 'base_demand', 0.0) or 0.0
    plan.changes.append((src_uid, src.to_dict(), None))
    return plan


def set_existing(project: Project, uids, value: bool) -> list[Change]:
    """Marca tubulações como existentes (executadas) ou projetadas."""
    out = []
    for u in uids:
        l = project.network.links.get(u)
        if isinstance(l, Pipe):
            out += update(project, u, fixed_in_optimization=bool(value))
    return out


# ---------------------------------------------------------------------------
# Transformações geométricas
# ---------------------------------------------------------------------------

def transform(project: Project, uids, fn, rot_delta: float = 0.0,
              mirror_axis_angle: float | None = None) -> list[Change]:
    """Aplica fn(x, y) -> (x, y) aos elementos. Ligações movem seus vértices;
    os nós das extremidades só se movem quando também estão selecionados."""
    out = []
    for uid in uids:
        e = project.get(uid)
        if e is None:
            continue
        before = e.to_dict()
        after = copy.deepcopy(before)
        if e.COLLECTION == 'node':
            after['x'], after['y'] = fn(e.x, e.y)
        elif e.COLLECTION == 'link':
            after['vertices'] = [list(fn(*v[:2])) for v in e.vertices]
        elif e.COLLECTION == 'cad':
            after['points'] = [list(fn(*p[:2])) for p in e.points]
            if e.geom == 'arc':
                if mirror_axis_angle is not None:
                    a0 = 2 * mirror_axis_angle - e.end_angle
                    a1 = 2 * mirror_axis_angle - e.start_angle
                    after['start_angle'], after['end_angle'] = a0 % 360, a1 % 360
                else:
                    after['start_angle'] = (e.start_angle + rot_delta) % 360
                    after['end_angle'] = (e.end_angle + rot_delta) % 360
            if e.geom == 'text':
                if mirror_axis_angle is not None:
                    after['rotation'] = (2 * mirror_axis_angle - e.rotation) % 360
                else:
                    after['rotation'] = (e.rotation + rot_delta) % 360
        else:
            continue
        if after != before:
            out.append((uid, before, after))
    return out


def move(project, uids, dx, dy):
    return transform(project, uids, lambda x, y: (x + dx, y + dy))


def rotate(project, uids, cx, cy, angle_deg):
    a = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)
    return transform(project, uids,
                     lambda x, y: (cx + (x - cx) * ca - (y - cy) * sa,
                                   cy + (x - cx) * sa + (y - cy) * ca), rot_delta=angle_deg)


def mirror(project, uids, ax, ay, bx, by):
    """Espelha em relação à reta A-B."""
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy or 1.0
    ang = math.degrees(math.atan2(dy, dx))

    def fn(x, y):
        t = ((x - ax) * dx + (y - ay) * dy) / L2
        px, py = ax + t * dx, ay + t * dy
        return 2 * px - x, 2 * py - y
    return transform(project, uids, fn, mirror_axis_angle=ang)


def centroid(project, uids):
    from ..cad import geometry as G
    pts = []
    for u in uids:
        e = project.get(u)
        if e is not None:
            pts += G.element_polyline(project, e)
    if not pts:
        return 0.0, 0.0
    x0, y0, x1, y1 = G.bbox(pts)
    return (x0 + x1) / 2, (y0 + y1) / 2


# ---------------------------------------------------------------------------
# Copiar / colar
# ---------------------------------------------------------------------------

def copy_selection(project: Project, uids) -> dict:
    """Área de transferência interna: dicionários dos elementos selecionados.
    Ligações só são copiadas se os dois nós também estiverem na seleção."""
    uids = set(uids)
    items = []
    skipped = 0
    for u in uids:
        e = project.get(u)
        if e is None:
            continue
        if e.COLLECTION == 'link' and not (e.start in uids and e.end in uids):
            skipped += 1
            continue
        items.append(e.to_dict())
    return {'items': items, 'skipped_links': skipped}


def paste(project: Project, clip: dict, dx: float, dy: float) -> list[Change]:
    remap = {d['uid']: new_uid() for d in clip.get('items', [])}
    taken: set[str] = set()
    out = []
    order = sorted(clip.get('items', []), key=lambda d: {'node': 0, 'link': 1}.get(
        element_from_dict(d).COLLECTION, 2))
    for d in order:
        d = copy.deepcopy(d)
        d['uid'] = remap[d['uid']]
        e = element_from_dict(d)
        if e.COLLECTION == 'node':
            e.x += dx
            e.y += dy
        elif e.COLLECTION == 'link':
            e.start, e.end = remap.get(e.start, e.start), remap.get(e.end, e.end)
            e.vertices = [[v[0] + dx, v[1] + dy] for v in e.vertices]
        elif e.COLLECTION == 'cad':
            e.points = [[p[0] + dx, p[1] + dy] for p in e.points]
        if e.COLLECTION in ('node', 'link'):
            e.name = project.network.unique_name(e.KIND, taken)
            taken.add(e.name)
        out.append((e.uid, None, e.to_dict()))
    return out


# ---------------------------------------------------------------------------
# Dividir tubulação
# ---------------------------------------------------------------------------

def _node_elevation(n):
    if hasattr(n, 'elevation'):
        return n.elevation
    if getattr(n, 'ground_elevation', None) is not None:
        return n.ground_elevation
    return getattr(n, 'head', 0.0)


def split_pipe(project: Project, pipe_uid: str, x: float, y: float,
               junction: Junction | None = None) -> tuple[list[Change], Junction | None]:
    """Divide a tubulação no ponto mais próximo de (x, y), inserindo uma junção.
    A primeira parte mantém o uid original; a segunda é uma nova tubulação."""
    from ..cad import geometry as G
    net = project.network
    pipe = net.links.get(pipe_uid)
    if not isinstance(pipe, Pipe):
        return [], None
    pts = net.link_points(pipe)
    d, seg, q = G.polyline_distance((x, y), pts)
    total = G.polyline_length(pts)
    if total <= 0:
        return [], None
    part1 = pts[:seg + 1] + [q]
    frac = G.polyline_length(part1) / total
    if frac <= 1e-6 or frac >= 1 - 1e-6:
        return [], None
    a, b = net.nodes[pipe.start], net.nodes[pipe.end]
    if junction is None:
        junction = Junction(name=net.unique_name('junction'), x=q[0], y=q[1],
                            elevation=_node_elevation(a) + frac * (_node_elevation(b) -
                                                                   _node_elevation(a)))
    else:
        junction.x, junction.y = q
    before = pipe.to_dict()
    first = copy.deepcopy(before)
    first['end'] = junction.uid
    first['vertices'] = [list(v) for v in pts[1:seg + 1]]
    second = Pipe(**{k: copy.deepcopy(v) for k, v in before.items()
                     if k not in ('uid', 'kind', 'name', 'start', 'vertices')})
    second.name = net.unique_name('pipe', {junction.name})
    second.start = junction.uid
    second.end = pipe.end
    second.vertices = [list(v) for v in pts[seg + 1:-1]]
    if not pipe.auto_length:
        first['length'] = pipe.length * frac
        second.length = pipe.length * (1 - frac)
    changes = [(junction.uid, None, junction.to_dict()), (pipe.uid, before, first),
               (second.uid, None, second.to_dict())]
    return changes, junction


# ---------------------------------------------------------------------------
# Conversão de entidades CAD em tubulações
# ---------------------------------------------------------------------------

@dataclass
class ConversionPlan:
    changes: list = field(default_factory=list)
    n_pipes: int = 0
    n_new_nodes: int = 0
    n_reused_nodes: int = 0
    ambiguous: list = field(default_factory=list)   # mensagens
    ignored: int = 0


def cad_to_pipes(project: Project, cad_uids, tol: float, reuse_existing: bool = True,
                 per_segment: bool = False, diameter: float = 100.0,
                 roughness: float = 130.0, material: str = 'PVC',
                 elevation: float = 0.0, existing: bool = False) -> ConversionPlan:
    """Planeja a conversão de linhas/polilinhas CAD em tubulações.

    Extremidades a menos de `tol` são unidas num único nó. Com `reuse_existing`,
    nós já existentes dentro da tolerância são reaproveitados; havendo mais de um,
    o caso é registrado como ambíguo (usa-se o mais próximo) para confirmação.
    """
    net = project.network
    plan = ConversionPlan()
    new_nodes: list[Junction] = []
    taken: set[str] = set()

    def node_at(p):
        for n in new_nodes:
            if math.dist((n.x, n.y), p) <= tol:
                return n.uid
        if reuse_existing:
            cand = connectivity.nearest_node(net, p[0], p[1], tol)
            if cand:
                if len(cand) > 1:
                    names = ', '.join(net.nodes[c].name for c in cand)
                    plan.ambiguous.append(f'Ponto ({p[0]:.2f}; {p[1]:.2f}): nós {names} '
                                          f'dentro da tolerância — usado {net.nodes[cand[0]].name}.')
                if cand[0] not in reused:
                    reused.add(cand[0])
                return cand[0]
        j = Junction(name=net.unique_name('junction', taken), x=p[0], y=p[1],
                     elevation=elevation)
        taken.add(j.name)
        new_nodes.append(j)
        return j.uid

    reused: set[str] = set()
    pipes = []
    for uid in cad_uids:
        e = project.cad.get(uid)
        if e is None or e.geom not in ('line', 'polyline') or len(e.points) < 2:
            plan.ignored += 1
            continue
        pts = [tuple(p[:2]) for p in e.points]
        if e.closed:
            pts.append(pts[0])
        chains = [[pts[i], pts[i + 1]] for i in range(len(pts) - 1)] if per_segment else [pts]
        for chain in chains:
            a, b = node_at(chain[0]), node_at(chain[-1])
            if a == b:
                plan.ignored += 1
                continue
            p = Pipe(name=net.unique_name('pipe', taken), start=a, end=b,
                     vertices=[list(v) for v in chain[1:-1]], diameter=diameter,
                     roughness=roughness, material=material, fixed_in_optimization=existing)
            taken.add(p.name)
            pipes.append(p)
    plan.changes = add(new_nodes) + add(pipes)
    plan.n_pipes = len(pipes)
    plan.n_new_nodes = len(new_nodes)
    plan.n_reused_nodes = len(reused)
    return plan
