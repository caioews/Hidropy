"""Ajuda: manual do usuário e janela Sobre."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QTextBrowser,
                               QVBoxLayout)

RESOURCES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'resources')
MANUAL = os.path.join(RESOURCES, 'manual.html')
LOGO = os.path.join(RESOURCES, 'hidropy.png')

AUTHOR = 'Caio Henrique de Oliveira Nascimento'
AUTHOR_INFO = 'Estudante de Engenharia Ambiental e Sanitária<br>IFCE — campus Maracanaú'
LINKEDIN = 'https://www.linkedin.com/in/caio-henrique-6a6650236'


class ManualDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Manual do HidroPy')
        self.resize(900, 760)
        v = QVBoxLayout(self)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)        # LinkedIn abre no navegador
        self.browser.setOpenLinks(True)                # links do sumário rolam o texto
        try:
            with open(MANUAL, encoding='utf-8') as f:
                self.browser.setHtml(f.read())
        except OSError:
            self.browser.setPlainText('Manual não encontrado.')
        v.addWidget(self.browser)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Sobre o HidroPy')
        h = QHBoxLayout()
        logo = QLabel()
        if os.path.exists(LOGO):
            logo.setPixmap(QPixmap(LOGO).scaled(120, 120, Qt.KeepAspectRatio,
                                                Qt.SmoothTransformation))
        logo.setAlignment(Qt.AlignTop)
        h.addWidget(logo)
        text = QLabel(
            '<h2 style="margin:0">HidroPy</h2>'
            '<p>Simulador hidráulico baseado em Python</p>'
            '<p>Desenho, simulação e otimização de redes de distribuição de água, com '
            'simulação hidráulica pelo EPANET e otimização de diâmetros por algoritmo '
            'genético.</p>'
            f'<p><b>Criado por</b><br>{AUTHOR}<br>{AUTHOR_INFO}</p>'
            f'<p>LinkedIn: <a href="{LINKEDIN}">www.linkedin.com/in/caio-henrique-6a6650236</a>'
            '</p>')
        text.setTextFormat(Qt.RichText)
        text.setWordWrap(True)
        text.setOpenExternalLinks(True)
        text.setTextInteractionFlags(Qt.TextBrowserInteraction)
        text.setMinimumWidth(360)
        h.addWidget(text, 1)
        v = QVBoxLayout(self)
        v.addLayout(h)
        bb = QDialogButtonBox(QDialogButtonBox.Ok)
        bb.accepted.connect(self.accept)
        v.addWidget(bb)
