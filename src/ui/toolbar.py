"""Barras de ferramentas com ícones desenhados em código (sem arquivos externos)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QSize
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QStyle, QToolBar

BLUE = QColor('#1f5fbf')
DARK = QColor('#303030')


def _icon(draw) -> QIcon:
    pm = QPixmap(32, 32)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    draw(p)
    p.end()
    return QIcon(pm)


def _pen(p, color=None, w=2.2):
    p.setPen(QPen(color or DARK, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))


def icons(fg: QColor | None = None):
    global DARK
    if fg is not None:
        DARK = fg
    def junction(p):
        _pen(p, BLUE, 2)
        p.setBrush(QBrush(BLUE))
        p.drawEllipse(QPointF(16, 16), 6, 6)

    def reservoir(p):
        _pen(p, QColor('#1a7a1a'), 2)
        p.setBrush(QBrush(QColor('#bfe6bf')))
        p.drawRect(QRectF(5, 9, 22, 15))
        p.drawLine(QPointF(9, 14), QPointF(23, 14))

    def tank(p):
        _pen(p, QColor('#127a8a'), 2)
        p.setBrush(QBrush(QColor('#ffffff')))
        p.drawRect(QRectF(9, 4, 14, 24))
        p.setBrush(QBrush(QColor('#2c7bb6')))
        p.setPen(Qt.NoPen)
        p.drawRect(QRectF(10, 15, 12, 12))

    def pipe(p):
        _pen(p, BLUE, 3)
        p.drawLine(QPointF(4, 26), QPointF(28, 6))
        p.setBrush(QBrush(BLUE))
        p.drawEllipse(QPointF(4, 26), 2.5, 2.5)
        p.drawEllipse(QPointF(28, 6), 2.5, 2.5)

    def pump(p):
        _pen(p, QColor('#b01010'), 2)
        p.drawLine(QPointF(2, 16), QPointF(30, 16))
        p.setBrush(QBrush(QColor('#ffffff')))
        p.drawEllipse(QPointF(16, 16), 9, 9)
        p.setBrush(QBrush(QColor('#b01010')))
        p.drawPolygon(QPolygonF([QPointF(23, 16), QPointF(12, 10), QPointF(12, 22)]))

    def valve(p):
        _pen(p, QColor('#6a3d9a'), 2)
        p.drawLine(QPointF(2, 16), QPointF(30, 16))
        p.setBrush(QBrush(QColor('#6a3d9a')))
        p.drawPolygon(QPolygonF([QPointF(6, 8), QPointF(26, 24), QPointF(26, 8), QPointF(6, 24)]))

    def select(p):
        _pen(p, DARK, 1.8)
        p.setBrush(Qt.NoBrush)
        p.drawPolygon(QPolygonF([QPointF(8, 4), QPointF(8, 26), QPointF(13, 21), QPointF(17, 29),
                                 QPointF(20, 27), QPointF(16, 20), QPointF(23, 20)]))

    def pan(p):
        _pen(p, DARK, 2)
        for a, b in (((16, 3), (16, 29)), ((3, 16), (29, 16))):
            p.drawLine(QPointF(*a), QPointF(*b))
        for tri in (((16, 2), (12, 7), (20, 7)), ((16, 30), (12, 25), (20, 25)),
                    ((2, 16), (7, 12), (7, 20)), ((30, 16), (25, 12), (25, 20))):
            p.setBrush(QBrush(DARK))
            p.drawPolygon(QPolygonF([QPointF(*t) for t in tri]))

    def line(p):
        _pen(p)
        p.drawLine(QPointF(5, 27), QPointF(27, 5))

    def polyline(p):
        _pen(p)
        p.drawPolyline(QPolygonF([QPointF(4, 26), QPointF(12, 8), QPointF(20, 22),
                                  QPointF(28, 6)]))

    def rect(p):
        _pen(p)
        p.drawRect(QRectF(5, 8, 22, 16))

    def circle(p):
        _pen(p)
        p.drawEllipse(QPointF(16, 16), 11, 11)

    def arc(p):
        _pen(p)
        p.drawArc(QRectF(5, 7, 22, 22), 0 * 16, 180 * 16)

    def text(p):
        _pen(p)
        f = p.font()
        f.setPixelSize(22)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(0, 0, 32, 32), Qt.AlignCenter, 'A')

    def dimension(p):
        _pen(p, DARK, 1.6)
        p.drawLine(QPointF(4, 8), QPointF(4, 24))
        p.drawLine(QPointF(28, 8), QPointF(28, 24))
        p.drawLine(QPointF(4, 18), QPointF(28, 18))
        p.drawLine(QPointF(2, 20), QPointF(6, 16))
        p.drawLine(QPointF(26, 20), QPointF(30, 16))

    def measure(p):
        _pen(p, QColor('#b00000'), 2)
        p.drawLine(QPointF(4, 22), QPointF(28, 22))
        for x in range(4, 29, 6):
            p.drawLine(QPointF(x, 22), QPointF(x, 16 if (x - 4) % 12 == 0 else 19))

    def split(p):
        _pen(p, BLUE, 3)
        p.drawLine(QPointF(3, 16), QPointF(29, 16))
        p.setBrush(QBrush(QColor('#ff8c00')))
        _pen(p, QColor('#ff8c00'), 1)
        p.drawEllipse(QPointF(16, 16), 5, 5)

    def run(p):
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor('#1a8a1a')))
        p.drawPolygon(QPolygonF([QPointF(9, 5), QPointF(27, 16), QPointF(9, 27)]))

    def optimize(p):
        _pen(p, QColor('#b06000'), 2)
        p.drawPolyline(QPolygonF([QPointF(4, 6), QPointF(10, 18), QPointF(16, 22),
                                  QPointF(22, 25), QPointF(28, 26)]))
        p.setBrush(QBrush(QColor('#b06000')))
        p.drawEllipse(QPointF(28, 26), 3, 3)

    def results(p):
        for i, (h, c) in enumerate(((10, '#2c7bb6'), (18, '#90eb9d'), (24, '#f29e2e'),
                                    (14, '#d7191c'))):
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(c)))
            p.drawRect(QRectF(4 + i * 6.5, 28 - h, 5, h))

    def dxf_in(p):
        _pen(p, DARK, 1.6)
        p.drawRect(QRectF(4, 4, 18, 24))
        f = p.font()
        f.setPixelSize(8)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(4, 10, 18, 10), Qt.AlignCenter, 'DXF')
        _pen(p, QColor('#1a8a1a'), 2.5)
        p.drawLine(QPointF(30, 16), QPointF(20, 16))
        p.drawLine(QPointF(24, 12), QPointF(20, 16))
        p.drawLine(QPointF(24, 20), QPointF(20, 16))

    def dxf_out(p):
        _pen(p, DARK, 1.6)
        p.drawRect(QRectF(4, 4, 18, 24))
        f = p.font()
        f.setPixelSize(8)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(4, 10, 18, 10), Qt.AlignCenter, 'DXF')
        _pen(p, QColor('#b00000'), 2.5)
        p.drawLine(QPointF(18, 16), QPointF(30, 16))
        p.drawLine(QPointF(26, 12), QPointF(30, 16))
        p.drawLine(QPointF(26, 20), QPointF(30, 16))

    def sheet(p):
        _pen(p, QColor('#1d6f42'), 1.6)
        p.setBrush(QBrush(QColor('#e6f2ea')))
        p.drawRect(QRectF(4, 5, 24, 22))
        for y in (11, 16, 21):
            p.drawLine(QPointF(4, y), QPointF(28, y))
        p.drawLine(QPointF(12, 5), QPointF(12, 27))

    def validate(p):
        _pen(p, QColor('#1a8a1a'), 3.5)
        p.drawPolyline(QPolygonF([QPointF(5, 17), QPointF(13, 25), QPointF(27, 7)]))

    return {k: _icon(v) for k, v in locals().items() if callable(v) and k not in ('_icon', 'fg')}


def build_toolbars(win):
    a = win.a
    ic = icons(win.palette().windowText().color())
    st = win.style()
    std = {'new': QStyle.SP_FileIcon, 'open': QStyle.SP_DialogOpenButton,
           'save': QStyle.SP_DialogSaveButton, 'undo': QStyle.SP_ArrowBack,
           'redo': QStyle.SP_ArrowForward, 'fit': QStyle.SP_TitleBarMaxButton,
           'delete': QStyle.SP_TrashIcon}
    for k, sp in std.items():
        a[k].setIcon(st.standardIcon(sp))
    mapping = {'tool_select': 'select', 'tool_pan': 'pan', 'tool_line': 'line',
               'tool_polyline': 'polyline', 'tool_rect': 'rect', 'tool_circle': 'circle',
               'tool_arc': 'arc', 'tool_text': 'text', 'tool_dimension': 'dimension',
               'tool_measure': 'measure', 'tool_junction': 'junction',
               'tool_reservoir': 'reservoir', 'tool_tank': 'tank', 'tool_pipe': 'pipe',
               'tool_pump': 'pump', 'tool_valve': 'valve', 'tool_split': 'split',
               'simulate': 'run', 'optimize': 'optimize', 'results': 'results',
               'import_dxf': 'dxf_in', 'export_res': 'sheet', 'export_dxf': 'dxf_out', 'validate': 'validate'}
    for k, name in mapping.items():
        a[k].setIcon(ic[name])

    def bar(title, keys, name):
        tb = QToolBar(title, win)
        tb.setObjectName(name)
        tb.setIconSize(QSize(22, 22))
        for k in keys:
            if k is None:
                tb.addSeparator()
            else:
                tb.addAction(a[k])
        win.addToolBar(Qt.TopToolBarArea, tb)
        return tb
    bar('Arquivo', ['new', 'open', 'save', None, 'import_dxf', 'export_dxf', None, 'undo',
                    'redo', 'delete', 'fit'], 'tb_file')
    bar('Rede', ['tool_select', 'tool_pan', None, 'tool_pipe', 'tool_junction',
                 'tool_reservoir', 'tool_tank', 'tool_pump', 'tool_valve', 'tool_split'],
        'tb_net')
    bar('Desenho', ['tool_line', 'tool_polyline', 'tool_rect', 'tool_circle', 'tool_arc',
                    'tool_text', 'tool_dimension', 'tool_measure'], 'tb_cad')
    bar('Cálculo', ['validate', 'simulate', 'optimize', 'results', 'export_res'], 'tb_calc')
