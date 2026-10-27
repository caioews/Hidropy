"""Entrada de coordenadas precisas (estilo CAD).

Formatos aceitos (coordenadas do modelo, em metros):
    x,y          absoluto            (ex.: 350120.5,7400310)
    @dx,dy       relativo ao último ponto
    @d<ang       polar relativo (distância < ângulo em graus)
O separador decimal pode ser ponto; vírgula separa X de Y (ou use ';').
"""

from __future__ import annotations

import math
import re

from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QWidget

_NUM = r'[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?'
_ABS = re.compile(rf'^\s*({_NUM})\s*[,;\s]\s*({_NUM})\s*$')
_REL = re.compile(rf'^\s*@\s*({_NUM})\s*[,;\s]\s*({_NUM})\s*$')
_POL = re.compile(rf'^\s*@\s*({_NUM})\s*<\s*({_NUM})\s*$')


def parse_point(text: str, last: tuple | None):
    m = _ABS.match(text)
    if m:
        return float(m.group(1)), float(m.group(2))
    base = last or (0.0, 0.0)
    m = _REL.match(text)
    if m:
        return base[0] + float(m.group(1)), base[1] + float(m.group(2))
    m = _POL.match(text)
    if m:
        d, a = float(m.group(1)), math.radians(float(m.group(2)))
        return base[0] + d * math.cos(a), base[1] + d * math.sin(a)
    raise ValueError('Formato inválido. Use x,y  @dx,dy  ou  @dist<ângulo')


class CommandLine(QWidget):
    def __init__(self, canvas, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        h = QHBoxLayout(self)
        h.setContentsMargins(4, 0, 4, 0)
        h.addWidget(QLabel('Coordenada:'))
        self.edit = QLineEdit()
        self.edit.setPlaceholderText('x,y   @dx,dy   @dist<ângulo   — Enter envia o ponto à '
                                     'ferramenta ativa')
        self.edit.returnPressed.connect(self.submit)
        h.addWidget(self.edit, 1)
        self.msg = QLabel('')
        h.addWidget(self.msg, 2)

    def submit(self):
        text = self.edit.text()
        tool = self.canvas.tool
        last = getattr(tool, 'last', None) if tool else None
        try:
            x, y = parse_point(text, last)
        except ValueError as e:
            self.msg.setText(str(e))
            return
        self.edit.clear()
        if tool is None or tool.name in ('Selecionar', 'Pan'):
            self.canvas.center_on_model(x, y)
            self.msg.setText(f'Vista centralizada em ({x:.3f}; {y:.3f}).')
        else:
            self.canvas.feed_point(x, y)
            self.msg.setText(f'Ponto ({x:.3f}; {y:.3f}) enviado a "{tool.name}".')
