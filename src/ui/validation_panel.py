"""Lista de erros (impeditivos) e advertências da validação."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView,
                               QAbstractItemView)

from ..hydraulics.validation import validate


class ValidationPanel(QWidget):
    elementActivated = Signal(str)
    validated = Signal(int, int)        # erros, advertências

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.ctrl = controller
        self.issues = []
        v = QVBoxLayout(self)
        v.setContentsMargins(2, 2, 2, 2)
        h = QHBoxLayout()
        b = QPushButton('Validar rede')
        b.clicked.connect(self.run)
        h.addWidget(b)
        self.only_err = QCheckBox('Somente erros')
        self.only_err.toggled.connect(self._fill)
        h.addWidget(self.only_err)
        self.summary = QLabel('Rede ainda não validada.')
        h.addWidget(self.summary, 1)
        v.addLayout(h)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['Tipo', 'Código', 'Mensagem'])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.cellDoubleClicked.connect(self._activate)
        v.addWidget(self.table)

    def run(self):
        self.issues = validate(self.ctrl.project)
        self._fill()
        ne = sum(1 for i in self.issues if i.is_error)
        nw = len(self.issues) - ne
        self.summary.setText(f'<b>{ne}</b> erro(s) impeditivo(s), <b>{nw}</b> advertência(s).'
                             if self.issues else 'Nenhum problema encontrado.')
        self.validated.emit(ne, nw)
        return self.issues

    def _fill(self):
        items = [i for i in self.issues if i.is_error or not self.only_err.isChecked()]
        self.table.setRowCount(len(items))
        for r, i in enumerate(items):
            a = QTableWidgetItem('ERRO' if i.is_error else 'Advertência')
            a.setForeground(QColor('#b00000') if i.is_error else QColor('#9a6a00'))
            a.setData(Qt.UserRole, i.uid)
            self.table.setItem(r, 0, a)
            self.table.setItem(r, 1, QTableWidgetItem(i.code))
            self.table.setItem(r, 2, QTableWidgetItem(i.message))

    def _activate(self, row, col):
        uid = self.table.item(row, 0).data(Qt.UserRole)
        if uid:
            self.elementActivated.emit(uid)
