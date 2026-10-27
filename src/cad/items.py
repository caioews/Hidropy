"""Itens gráficos (QGraphicsItem). Só desenham — os dados vêm do modelo.

Coordenadas de cena = coordenadas do modelo deslocadas pela origem de exibição e
com o eixo Y invertido (ver CadCanvas.m2s / s2m).
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QPainterPath, QPen,
                           QPolygonF)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QGraphicsSimpleTextItem

from . import geometry as G

SELECT_COLOR = QColor('#ff8c00')
HIGHLIGHT_COLOR = QColor('#ff00ff')

Z_REF, Z_CAD, Z_LINK, Z_SYMBOL, Z_NODE, Z_LABEL = 0, 1, 10, 15, 20, 30


def cosmetic_pen(color, width=1.0, style=Qt.SolidLine):
    pen = QPen(QColor(color), width, style)
    pen.setCosmetic(True)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


class LabelItem(QGraphicsSimpleTextItem):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setZValue(Z_LABEL)
        f = QFont('Segoe UI', 8)
        self.setFont(f)
        self.setBrush(QBrush(QColor('#202020')))
        self.setAcceptedMouseButtons(Qt.NoButton)


class NodeItem(QGraphicsItem):
    """Símbolo de nó em tamanho fixo de tela."""

    def __init__(self, canvas, uid):
        super().__init__()
        self.canvas = canvas
        self.uid = uid
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setZValue(Z_NODE)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.label = LabelItem()
        canvas.scene().addItem(self.label)

    def boundingRect(self):
        return QRectF(-12, -14, 24, 28)

    def paint(self, painter, option, widget=None):
        e = self.canvas.project.network.nodes.get(self.uid)
        if e is None:
            return
        st = self.canvas.node_style(e)
        if not st['symbols'] and not st['selected'] and not st['thematic']:
            r = 2.0
        else:
            r = st['size']
        color = QColor(st['color'])
        pen = QPen(SELECT_COLOR if st['selected'] else color.darker(140), 1.6 if
                   st['selected'] else 1.0)
        painter.setPen(pen)
        if e.KIND == 'junction':
            painter.setBrush(QBrush(color))
            painter.drawEllipse(QPointF(0, 0), r, r)
        elif e.KIND == 'reservoir':
            painter.setBrush(QBrush(color.lighter(130)))
            painter.drawRect(QRectF(-r * 2, -r * 1.3, r * 4, r * 2.6))
            painter.setPen(QPen(color.darker(160), 1))
            painter.drawLine(QPointF(-r * 1.4, -r * 0.3), QPointF(r * 1.4, -r * 0.3))
            painter.drawLine(QPointF(-r * 1.0, r * 0.4), QPointF(r * 1.0, r * 0.4))
        elif e.KIND == 'tank':
            rect = QRectF(-r * 1.4, -r * 2.2, r * 2.8, r * 4.4)
            painter.setBrush(QBrush(QColor('#ffffff')))
            painter.drawRect(rect)
            frac = self.canvas.tank_fraction(self.uid)
            if frac is not None:
                h = rect.height() * max(0.0, min(1.0, frac))
                painter.setBrush(QBrush(QColor('#2c7bb6')))
                painter.setPen(Qt.NoPen)
                painter.drawRect(QRectF(rect.left(), rect.bottom() - h, rect.width(), h))
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(rect)
            else:
                painter.setBrush(QBrush(color.lighter(120)))
                painter.drawRect(rect)
        if st['highlight']:
            painter.setPen(QPen(HIGHLIGHT_COLOR, 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPointF(0, 0), r + 4, r + 4)


class SymbolItem(QGraphicsItem):
    """Símbolo de bomba/válvula no ponto médio da ligação (tamanho de tela)."""

    def __init__(self, kind, parent):
        super().__init__(parent)
        self.kind = kind
        self.color = QColor('#000000')
        self.selected = False
        self.text = ''
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setZValue(Z_SYMBOL)
        self.setAcceptedMouseButtons(Qt.NoButton)

    def boundingRect(self):
        return QRectF(-10, -10, 20, 20)

    def paint(self, painter, option, widget=None):
        pen = QPen(SELECT_COLOR if self.selected else self.color, 1.4)
        painter.setPen(pen)
        painter.setBrush(QBrush(QColor('#ffffff')))
        if self.kind == 'pump':
            painter.drawEllipse(QPointF(0, 0), 7, 7)
            painter.setBrush(QBrush(pen.color()))
            painter.drawPolygon(QPolygonF([QPointF(6, 0), QPointF(-4, -5), QPointF(-4, 5)]))
        elif self.kind == 'valve':
            painter.setBrush(QBrush(pen.color()))
            painter.drawPolygon(QPolygonF([QPointF(-8, -5), QPointF(8, 5), QPointF(8, -5),
                                           QPointF(-8, 5)]))
        elif self.kind == 'cv':
            painter.drawLine(QPointF(-4, -5), QPointF(4, 0))
            painter.drawLine(QPointF(4, 0), QPointF(-4, 5))


class ArrowItem(QGraphicsItem):
    def __init__(self, parent):
        super().__init__(parent)
        self.color = QColor('#000000')
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setZValue(Z_SYMBOL)
        self.setAcceptedMouseButtons(Qt.NoButton)

    def boundingRect(self):
        return QRectF(-8, -8, 16, 16)

    def paint(self, painter, option, widget=None):
        painter.setPen(QPen(self.color.darker(130), 1))
        painter.setBrush(QBrush(self.color))
        painter.drawPolygon(QPolygonF([QPointF(7, 0), QPointF(-5, -4.5), QPointF(-2, 0),
                                       QPointF(-5, 4.5)]))


class LinkItem(QGraphicsPathItem):
    def __init__(self, canvas, uid):
        super().__init__()
        self.canvas = canvas
        self.uid = uid
        self.setZValue(Z_LINK)
        self.setAcceptedMouseButtons(Qt.NoButton)
        e = canvas.project.network.links.get(uid)
        self.symbol = SymbolItem(e.KIND if e is not None else 'pipe', self)
        self.arrow = ArrowItem(self)
        self.label = LabelItem()
        canvas.scene().addItem(self.label)

    def refresh(self):
        c = self.canvas
        e = c.project.network.links.get(self.uid)
        if e is None:
            return
        pts = c.project.network.link_points(e)
        path = QPainterPath()
        if pts:
            path.moveTo(c.m2s(*pts[0]))
            for p in pts[1:]:
                path.lineTo(c.m2s(*p))
        self.setPath(path)
        st = c.link_style(e)
        pen = cosmetic_pen(SELECT_COLOR if st['selected'] else st['color'], st['width'],
                           Qt.DotLine if e.status == 'Closed' else Qt.SolidLine)
        if getattr(e, 'existing', False):
            # trecho existente (executado): tracejado
            pen.setCapStyle(Qt.FlatCap)
            pen.setDashPattern([5, 3] if e.status != 'Closed' else [5, 2, 1, 2])
        self.setPen(pen)
        (mx, my), ang = G.point_at_fraction(pts, 0.5) if len(pts) >= 2 else ((0, 0), 0)
        kind = e.KIND if e.KIND != 'pipe' else ('cv' if e.status == 'CV' else '')
        self.symbol.kind = kind
        self.symbol.setVisible(bool(kind) and st['symbols'])
        self.symbol.color = QColor(st['color'])
        self.symbol.selected = st['selected']
        self.symbol.setPos(c.m2s(mx, my))
        self.symbol.setRotation(-ang)
        self.symbol.update()
        sign = st['arrow']
        self.arrow.setVisible(bool(sign))
        if sign:
            (ax, ay), aang = G.point_at_fraction(pts, 0.35 if kind else 0.5)
            self.arrow.color = QColor(st['color'])
            self.arrow.setPos(c.m2s(ax, ay))
            self.arrow.setRotation(-aang + (180 if sign < 0 else 0))
            self.arrow.update()


class CadItem(QGraphicsPathItem):
    """Linha, polilinha, círculo, arco ou ponto."""

    def __init__(self, canvas, uid):
        super().__init__()
        self.canvas = canvas
        self.uid = uid
        self.setAcceptedMouseButtons(Qt.NoButton)

    def refresh(self):
        c = self.canvas
        e = c.project.cad.get(self.uid)
        if e is None:
            return
        path = QPainterPath()
        if e.geom == 'point':
            p = c.m2s(*e.points[0][:2])
            path.addEllipse(p, 0.25, 0.25)
        else:
            pts = G.cad_polyline(e)
            if pts:
                path.moveTo(c.m2s(*pts[0]))
                for p in pts[1:]:
                    path.lineTo(c.m2s(*p))
        self.setPath(path)
        st = c.cad_style(e)
        self.setPen(cosmetic_pen(SELECT_COLOR if st['selected'] else st['color'], st['width'],
                                 Qt.DashLine if st['selected'] else Qt.SolidLine))
        self.setZValue(Z_REF if st['reference'] else Z_CAD)


class CadTextItem(QGraphicsItem):
    BASE = 100.0

    def __init__(self, canvas, uid):
        super().__init__()
        self.canvas = canvas
        self.uid = uid
        self.font = QFont('Arial')
        self.font.setPixelSize(int(self.BASE))
        self.setAcceptedMouseButtons(Qt.NoButton)
        self._rect = QRectF()

    def refresh(self):
        self.prepareGeometryChange()
        e = self.canvas.project.cad.get(self.uid)
        if e is None:
            return
        fm = QFontMetricsF(self.font)
        k = (e.height or 1.0) / fm.capHeight() if fm.capHeight() else 0.01
        w = fm.horizontalAdvance(e.text or ' ')
        self._k = k
        self._rect = QRectF(0, -fm.ascent(), w, fm.height())
        self.setPos(self.canvas.m2s(*e.points[0][:2]))
        self.setRotation(-e.rotation)
        self.setScale(k)
        st = self.canvas.cad_style(e)
        self._color = SELECT_COLOR if st['selected'] else QColor(st['color'])
        self.setZValue(Z_REF if st['reference'] else Z_CAD)
        self.update()

    def boundingRect(self):
        return self._rect

    def paint(self, painter, option, widget=None):
        e = self.canvas.project.cad.get(self.uid)
        if e is None:
            return
        painter.setFont(self.font)
        painter.setPen(QPen(self._color))
        painter.drawText(QPointF(0, 0), e.text)


class CadDimensionItem(QGraphicsItem):
    """Cota alinhada entre dois pontos, com deslocamento."""

    def __init__(self, canvas, uid):
        super().__init__()
        self.canvas = canvas
        self.uid = uid
        self.setAcceptedMouseButtons(Qt.NoButton)
        self._rect = QRectF()

    def _geom(self, e):
        (x1, y1), (x2, y2) = e.points[0][:2], e.points[1][:2]
        L = math.dist((x1, y1), (x2, y2)) or 1e-9
        nx, ny = -(y2 - y1) / L, (x2 - x1) / L
        o = e.offset
        a = (x1 + nx * o, y1 + ny * o)
        b = (x2 + nx * o, y2 + ny * o)
        return (x1, y1), (x2, y2), a, b, L

    def refresh(self):
        self.prepareGeometryChange()
        e = self.canvas.project.cad.get(self.uid)
        if e is None or len(e.points) < 2:
            return
        p1, p2, a, b, L = self._geom(e)
        c = self.canvas
        pts = [c.m2s(*p) for p in (p1, p2, a, b)]
        xs = [p.x() for p in pts]
        ys = [p.y() for p in pts]
        h = e.height * 2
        self._rect = QRectF(min(xs) - h, min(ys) - h, max(xs) - min(xs) + 2 * h,
                            max(ys) - min(ys) + 2 * h)
        st = c.cad_style(e)
        self._color = SELECT_COLOR if st['selected'] else QColor(st['color'])
        self.setZValue(Z_CAD)
        self.update()

    def boundingRect(self):
        return self._rect

    def paint(self, painter, option, widget=None):
        e = self.canvas.project.cad.get(self.uid)
        if e is None or len(e.points) < 2:
            return
        c = self.canvas
        p1, p2, a, b, L = self._geom(e)
        painter.setPen(cosmetic_pen(self._color, 1.0))
        P = [c.m2s(*p) for p in (p1, p2, a, b)]
        painter.drawLine(P[0], P[2])
        painter.drawLine(P[1], P[3])
        painter.drawLine(P[2], P[3])
        tick = e.height * 0.5
        for q in (P[2], P[3]):
            painter.drawLine(q + QPointF(-tick, tick), q + QPointF(tick, -tick))
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        if ang > 90 or ang < -90:
            ang -= 180
        painter.save()
        painter.translate(c.m2s(mx, my))
        painter.rotate(-ang)
        f = QFont('Arial')
        f.setPixelSize(100)
        fm = QFontMetricsF(f)
        k = e.height / fm.capHeight()
        painter.scale(k, k)
        painter.setFont(f)
        txt = e.text or f'{L:.2f}'
        painter.setPen(QPen(self._color))
        painter.drawText(QPointF(-fm.horizontalAdvance(txt) / 2, -fm.descent() - 20), txt)
        painter.restore()
