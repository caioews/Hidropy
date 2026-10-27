"""Canvas CAD (Qt Graphics View).

Separação de coordenadas:
    modelo (m, coordenadas reais/UTM)  <->  cena (modelo - origem, Y invertido)  <->  tela
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

from ..results import thematic_views as TV
from . import geometry as G
from . import selection as SEL
from . import snapping
from .items import (NodeItem, LinkItem, CadItem, CadTextItem, CadDimensionItem, cosmetic_pen,
                    SELECT_COLOR)
from .spatial import SpatialIndex

BG = QColor('#fbfbf8')


class CadCanvas(QGraphicsView):
    cursorMoved = Signal(float, float, str)
    zoomChanged = Signal(float)
    statusMessage = Signal(str)
    toolChanged = Signal(str)
    contextMenuRequested = Signal(object)    # posição global (QPoint)

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.ctrl = controller
        self.setScene(QGraphicsScene(self))
        self.scene().setItemIndexMethod(QGraphicsScene.NoIndex)
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setRenderHint(QPainter.TextAntialiasing, True)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.scene().setSceneRect(QRectF(-1e6, -1e6, 2e6, 2e6))
        self.items_by_uid: dict = {}
        self.index = SpatialIndex(self.project)
        self.tool = None
        self.current_layer = '0'
        self.theme = TV.ThemeConfig()
        self.theme_sim = None
        self.theme_opt = None
        self.theme_stale = False
        self._node_scale = None
        self._link_scale = None
        self._highlight: set = set()
        self._flow_sign: dict = {}
        self._pan_start = None
        self.snap_result = None
        self.cursor_model = (0.0, 0.0)
        self.preview_opt_uid = None      # resultado de otimização em pré-visualização
        self.ctrl.elementsChanged.connect(self.on_elements_changed)
        self.ctrl.projectReplaced.connect(self.rebuild)
        self.ctrl.selectionChanged.connect(self.on_selection_changed)
        self.ctrl.layersChanged.connect(self.on_layers_changed)
        self.ctrl.resultsChanged.connect(self.refresh_theme)
        self._label_timer = QTimer(self, singleShot=True, interval=50,
                                   timeout=self.refresh_all_styles)

    # ------------------------------------------------------------------ props
    @property
    def project(self):
        return self.ctrl.project

    @property
    def ppm(self) -> float:
        """pixels por metro."""
        return self.transform().m11() or 1.0

    def m2s(self, x, y) -> QPointF:
        ox, oy = self.project.display_origin
        return QPointF(x - ox, -(y - oy))

    def s2m(self, p: QPointF):
        ox, oy = self.project.display_origin
        return p.x() + ox, -p.y() + oy

    def view2model(self, pos):
        return self.s2m(self.mapToScene(pos))

    def px(self, n_pixels: float) -> float:
        """Converte pixels de tela em metros do modelo."""
        return n_pixels / self.ppm

    # ------------------------------------------------------------------ itens
    def rebuild(self):
        self.scene().clear()
        self.items_by_uid.clear()
        self.index = SpatialIndex(self.project)
        p = self.project
        if p.display_origin == (0.0, 0.0):
            b = p.bounds()
            if b:
                p.display_origin = (round(b[0], -2), round(b[1], -2))
        for e in list(p.cad.values()) + list(p.network.links.values()) + \
                list(p.network.nodes.values()):
            self._create_item(e)
        self.refresh_theme()
        self.fit_all()

    def _create_item(self, e):
        if e.COLLECTION == 'node':
            it = NodeItem(self, e.uid)
        elif e.COLLECTION == 'link':
            it = LinkItem(self, e.uid)
        elif e.COLLECTION == 'cad':
            if e.geom == 'text':
                it = CadTextItem(self, e.uid)
            elif e.geom == 'dimension':
                it = CadDimensionItem(self, e.uid)
            else:
                it = CadItem(self, e.uid)
        else:
            return None
        self.scene().addItem(it)
        self.items_by_uid[e.uid] = it
        self._refresh_item(it, e)
        return it

    def _remove_item(self, uid):
        it = self.items_by_uid.pop(uid, None)
        if it is None:
            return
        lab = getattr(it, 'label', None)
        if lab is not None:
            self.scene().removeItem(lab)
        self.scene().removeItem(it)

    def _refresh_item(self, it, e):
        vis = self.project.layer_visible(e.layer)
        it.setVisible(vis)
        if e.COLLECTION == 'node':
            it.setPos(self.m2s(e.x, e.y))
            it.update()
        else:
            it.refresh()
        lab = getattr(it, 'label', None)
        if lab is not None:
            text = self.label_text(e)
            lab.setText(text)
            lab.setVisible(vis and bool(text))
            if text:
                if e.COLLECTION == 'node':
                    lab.setPos(self.m2s(e.x, e.y))
                    lab.setTransform(lab.transform().fromTranslate(8, -18))
                else:
                    pts = self.project.network.link_points(e)
                    if len(pts) >= 2:
                        (mx, my), _ = G.point_at_fraction(pts, 0.5)
                        lab.setPos(self.m2s(mx, my))
                        lab.setTransform(lab.transform().fromTranslate(6, 2))

    def on_elements_changed(self, cs):
        p = self.project
        self.index.invalidate()
        for uid in cs.removed:
            self._remove_item(uid)
        touched_nodes = set()
        for uid in cs.added | cs.modified:
            e = p.get(uid)
            if e is None:
                continue
            it = self.items_by_uid.get(uid)
            if it is None or (e.COLLECTION == 'cad' and type(it).__name__ != {
                    'text': 'CadTextItem', 'dimension': 'CadDimensionItem'}.get(e.geom,
                                                                                 'CadItem')):
                if it is not None:
                    self._remove_item(uid)
                self._create_item(e)
            else:
                self._refresh_item(it, e)
            if e.COLLECTION == 'node':
                touched_nodes.add(uid)
        if touched_nodes:
            for l in p.network.links.values():
                if l.start in touched_nodes or l.end in touched_nodes:
                    it = self.items_by_uid.get(l.uid)
                    if it is not None:
                        self._refresh_item(it, l)
        self.refresh_theme()

    def on_layers_changed(self):
        self.index.invalidate()
        self.refresh_all_styles()

    def on_selection_changed(self, uids, source):
        self.refresh_all_styles()

    def refresh_all_styles(self):
        p = self.project
        for uid, it in self.items_by_uid.items():
            e = p.get(uid)
            if e is not None:
                self._refresh_item(it, e)
        self.viewport().update()

    # ------------------------------------------------------------------ estilos
    def _layer_color(self, e):
        l = self.project.layer_by_name(e.layer)
        return l.color if l else '#808080', (l.line_width if l else 1.0), bool(l and l.reference)

    def node_style(self, e):
        color, _, _ = self._layer_color(e)
        thematic = False
        if self._node_scale is not None:
            c = self._node_scale.color(e.uid)
            if c:
                color, thematic = c, True
            elif self.theme.node_var:
                color = '#b0b0b0'
        sel = e.uid in self.ctrl.selection
        return {'color': color, 'size': 5.0 if thematic else 3.6, 'selected': sel,
                'highlight': e.uid in self._highlight, 'thematic': thematic,
                'symbols': self.project.settings.show_symbols or e.KIND != 'junction'}

    def link_style(self, e):
        color, width, _ = self._layer_color(e)
        width = max(1.0, width * 1.6)
        if self._link_scale is not None:
            c = self._link_scale.color(e.uid)
            if c:
                color, width = c, 3.0
            elif self.theme.link_var:
                color = '#b8b8b8'
        if e.uid in self._highlight:
            color, width = '#ff00ff', 4.0
        arrow = 0
        if self.project.settings.show_flow_arrows:
            arrow = self._flow_sign.get(e.uid, 0)
        return {'color': color, 'width': width, 'selected': e.uid in self.ctrl.selection,
                'symbols': self.project.settings.show_symbols, 'arrow': arrow}

    def cad_style(self, e):
        color, width, ref = self._layer_color(e)
        if e.color:
            color = e.color
        return {'color': color, 'width': width, 'selected': e.uid in self.ctrl.selection,
                'reference': ref}

    def tank_fraction(self, uid):
        sim = self.theme_sim
        if not sim:
            return None
        d = sim.get('nodes', {}).get(uid)
        t = self.project.network.nodes.get(uid)
        if not d or t is None or 'level' not in d:
            return None
        lv = TV.value_at(d['level'], self.theme.time_index)
        if lv is None or t.max_level <= t.min_level:
            return None
        return (lv - t.min_level) / (t.max_level - t.min_level)

    def label_text(self, e) -> str:
        s = self.project.settings
        parts = []
        t = self.theme.time_index
        sim = self.theme_sim
        if e.COLLECTION == 'node':
            if s.show_node_labels:
                parts.append(e.name)
            if s.show_pressures and sim and e.KIND != 'reservoir':
                v = TV.value_at(sim.get('nodes', {}).get(e.uid, {}).get('pressure'), t)
                if v is not None:
                    parts.append(f'N={v:.2f} m' if e.KIND == 'tank' else f'{v:.2f} m')
        elif e.COLLECTION == 'link':
            if s.show_link_labels:
                parts.append(e.name)
            if s.show_diameters and hasattr(e, 'diameter'):
                parts.append(f'Ø{e.diameter:g}')
                if self.theme_opt and e.uid in self.theme_opt.get('pipes', {}):
                    d = self.theme_opt['pipes'][e.uid]['opt_diam_mm']
                    if abs(d - e.diameter) > 1e-6:
                        parts[-1] += f'→{d:g}'
            if sim:
                d = sim.get('links', {}).get(e.uid, {})
                if s.show_flows:
                    v = TV.value_at(d.get('flow'), t)
                    if v is not None:
                        parts.append(f'{v:.2f} L/s')
                if s.show_velocities:
                    v = TV.value_at(d.get('velocity'), t)
                    if v is not None:
                        parts.append(f'{abs(v):.2f} m/s')
        return '  '.join(parts)

    # ------------------------------------------------------------------ temas
    def set_theme(self, cfg: TV.ThemeConfig):
        self.theme = cfg
        self.refresh_theme()

    def theme_results(self):
        p = self.project
        sim = p.latest_result('simulation')
        opt = None
        if self.preview_opt_uid:
            opt = next((r for r in p.results('optimization') if r['uid'] == self.preview_opt_uid),
                       None)
        if opt is None:
            opt = p.latest_result('optimization')
        return sim, opt

    def refresh_theme(self):
        sim, opt = self.theme_results()
        self.theme_sim, self.theme_opt = sim, opt
        cfg = self.theme
        p = self.project
        self.theme_stale = False
        self._node_scale = self._link_scale = None
        self._highlight = set()
        if cfg.node_var:
            vals = TV.node_values(p, cfg.node_var, sim, opt, cfg.time_index)
            self._node_scale = TV.ColorScale(cfg.node_var, vals, cfg.node_breaks, cfg.classes)
        if cfg.link_var:
            vals = TV.link_values(p, cfg.link_var, sim, opt, cfg.time_index)
            self._link_scale = TV.ColorScale(cfg.link_var, vals, cfg.link_breaks, cfg.classes)
        used = []
        if cfg.node_var in TV.SIM_NODE or cfg.link_var in TV.SIM_LINK:
            used.append(sim)
        if cfg.node_var in TV.OPT_VARS or cfg.link_var in TV.OPT_VARS:
            used.append(opt)
        self.theme_stale = any(r is not None and not self.ctrl.is_current(r) for r in used)
        if cfg.highlight_limits and sim:
            o = p.sim_options
            t = cfg.time_index
            if cfg.node_var == 'pressure':
                for u, v in TV.node_values(p, 'pressure', sim, None, t).items():
                    n = p.network.nodes.get(u)
                    if n is not None and n.KIND == 'junction' and (
                            v < o.pressure_min or v > o.pressure_max):
                        self._highlight.add(u)
            if cfg.link_var == 'velocity':
                for u, v in TV.link_values(p, 'velocity', sim, None, t).items():
                    if v > o.velocity_max or (o.velocity_min > 0 and v < o.velocity_min):
                        self._highlight.add(u)
            if cfg.link_var == 'flow':
                self._highlight |= set(TV.violations(p, sim)['reverse'])
        if cfg.highlight_limits and opt and cfg.node_var == 'opt_p_min':
            self._highlight |= {u for u, d in opt.get('junctions', {}).items()
                                if not d.get('ok_pressure', True)}
        self._flow_sign = TV.flow_signs(sim, cfg.time_index) if sim else {}
        self._label_timer.start()

    def legends(self) -> list:
        out = []
        if self._node_scale is not None:
            out.append(self._node_scale.legend('Nós: ' + TV.NODE_VARS[self.theme.node_var],
                                               self.theme_stale))
        if self._link_scale is not None:
            out.append(self._link_scale.legend('Ligações: ' + TV.LINK_VARS[self.theme.link_var],
                                               self.theme_stale))
        return out

    # ------------------------------------------------------------------ vista
    def fit_all(self):
        b = self.project.bounds()
        if not b:
            self.resetTransform()
            self.scale_view(2.0)
            self.centerOn(self.m2s(*self.project.display_origin))
            return
        self.fit_model_rect(*b)

    def fit_model_rect(self, x0, y0, x1, y1, margin=0.08):
        w = max(x1 - x0, 1.0)
        h = max(y1 - y0, 1.0)
        # reserva espaço à direita para as legendas dos mapas temáticos
        legend_px = 240 if self.legends() else 0
        vw = max(self.viewport().width() - legend_px, 100)
        vh = max(self.viewport().height(), 100)
        s = min(vw / (w * (1 + 2 * margin)), vh / (h * (1 + 2 * margin)))
        self.resetTransform()
        self.scale_view(s)
        c = self.m2s((x0 + x1) / 2, (y0 + y1) / 2)
        self.centerOn(c.x() + legend_px / 2 / self.ppm, c.y())

    def scale_view(self, factor):
        new = min(1e3, max(1e-4, self.ppm * factor))
        factor = new / self.ppm
        if abs(factor - 1.0) < 1e-12:
            return
        self.scale(factor, factor)
        self.zoomChanged.emit(self.ppm)

    def zoom_to(self, uids):
        pts = []
        for u in uids:
            e = self.project.get(u)
            if e is not None:
                pts += G.element_polyline(self.project, e)
        if not pts:
            return
        x0, y0, x1, y1 = G.bbox(pts)
        pad = max(x1 - x0, y1 - y0, 20.0) * 0.5
        self.fit_model_rect(x0 - pad, y0 - pad, x1 + pad, y1 + pad, 0)

    def center_on_model(self, x, y):
        self.centerOn(self.m2s(x, y))

    def wheelEvent(self, ev):
        factor = 1.2 if ev.angleDelta().y() > 0 else 1 / 1.2
        before = self.mapToScene(ev.position().toPoint())
        self.scale_view(factor)
        after = self.mapToScene(ev.position().toPoint())
        d = after - before
        self.translate(d.x(), d.y())
        self.viewport().update()

    # ------------------------------------------------------------------ snap
    def snap_point(self, pos, exclude=None):
        x, y = self.view2model(pos)
        if exclude is None and self.tool is not None:
            exclude = self.tool.snap_exclude()
        tol = self.px(self.project.settings.snap_tolerance_px)
        extra = self.tool.snap_extra() if self.tool else []
        r = snapping.snap(self.project, self.index, x, y, tol, extra, exclude)
        self.snap_result = r
        return r

    def pick(self, x, y, only=None, tol_px=6):
        return SEL.pick(self.project, self.index, x, y, self.px(tol_px), only)

    # ------------------------------------------------------------------ ferramentas
    def set_tool(self, tool):
        if self.tool is not None:
            self.tool.cancel()
        self.tool = tool
        self.toolChanged.emit(tool.name if tool else '')
        self.statusMessage.emit(tool.prompt() if tool else '')
        self.setCursor(tool.cursor if tool else Qt.ArrowCursor)
        self.viewport().update()

    def feed_point(self, x, y):
        if self.tool is not None:
            self.tool.feed(x, y)
            self.viewport().update()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MiddleButton:
            self._pan_start = ev.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        self.setFocus()
        if self.tool is not None:
            r = self.snap_point(ev.position().toPoint())
            self.tool.press(r.x, r.y, ev)
            self.viewport().update()

    def mouseMoveEvent(self, ev):
        if self._pan_start is not None:
            d = ev.position() - self._pan_start
            self._pan_start = ev.position()
            self.translate(d.x() / self.ppm, d.y() / self.ppm)
            self.viewport().update()
            return
        r = self.snap_point(ev.position().toPoint())
        self.cursor_model = (r.x, r.y)
        self.cursorMoved.emit(r.x, r.y, snapping.SNAP_LABELS.get(r.kind, ''))
        if self.tool is not None:
            self.tool.move(r.x, r.y, ev)
        self.viewport().update()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MiddleButton and self._pan_start is not None:
            self._pan_start = None
            self.setCursor(self.tool.cursor if self.tool else Qt.ArrowCursor)
            return
        if self.tool is not None:
            r = self.snap_point(ev.position().toPoint())
            self.tool.release(r.x, r.y, ev)
            self.viewport().update()

    def contextMenuEvent(self, ev):
        # menu de contexto só na ferramenta de seleção (nas outras o botão direito termina)
        if self.tool is not None and self.tool.name == 'Selecionar':
            self.contextMenuRequested.emit(ev.globalPos())

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.MiddleButton:
            self.fit_all()
            return
        if self.tool is not None:
            r = self.snap_point(ev.position().toPoint())
            self.tool.double(r.x, r.y, ev)
            self.viewport().update()

    def keyPressEvent(self, ev):
        if self.tool is not None and self.tool.key(ev):
            self.viewport().update()
            return
        super().keyPressEvent(ev)

    # ------------------------------------------------------------------ desenho
    def drawBackground(self, painter, rect):
        painter.fillRect(rect, BG)
        s = self.project.settings
        if not s.grid_visible or s.grid_spacing <= 0:
            return
        g = s.grid_spacing
        while g * self.ppm < 8:
            g *= 5 if str(g)[0] == '2' else 2
        ox, oy = self.project.display_origin
        x0, y1m = self.s2m(rect.topLeft())
        x1, y0m = self.s2m(rect.bottomRight())
        kx0, kx1 = math.floor(x0 / g), math.ceil(x1 / g)
        ky0, ky1 = math.floor(y0m / g), math.ceil(y1m / g)
        if (kx1 - kx0) * (ky1 - ky0) > 200000:
            return
        minor = cosmetic_pen('#ececec', 1)
        major = cosmetic_pen('#dcdcdc', 1)
        for k in range(kx0, kx1 + 1):
            painter.setPen(major if k % 5 == 0 else minor)
            x = k * g - ox
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
        for k in range(ky0, ky1 + 1):
            painter.setPen(major if k % 5 == 0 else minor)
            y = -(k * g - oy)
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))

    def drawForeground(self, painter, rect):
        if self.tool is not None:
            painter.save()
            self.tool.paint(painter)
            painter.restore()
        r = self.snap_result
        if r is not None and r.kind not in ('free',):
            p = self.m2s(r.x, r.y)
            d = self.px(6)
            painter.setPen(cosmetic_pen('#00a000', 1.5))
            painter.setBrush(Qt.NoBrush)
            if r.kind == 'mid':
                painter.drawPolygon([p + QPointF(0, -d), p + QPointF(d, d), p + QPointF(-d, d)])
            elif r.kind == 'int':
                painter.drawLine(p + QPointF(-d, -d), p + QPointF(d, d))
                painter.drawLine(p + QPointF(-d, d), p + QPointF(d, -d))
            elif r.kind == 'center':
                painter.drawEllipse(p, d, d)
            elif r.kind == 'grid':
                painter.drawLine(p + QPointF(-d, 0), p + QPointF(d, 0))
                painter.drawLine(p + QPointF(0, -d), p + QPointF(0, d))
            else:
                painter.drawRect(QRectF(p.x() - d, p.y() - d, 2 * d, 2 * d))
        painter.save()
        painter.resetTransform()
        self._draw_scale_bar(painter)
        self._draw_legends(painter)
        painter.restore()

    def _draw_scale_bar(self, painter):
        target = 120 / self.ppm
        exp = 10 ** math.floor(math.log10(target)) if target > 0 else 1
        nice = exp
        for m in (1, 2, 5, 10):
            if m * exp <= target:
                nice = m * exp
        w = nice * self.ppm
        x, y = 16, self.viewport().height() - 22
        painter.setPen(QPen(QColor('#202020'), 1))
        painter.setBrush(QBrush(QColor('#202020')))
        painter.drawRect(QRectF(x, y, w / 2, 5))
        painter.setBrush(QBrush(QColor('#ffffff')))
        painter.drawRect(QRectF(x + w / 2, y, w / 2, 5))
        painter.setFont(QFont('Segoe UI', 8))
        label = f'{nice:g} m' if nice < 1000 else f'{nice / 1000:g} km'
        painter.drawText(QPointF(x, y - 4), '0')
        painter.drawText(QPointF(x + w - 10, y - 4), label)

    def _draw_legends(self, painter):
        legends = self.legends()
        if not legends:
            return
        painter.setFont(QFont('Segoe UI', 8))
        fm = painter.fontMetrics()
        x = self.viewport().width() - 230
        y = 10
        for lg in legends:
            lines = len(lg.entries) + (1 if lg.note else 0) + 1
            h = lines * 16 + 10
            painter.setPen(QPen(QColor('#a0a0a0')))
            painter.setBrush(QBrush(QColor(255, 255, 255, 230)))
            painter.drawRect(QRectF(x, y, 220, h))
            painter.setPen(QPen(QColor('#101010')))
            painter.drawText(QPointF(x + 8, y + 16), fm.elidedText(lg.title, Qt.ElideRight, 205))
            yy = y + 32
            for color, text in lg.entries:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(QColor(color)))
                painter.drawRect(QRectF(x + 10, yy - 9, 22, 9))
                painter.setPen(QPen(QColor('#101010')))
                painter.drawText(QPointF(x + 40, yy), text)
                yy += 16
            if lg.note:
                painter.setPen(QPen(QColor('#505050')))
                painter.drawText(QPointF(x + 10, yy), lg.note)
            y += h + 8

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.viewport().update()


def selection_color():
    return SELECT_COLOR
