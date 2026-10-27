"""Ferramentas interativas do canvas. Trabalham em coordenadas do MODELO.

Cada ferramenta gera alterações via hydraulics.editing e as envia ao controlador
(uma operação = um passo de desfazer).
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath
from PySide6.QtWidgets import QInputDialog, QMessageBox

from ..hydraulics import editing
from ..hydraulics.models import (CadEntity, Junction, Reservoir, Tank, Pipe, Pump, Valve,
                                 KIND_LABELS)
from . import geometry as G
from .items import cosmetic_pen

PREVIEW = '#0078d7'


class Tool:
    name = ''
    cursor = Qt.CrossCursor

    def __init__(self, canvas):
        self.c = canvas
        self.last = None

    @property
    def ctrl(self):
        return self.c.ctrl

    @property
    def project(self):
        return self.c.project

    def prompt(self) -> str:
        return ''

    def say(self, msg):
        self.c.statusMessage.emit(msg)

    def press(self, x, y, ev):
        if ev is None or ev.button() == Qt.LeftButton:
            self.point(x, y, ev)
        elif ev.button() == Qt.RightButton:
            self.finish()

    def point(self, x, y, ev):
        pass

    def move(self, x, y, ev):
        pass

    def release(self, x, y, ev):
        pass

    def double(self, x, y, ev):
        pass

    def feed(self, x, y):
        self.point(x, y, None)

    def key(self, ev) -> bool:
        if ev.key() == Qt.Key_Escape:
            self.cancel()
            self.say(self.prompt())
            return True
        if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.finish()
            return True
        return False

    def finish(self):
        self.cancel()

    def cancel(self):
        self.last = None

    def snap_extra(self):
        return []

    def snap_exclude(self):
        """Elementos ignorados pelo snap (ex.: os que estão sendo arrastados)."""
        return None

    def paint(self, painter):
        pass

    # utilitários de desenho de pré-visualização
    def _poly(self, painter, pts, color=PREVIEW, dash=True):
        if len(pts) < 2:
            return
        path = QPainterPath(self.c.m2s(*pts[0]))
        for p in pts[1:]:
            path.lineTo(self.c.m2s(*p))
        painter.setPen(cosmetic_pen(color, 1.2, Qt.DashLine if dash else Qt.SolidLine))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)


# ---------------------------------------------------------------------------
# Seleção, movimentação, pan
# ---------------------------------------------------------------------------

class SelectTool(Tool):
    name = 'Selecionar'
    cursor = Qt.ArrowCursor

    def __init__(self, canvas):
        super().__init__(canvas)
        self.mode = None
        self.start = None
        self.cur = None
        self.moved = False

    def prompt(self):
        return ('Clique para selecionar (Shift/Ctrl: adicionar). Arraste: janela (→) ou '
                'captura (←). Arraste um item selecionado para mover.')

    def press(self, x, y, ev):
        if ev is not None and ev.button() != Qt.LeftButton:
            return
        raw = self.c.view2model(ev.position().toPoint()) if ev is not None else (x, y)
        uid = self.c.pick(*raw)
        add = ev is not None and bool(ev.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier))
        sel = list(self.ctrl.selection)
        if uid and uid in sel and not add:
            self.mode = 'move'
            self.start = (x, y)
            self.cur = (x, y)
            self.moved = False
            self.merge_target = None
            return
        if uid:
            if add:
                sel = [u for u in sel if u != uid] if uid in sel else sel + [uid]
            else:
                sel = [uid]
            self.ctrl.set_selection(sel, 'canvas')
            self.mode = None
            return
        self.mode = 'window'
        self.start = raw
        self.cur = raw
        self._add = add

    def move(self, x, y, ev):
        if self.mode == 'move':
            self.cur = (x, y)
            self.moved = math.dist(self.start, self.cur) > 0
            self.merge_target = self._merge_target(x, y) if self.moved else None
        elif self.mode == 'window':
            self.cur = self.c.view2model(ev.position().toPoint()) if ev is not None else (x, y)

    def _moving_node(self):
        nodes = [u for u in self.ctrl.selection if u in self.project.network.nodes]
        return nodes[0] if len(nodes) == 1 else None

    def _merge_target(self, x, y):
        """Nó sob o cursor onde o nó arrastado pode ser unido (ou None)."""
        moving = self._moving_node()
        if moving is None:
            return None
        sel = set(self.ctrl.selection)
        r = self.c.snap_result
        net = self.project.network
        if r is not None and r.kind == 'node' and r.uid in net.nodes and r.uid not in sel:
            return r.uid
        from ..hydraulics.connectivity import nearest_node
        cand = nearest_node(net, x, y, self.c.px(7), exclude=sel)
        return cand[0] if cand else None

    def _merge(self, src, dst):
        net = self.project.network
        a, b = net.nodes[src], net.nodes[dst]
        plan = editing.merge_nodes(self.project, src, dst)
        lines = [f"Unir o nó '{a.name}' ao nó '{b.name}'?", '',
                 f"• '{b.name}' é mantido como está (posição, cota, demanda e demais dados).",
                 f"• {len(plan.moved_links)} ligação(ões) de '{a.name}' passam para "
                 f"'{b.name}': {', '.join(plan.moved_links) or '—'}.",
                 f"• '{a.name}' é excluído."]
        if plan.lost_demand:
            lines.append(f"• A demanda de '{a.name}' ({plan.lost_demand:.4g} L/s) é descartada.")
        if plan.removed_links:
            lines.append(f"• Ligação(ões) entre os dois nós excluída(s): "
                         f"{', '.join(plan.removed_links)}.")
        if plan.parallel:
            lines.append('• Atenção: ficarão ligações paralelas: ' +
                         '; '.join(f'{x} e {y}' for x, y in plan.parallel) + '.')
        if QMessageBox.question(self.c, 'Unir nós', '\n'.join(lines),
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.Yes) != QMessageBox.Yes:
            self.say('União cancelada; nada foi alterado.')
            return
        self.ctrl.apply(plan.changes, f"Unir nó {a.name} a {b.name}")
        self.ctrl.set_selection([dst], 'canvas')
        self.say(f"Nó '{a.name}' unido a '{b.name}' ({len(plan.moved_links)} ligação(ões) "
                 'transferida(s)). Ctrl+Z desfaz.')

    def snap_exclude(self):
        return set(self.ctrl.selection) if self.mode == 'move' else None

    def release(self, x, y, ev):
        if self.mode == 'move' and self.moved:
            target = self._merge_target(x, y)
            if target is not None:
                self.mode = None
                self.merge_target = None
                self._merge(self._moving_node(), target)
                return
            dx, dy = self.cur[0] - self.start[0], self.cur[1] - self.start[1]
            self.ctrl.apply(editing.move(self.project, self.ctrl.selection, dx, dy), 'Mover')
            self.say(f'Deslocamento: ΔX = {dx:.3f} m, ΔY = {dy:.3f} m')
        elif self.mode == 'window' and self.start and self.cur:
            if math.dist(self.start, self.cur) < self.c.px(3):
                if not self._add:
                    self.ctrl.set_selection([], 'canvas')
            else:
                crossing = self.cur[0] < self.start[0]
                from . import selection as SEL
                uids = SEL.window(self.project, self.c.index, *self.start, *self.cur, crossing)
                if self._add:
                    uids = list(self.ctrl.selection) + uids
                self.ctrl.set_selection(uids, 'canvas')
        self.mode = None

    def snap_extra(self):
        return []

    def cancel(self):
        self.mode = None

    def key(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.ctrl.set_selection([], 'canvas')
            return True
        return False

    def paint(self, painter):
        if self.mode == 'window' and self.start and self.cur:
            a, b = self.c.m2s(*self.start), self.c.m2s(*self.cur)
            crossing = self.cur[0] < self.start[0]
            painter.setPen(cosmetic_pen('#1e7b1e' if crossing else '#0050c8', 1,
                                        Qt.DashLine if crossing else Qt.SolidLine))
            painter.setBrush(QColor(30, 160, 30, 30) if crossing else QColor(0, 80, 200, 30))
            painter.drawRect(QRectF(a, b).normalized())
        elif self.mode == 'move' and self.moved:
            if getattr(self, 'merge_target', None):
                t = self.project.network.nodes.get(self.merge_target)
                if t is not None:
                    p = self.c.m2s(t.x, t.y)
                    d = self.c.px(9)
                    painter.setPen(cosmetic_pen('#e000e0', 2.0))
                    painter.setBrush(Qt.NoBrush)
                    painter.drawEllipse(p, d, d)
                    painter.save()
                    painter.translate(p)
                    k = 1 / self.c.ppm
                    painter.scale(k, k)
                    painter.drawText(QPointF(12, -12), f'unir a {t.name}')
                    painter.restore()
            dx, dy = self.cur[0] - self.start[0], self.cur[1] - self.start[1]
            for u in self.ctrl.selection[:300]:
                e = self.project.get(u)
                if e is None:
                    continue
                pts = [(p[0] + dx, p[1] + dy) for p in G.element_polyline(self.project, e)]
                if len(pts) == 1:
                    p = self.c.m2s(*pts[0])
                    d = self.c.px(4)
                    painter.setPen(cosmetic_pen(PREVIEW, 1.2))
                    painter.drawEllipse(p, d, d)
                else:
                    self._poly(painter, pts)


class PanTool(Tool):
    name = 'Pan'
    cursor = Qt.OpenHandCursor

    def prompt(self):
        return 'Arraste para deslocar a vista (o botão do meio funciona em qualquer ferramenta).'

    def press(self, x, y, ev):
        if ev is not None:
            self._p = ev.position()

    def move(self, x, y, ev):
        if ev is not None and ev.buttons() & Qt.LeftButton and getattr(self, '_p', None):
            d = ev.position() - self._p
            self._p = ev.position()
            self.c.translate(d.x() / self.c.ppm, d.y() / self.c.ppm)

    def release(self, x, y, ev):
        self._p = None


# ---------------------------------------------------------------------------
# Elementos hidráulicos
# ---------------------------------------------------------------------------

def _ask_split(canvas, pipe) -> bool:
    return QMessageBox.question(
        canvas, 'Conectar à tubulação',
        f"O ponto está sobre a tubulação '{pipe.name}'.\n\nDividir a tubulação e conectar "
        "neste ponto?\n(Não: o novo elemento NÃO será conectado a ela.)",
        QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes


class NodeTool(Tool):
    CLASSES = {'junction': Junction, 'reservoir': Reservoir, 'tank': Tank}

    def __init__(self, canvas, kind):
        super().__init__(canvas)
        self.kind = kind
        self.name = 'Inserir ' + KIND_LABELS[kind].lower()

    def prompt(self):
        return f'Clique para inserir {KIND_LABELS[self.kind].lower()} (ou digite X,Y).'

    def point(self, x, y, ev):
        net = self.project.network
        tol = self.c.px(6)
        if self.c.pick(x, y, only={'node'}, tol_px=6):
            self.say('Já existe um nó neste ponto.')
            return
        e = self.CLASSES[self.kind](name=net.unique_name(self.kind), x=x, y=y)
        pipe_uid = self.c.pick(x, y, only={'link'}, tol_px=6) if self.kind == 'junction' else None
        pipe = net.links.get(pipe_uid) if pipe_uid else None
        if isinstance(pipe, Pipe) and _ask_split(self.c, pipe):
            changes, _ = editing.split_pipe(self.project, pipe.uid, x, y, junction=e)
            self.ctrl.apply(changes, f'Inserir {e.name} dividindo {pipe.name}')
        else:
            self.ctrl.add_elements([e], f'Inserir {e.name}')
        del tol
        self.say(f'{KIND_LABELS[self.kind]} {e.name} inserido em ({e.x:.3f}; {e.y:.3f}).')


class LinkTool(Tool):
    """Tubulação (com vértices), bomba ou válvula entre dois nós."""

    def __init__(self, canvas, kind):
        super().__init__(canvas)
        self.kind = kind
        self.name = 'Desenhar ' + KIND_LABELS[kind].lower()
        self.cancel()

    def cancel(self):
        self.start_uid = None
        self.start_new = None       # Junction ainda não gravada
        self.vertices = []
        self.cur = None
        self.last = None

    def prompt(self):
        if self.start_uid is None and self.start_new is None:
            return f'{KIND_LABELS[self.kind]}: clique no nó inicial (ou em vazio para criar junção).'
        if self.kind == 'pipe':
            return ('Clique para vértices; clique num nó para terminar; duplo clique/Enter '
                    'termina criando junção; Esc cancela.')
        return 'Clique no nó final (ou em vazio para criar junção).'

    def _start_point(self):
        if self.start_new is not None:
            return (self.start_new.x, self.start_new.y)
        n = self.project.network.nodes.get(self.start_uid)
        return (n.x, n.y) if n else None

    def _resolve(self, x, y):
        """('node', uid) | ('split', pipe) | ('new', None)."""
        uid = self.c.pick(x, y, only={'node'}, tol_px=7)
        if uid:
            return 'node', uid
        luid = self.c.pick(x, y, only={'link'}, tol_px=5)
        l = self.project.network.links.get(luid) if luid else None
        if isinstance(l, Pipe):
            return 'split', l
        return 'new', None

    def point(self, x, y, ev):
        net = self.project.network
        kind, ref = self._resolve(x, y)
        if self.start_uid is None and self.start_new is None:
            if kind == 'node':
                self.start_uid = ref
            elif kind == 'split' and _ask_split(self.c, ref):
                changes, j = editing.split_pipe(self.project, ref.uid, x, y)
                self.ctrl.apply(changes, f'Dividir {ref.name}')
                self.start_uid = j.uid
            elif self.project.settings.auto_create_junction:
                self.start_new = Junction(name=net.unique_name('junction'), x=x, y=y)
            else:
                self.say('Clique sobre um nó existente.')
                return
            self.last = (x, y)
            self.say(self.prompt())
            return
        if kind == 'node':
            if ref == self.start_uid:
                self.say('O nó final deve ser diferente do inicial.')
                return
            self._commit(end_uid=ref)
        elif kind == 'split' and _ask_split(self.c, ref):
            self._commit(split=(ref, x, y))
        elif self.kind == 'pipe':
            self.vertices.append([x, y])
            self.last = (x, y)
        else:
            self._commit(new_end=(x, y))

    def double(self, x, y, ev):
        if self.kind == 'pipe' and (self.start_uid or self.start_new):
            if self.vertices and math.dist(self.vertices[-1], (x, y)) < self.c.px(4):
                self.vertices.pop()
            self._commit(new_end=(x, y))

    def finish(self):
        if self.kind == 'pipe' and self.vertices:
            end = self.vertices.pop()
            self._commit(new_end=tuple(end))
        else:
            self.cancel()
            self.say(self.prompt())

    def _commit(self, end_uid=None, new_end=None, split=None):
        net = self.project.network
        changes = []
        taken = set()
        if self.start_new is not None:
            changes += editing.add([self.start_new])
            start = self.start_new.uid
            taken.add(self.start_new.name)
        else:
            start = self.start_uid
        if new_end is not None:
            if not self.project.settings.auto_create_junction:
                self.say('Termine sobre um nó existente (criação automática desligada).')
                return
            j = Junction(name=net.unique_name('junction', taken), x=new_end[0], y=new_end[1])
            taken.add(j.name)
            changes += editing.add([j])
            end_uid = j.uid
        elif split is not None:
            pipe, x, y = split
            ch, j = editing.split_pipe(self.project, pipe.uid, x, y)
            if j is None:
                self.say('Não foi possível dividir a tubulação nesse ponto.')
                return
            j.name = net.unique_name('junction', taken)
            ch[0] = (j.uid, None, j.to_dict())
            taken.add(j.name)
            changes += ch
            end_uid = j.uid
        cls = {'pipe': Pipe, 'pump': Pump, 'valve': Valve}[self.kind]
        link = cls(name=net.unique_name(self.kind, taken), start=start, end=end_uid,
                   vertices=[list(v) for v in self.vertices] if self.kind == 'pipe' else [])
        changes += editing.add([link])
        self.ctrl.apply(changes, f'Desenhar {link.name}')
        self.say(f'{KIND_LABELS[self.kind]} {link.name} criada.')
        # continua a partir do nó final (encadeamento, como no EPANET)
        self.cancel()
        if self.kind == 'pipe':
            self.start_uid = end_uid
            n = net.nodes.get(end_uid)
            self.last = (n.x, n.y) if n else None

    def move(self, x, y, ev):
        self.cur = (x, y)

    def snap_extra(self):
        return [('end', tuple(v)) for v in self.vertices]

    def paint(self, painter):
        s = self._start_point()
        if s is None or self.cur is None:
            return
        self._poly(painter, [s] + [tuple(v) for v in self.vertices] + [self.cur])
        if self.start_new is not None:
            p = self.c.m2s(*s)
            d = self.c.px(3.5)
            painter.setPen(cosmetic_pen(PREVIEW, 1.2))
            painter.drawEllipse(p, d, d)


class SplitPipeTool(Tool):
    name = 'Dividir tubulação'

    def prompt(self):
        return 'Clique sobre uma tubulação para dividi-la com uma nova junção.'

    def point(self, x, y, ev):
        uid = self.c.pick(x, y, only={'link'}, tol_px=6)
        pipe = self.project.network.links.get(uid) if uid else None
        if not isinstance(pipe, Pipe):
            self.say('Nenhuma tubulação neste ponto.')
            return
        changes, j = editing.split_pipe(self.project, pipe.uid, x, y)
        if j is None:
            self.say('Ponto coincide com uma extremidade da tubulação.')
            return
        self.ctrl.apply(changes, f'Dividir {pipe.name}')
        self.say(f'{pipe.name} dividida; junção {j.name} inserida.')


# ---------------------------------------------------------------------------
# Ferramentas geométricas
# ---------------------------------------------------------------------------

class CadTool(Tool):
    geom = 'line'
    min_points = 2

    def __init__(self, canvas):
        super().__init__(canvas)
        self.pts = []
        self.cur = None

    def cancel(self):
        self.pts = []
        self.cur = None
        self.last = None

    def layer(self):
        name = self.c.current_layer or '0'
        l = self.project.layer_by_name(name)
        if l is not None and (l.locked or l.reference):
            self.say(f"A camada atual '{name}' está bloqueada/é de referência. "
                     "Escolha outra no painel de camadas.")
            return None
        return name

    def emit(self, **kw):
        layer = self.layer()
        if layer is None:
            return False
        e = CadEntity(layer=layer, **kw)
        self.ctrl.add_elements([e], f'Desenhar {self.name.lower()}')
        return True

    def point(self, x, y, ev):
        self.pts.append((x, y))
        self.last = (x, y)
        self.on_point()

    def on_point(self):
        pass

    def move(self, x, y, ev):
        self.cur = (x, y)

    def snap_extra(self):
        return [('end', p) for p in self.pts]


class LineTool(CadTool):
    name = 'Linha'

    def prompt(self):
        return 'Linha: clique o primeiro ponto.' if not self.pts else \
            'Linha: próximo ponto (Esc/Enter termina).'

    def on_point(self):
        if len(self.pts) == 2:
            a, b = self.pts
            if self.emit(geom='line', points=[list(a), list(b)]):
                self.say(f'Linha: comprimento {math.dist(a, b):.3f} m.')
            self.pts = [b]

    def paint(self, painter):
        if self.pts and self.cur:
            self._poly(painter, [self.pts[-1], self.cur])


class PolylineTool(CadTool):
    name = 'Polilinha'

    def prompt(self):
        return 'Polilinha: clique os pontos; Enter/duplo clique/botão direito termina; C fecha.'

    def double(self, x, y, ev):
        self.finish()

    def finish(self, closed=False):
        pts = [p for i, p in enumerate(self.pts) if i == 0 or p != self.pts[i - 1]]
        if len(pts) >= 2:
            self.emit(geom='polyline', points=[list(p) for p in pts], closed=closed)
            self.say(f'Polilinha com {len(pts)} vértices, comprimento '
                     f'{G.polyline_length(pts + ([pts[0]] if closed else [])):.3f} m.')
        self.cancel()

    def key(self, ev):
        if ev.key() == Qt.Key_C and len(self.pts) >= 3:
            self.finish(closed=True)
            return True
        return super().key(ev)

    def paint(self, painter):
        if self.pts:
            self._poly(painter, self.pts + ([self.cur] if self.cur else []))


class RectTool(CadTool):
    name = 'Retângulo'

    def prompt(self):
        return 'Retângulo: clique dois cantos opostos.'

    def on_point(self):
        if len(self.pts) == 2:
            (x0, y0), (x1, y1) = self.pts
            self.emit(geom='polyline', closed=True,
                      points=[[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
            self.cancel()

    def paint(self, painter):
        if self.pts and self.cur:
            (x0, y0), (x1, y1) = self.pts[0], self.cur
            self._poly(painter, [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)])


class CircleTool(CadTool):
    name = 'Círculo'

    def prompt(self):
        return 'Círculo: clique o centro e depois um ponto do raio (ou digite @r,0).'

    def on_point(self):
        if len(self.pts) == 2:
            c, p = self.pts
            r = math.dist(c, p)
            if r > 0:
                self.emit(geom='circle', points=[list(c)], radius=r)
                self.say(f'Círculo: raio {r:.3f} m.')
            self.cancel()

    def paint(self, painter):
        if self.pts and self.cur:
            r = math.dist(self.pts[0], self.cur)
            self._poly(painter, G.arc_points(*self.pts[0], r, 0, 360))


def circle_3p(a, b, c):
    ax, ay = a
    bx, by = b
    cx, cy = c
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) +
          (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) +
          (cx * cx + cy * cy) * (bx - ax)) / d
    return (ux, uy), math.dist((ux, uy), a)


def arc_from_3p(a, b, c):
    res = circle_3p(a, b, c)
    if res is None:
        return None
    (ux, uy), r = res
    ang = lambda p: math.degrees(math.atan2(p[1] - uy, p[0] - ux)) % 360  # noqa: E731
    a0, am, a1 = ang(a), ang(b), ang(c)
    ccw = (am - a0) % 360 < (a1 - a0) % 360
    if not ccw:
        a0, a1 = a1, a0
    return (ux, uy), r, a0, a1


class ArcTool(CadTool):
    name = 'Arco'

    def prompt(self):
        return 'Arco por 3 pontos: início, ponto intermediário, fim.'

    def on_point(self):
        if len(self.pts) == 3:
            res = arc_from_3p(*self.pts)
            if res:
                (cx, cy), r, a0, a1 = res
                self.emit(geom='arc', points=[[cx, cy]], radius=r, start_angle=a0, end_angle=a1)
            else:
                self.say('Pontos colineares: arco indefinido.')
            self.cancel()

    def paint(self, painter):
        if len(self.pts) == 1 and self.cur:
            self._poly(painter, [self.pts[0], self.cur])
        elif len(self.pts) == 2 and self.cur:
            res = arc_from_3p(self.pts[0], self.pts[1], self.cur)
            if res:
                (cx, cy), r, a0, a1 = res
                self._poly(painter, G.arc_points(cx, cy, r, a0, a1))


class TextTool(CadTool):
    name = 'Texto'

    def prompt(self):
        return 'Texto: clique o ponto de inserção.'

    def on_point(self):
        p = self.pts[0]
        self.cancel()
        text, ok = QInputDialog.getText(self.c, 'Texto', 'Conteúdo:')
        if not ok or not text:
            return
        h, ok = QInputDialog.getDouble(self.c, 'Texto', 'Altura (m):', 2.0, 0.01, 1e5, 2)
        if ok:
            self.emit(geom='text', points=[list(p)], text=text, height=h)


class DimensionTool(CadTool):
    name = 'Cota'

    def prompt(self):
        return 'Cota: clique os dois pontos medidos e depois a posição da linha de cota.'

    def _offset(self, p):
        (x1, y1), (x2, y2) = self.pts[:2]
        L = math.dist((x1, y1), (x2, y2)) or 1e-9
        nx, ny = -(y2 - y1) / L, (x2 - x1) / L
        return (p[0] - x1) * nx + (p[1] - y1) * ny

    def on_point(self):
        if len(self.pts) == 3:
            off = self._offset(self.pts[2])
            h = max(self.c.px(12), 0.01)
            self.emit(geom='dimension', points=[list(self.pts[0]), list(self.pts[1])],
                      offset=off, height=round(h, 3))
            self.say(f'Cota: {math.dist(self.pts[0], self.pts[1]):.3f} m.')
            self.cancel()

    def paint(self, painter):
        if len(self.pts) == 1 and self.cur:
            self._poly(painter, [self.pts[0], self.cur])
        elif len(self.pts) == 2 and self.cur:
            off = self._offset(self.cur)
            (x1, y1), (x2, y2) = self.pts
            L = math.dist((x1, y1), (x2, y2)) or 1e-9
            nx, ny = -(y2 - y1) / L * off, (x2 - x1) / L * off
            self._poly(painter, [(x1, y1), (x1 + nx, y1 + ny), (x2 + nx, y2 + ny), (x2, y2)])


class MeasureTool(CadTool):
    name = 'Medir'

    def prompt(self):
        return 'Medir: clique os pontos (distância parcial e acumulada). Esc reinicia.'

    def on_point(self):
        if len(self.pts) >= 2:
            a, b = self.pts[-2], self.pts[-1]
            d = math.dist(a, b)
            ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
            tot = G.polyline_length(self.pts)
            self.say(f'Distância: {d:.3f} m   Ângulo: {ang:.2f}°   ΔX: {b[0] - a[0]:.3f}   '
                     f'ΔY: {b[1] - a[1]:.3f}   Acumulado: {tot:.3f} m')

    def finish(self):
        self.cancel()

    def paint(self, painter):
        if self.pts:
            self._poly(painter, self.pts + ([self.cur] if self.cur else []), '#c00000', False)
            if self.cur:
                d = math.dist(self.pts[-1], self.cur)
                painter.setPen(cosmetic_pen('#c00000', 1))
                p = self.c.m2s(*self.cur)
                painter.save()
                painter.translate(p)
                k = 1 / self.c.ppm
                painter.scale(k, k)
                painter.drawText(QPointF(12, -8), f'{d:.3f} m')
                painter.restore()
