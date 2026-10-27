"""Gerenciador de camadas: criar, renomear, ocultar, bloquear, cor, espessura, referência."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QColorDialog, QHBoxLayout, QInputDialog,
                               QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget, QHeaderView, QLabel)

from ..hydraulics.models import Layer

COLS = ['Visível', 'Bloq.', 'Ref.', 'Cor', 'Nome', 'Esp.', 'Itens']


class LayersPanel(QWidget):
    currentLayerChanged = Signal(str)

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.ctrl = controller
        self.current = '0'
        v = QVBoxLayout(self)
        v.setContentsMargins(2, 2, 2, 2)
        self.lbl = QLabel()
        v.addWidget(self.lbl)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        for c in (0, 1, 2, 3, 5, 6):
            self.table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)
        v.addWidget(self.table)
        h = QHBoxLayout()
        for text, fn in (('Nova', self.add_layer), ('Renomear', self.rename_layer),
                         ('Excluir', self.delete_layer), ('Tornar atual', self.make_current)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            h.addWidget(b)
        v.addLayout(h)
        self._building = False
        self.table.itemChanged.connect(self._item_changed)
        self.table.cellDoubleClicked.connect(self._double)
        self.ctrl.projectReplaced.connect(self.refresh)
        self.ctrl.layersChanged.connect(self.refresh)
        self.ctrl.elementsChanged.connect(lambda cs: self.refresh())
        self.refresh()

    def layers(self):
        return list(self.ctrl.project.layers.values())

    def refresh(self):
        self._building = True
        p = self.ctrl.project
        counts = {}
        for e in list(p.cad.values()) + list(p.network.nodes.values()) + \
                list(p.network.links.values()):
            counts[e.layer] = counts.get(e.layer, 0) + 1
        ls = self.layers()
        self.table.setRowCount(len(ls))
        for r, l in enumerate(ls):
            for c, val in ((0, l.visible), (1, l.locked), (2, l.reference)):
                it = QTableWidgetItem()
                it.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                it.setCheckState(Qt.Checked if val else Qt.Unchecked)
                it.setData(Qt.UserRole, l.uid)
                self.table.setItem(r, c, it)
            ci = QTableWidgetItem('')
            ci.setBackground(QColor(l.color))
            ci.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            ci.setToolTip('Duplo clique para alterar a cor')
            self.table.setItem(r, 3, ci)
            ni = QTableWidgetItem(('▶ ' if l.name == self.current else '') + l.name)
            ni.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            ni.setToolTip(f'origem: {l.source}')
            self.table.setItem(r, 4, ni)
            wi = QTableWidgetItem(f'{l.line_width:g}')
            self.table.setItem(r, 5, wi)
            qi = QTableWidgetItem(str(counts.get(l.name, 0)))
            qi.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(r, 6, qi)
        self.lbl.setText(f'Camada atual para desenho CAD: <b>{self.current}</b>')
        self._building = False

    def _layer_at(self, row) -> Layer | None:
        ls = self.layers()
        return ls[row] if 0 <= row < len(ls) else None

    def _item_changed(self, it):
        if self._building:
            return
        l = self._layer_at(it.row())
        if l is None:
            return
        c = it.column()
        if c in (0, 1, 2):
            val = it.checkState() == Qt.Checked
            setattr(l, ('visible', 'locked', 'reference')[c], val)
        elif c == 5:
            try:
                l.line_width = max(0.1, float(it.text().replace(',', '.')))
            except ValueError:
                pass
        self.ctrl.mark_dirty()
        self.ctrl.layersChanged.emit()

    def _double(self, row, col):
        l = self._layer_at(row)
        if l is None:
            return
        if col == 3:
            c = QColorDialog.getColor(QColor(l.color), self, f'Cor da camada {l.name}')
            if c.isValid():
                l.color = c.name()
                self.ctrl.mark_dirty()
                self.ctrl.layersChanged.emit()
        elif col == 4:
            self.make_current()

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        return self._layer_at(rows[0].row()) if rows else None

    def add_layer(self):
        name, ok = QInputDialog.getText(self, 'Nova camada', 'Nome:')
        if not ok or not name.strip():
            return
        if self.ctrl.project.layer_by_name(name.strip()):
            QMessageBox.warning(self, 'Camada', 'Já existe uma camada com esse nome.')
            return
        self.ctrl.project.add_layer(Layer(name=name.strip(), source='usuario'))
        self.ctrl.mark_dirty()
        self.ctrl.layersChanged.emit()

    def rename_layer(self):
        l = self._selected()
        if l is None:
            return
        name, ok = QInputDialog.getText(self, 'Renomear camada', 'Novo nome:', text=l.name)
        name = name.strip()
        if not ok or not name or name == l.name:
            return
        if self.ctrl.project.layer_by_name(name):
            QMessageBox.warning(self, 'Camada', 'Já existe uma camada com esse nome.')
            return
        old = l.name
        p = self.ctrl.project
        items = [(e.uid, {'layer': name}) for e in list(p.cad.values()) +
                 list(p.network.nodes.values()) + list(p.network.links.values())
                 if e.layer == old]
        l.name = name
        if self.current == old:
            self.current = name
            self.currentLayerChanged.emit(name)
        if items:
            self.ctrl.update_elements(items, f'Renomear camada {old}')
        self.ctrl.mark_dirty()
        self.ctrl.layersChanged.emit()

    def delete_layer(self):
        l = self._selected()
        if l is None:
            return
        p = self.ctrl.project
        used = [e for e in list(p.cad.values()) + list(p.network.nodes.values()) +
                list(p.network.links.values()) if e.layer == l.name]
        if used:
            QMessageBox.information(self, 'Camada', f'A camada contém {len(used)} elemento(s). '
                                    'Mova-os ou exclua-os antes.')
            return
        if l.name == '0':
            return
        del p.layers[l.uid]
        self.ctrl.mark_dirty()
        self.ctrl.layersChanged.emit()

    def make_current(self):
        l = self._selected()
        if l is None:
            return
        if l.locked or l.reference:
            QMessageBox.information(self, 'Camada', 'Camadas bloqueadas ou de referência não '
                                    'podem receber novos desenhos.')
            return
        self.current = l.name
        self.currentLayerChanged.emit(l.name)
        self.refresh()
