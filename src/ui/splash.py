"""Tela de abertura (splash screen) do HidroPy."""

from __future__ import annotations

import os

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QSplashScreen

CYAN = QColor('#0ABDDB')          # mesmo ciano do ícone
WIDTH, HEIGHT = 680, 380
DURATION_MS = 2000
LOGO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'resources',
                    'hidropy_logo.png')


def splash_pixmap(scale: float = 1.0) -> QPixmap:
    w, h = int(WIDTH * scale), int(HEIGHT * scale)
    pm = QPixmap(w, h)
    pm.fill(CYAN)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    s = scale
    # símbolo da rede (o ícone tem o mesmo fundo ciano, então se funde à tela)
    if os.path.exists(LOGO):
        logo = QPixmap(LOGO).scaled(int(165 * s), int(165 * s), Qt.KeepAspectRatio,
                                    Qt.SmoothTransformation)
        p.drawPixmap(int(48 * s), int((h - logo.height()) / 2 - 12 * s), logo)
    white = QColor('#FFFFFF')
    p.setPen(white)
    f = QFont('Segoe UI', 1)
    f.setPixelSize(int(76 * s))
    f.setBold(True)
    p.setFont(f)
    text_x = 240 * s
    p.drawText(QRectF(text_x, 100 * s, w - text_x - 30 * s, 100 * s),
               Qt.AlignLeft | Qt.AlignVCenter, 'HidroPy')
    f = QFont('Segoe UI', 1)
    f.setPixelSize(int(21 * s))
    p.setFont(f)
    p.drawText(QRectF(text_x + 4 * s, 196 * s, w - text_x - 30 * s, 40 * s),
               Qt.AlignLeft | Qt.AlignVCenter, 'simulador hidráulico baseado em python')
    # crédito discreto no canto inferior direito
    f = QFont('Segoe UI', 1)
    f.setPixelSize(int(12 * s))
    p.setFont(f)
    c = QColor(white)
    c.setAlpha(175)
    p.setPen(c)
    p.drawText(QRectF(0, h - 34 * s, w - 18 * s, 22 * s), Qt.AlignRight | Qt.AlignVCenter,
               'Criado por Caio Henrique')
    p.end()
    return pm


def show_splash(app) -> QSplashScreen:
    ratio = app.primaryScreen().devicePixelRatio() if app.primaryScreen() else 1.0
    pm = splash_pixmap(ratio)
    pm.setDevicePixelRatio(ratio)
    splash = QSplashScreen(pm, Qt.WindowStaysOnTopHint)
    splash.show()
    app.processEvents()
    return splash
