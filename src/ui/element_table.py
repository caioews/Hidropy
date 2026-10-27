"""Tabela editável de elementos: ordenação, filtro/pesquisa, edição em lote.

As edições passam pelo controlador (desfazer/refazer) e se refletem no desenho.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QTableView, QVBoxLayout,
                               QWidget, QAbstractItemView)

from ..hydraulics.models import KIND_LABELS
from ..hydraulics.schema import SCHEMA, parse_value
from ..results import tables
from .guards import confirm_existing_diameter

KINDS = ['junction', 'reservoir', 'tank', 'pipe', 'pump', 'valve', 'curve', 'pattern',
         'control']
EDITABLE = {'str', 'float', 'float_opt', 'int', 'bool', 'choice', 'layer', 'ref_node',
            'ref_pattern', 'ref_curve', 'ref_link'}


class ElementModel(QAbstractTableModel):
    def __init__(self, ctrl, kind):
        super().__init__()
        self.ctrl = ctrl
        self.kind = kind
        self.props = [p for p in SCHEMA[kind] if p.type != 'demand_cats']
        self.reload()

    def reload(self):
        self.beginResetModel()
        net = self.ctrl.project.network
        self.uids = [e.uid for e in net.elements() if e.KIND == self.kind]
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self.uids)

    def columnCount(self, parent=QModelIndex()):
        return len(self.props)

    def headerData(self, s, orient, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orient == Qt.Horizontal:
            p = self.props[s]
            return p.label + (f' ({p.unit})' if p.unit else '')
        return None

    def _raw(self, uid, p):
        e = self.ctrl.project.get(uid)
        if e is None:
            return None
        if p.key == 'geom_length':
            return round(self.ctrl.project.network.geometric_length(e), 3)
        return getattr(e, p.key, None)

    def data(self, idx, role=Qt.DisplayRole):
        if not idx.isValid():
            return None
        uid = self.uids[idx.row()]
        p = self.props[idx.column()]
        v = self._raw(uid, p)
        if role == Qt.CheckStateRole and p.type == 'bool':
            return Qt.Checked if v else Qt.Unchecked
        if role in (Qt.DisplayRole, Qt.EditRole):
            if p.type == 'bool':
                return 'sim' if v else 'não'
            if p.type.startswith('ref_'):
                e = self.ctrl.project.get(v) if v else None
                return e.name if e is not None else ''
            return v
        if role == Qt.UserRole:
            return uid
        return None

    def flags(self, idx):
        f = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        p = self.props[idx.column()]
        if p.type in EDITABLE:
            f |= Qt.ItemIsUserCheckable if p.type == 'bool' else Qt.ItemIsEditable
        return f

    def setData(self, idx, value, role=Qt.EditRole):
        uid = self.uids[idx.row()]
        p = self.props[idx.column()]
        if not confirm_existing_diameter(None, self.ctrl.project, [uid], p.key):
            return False
        try:
            v = self.convert(p, value, role)
        except ValueError as e:
            QMessageBox.warning(None, 'Valor inválido', str(e))
            return False
        return self.ctrl.update_element(uid, f'Editar {p.label}', **{p.key: v})

    def convert(self, p, value, role=Qt.EditRole):
        net = self.ctrl.project.network
        if p.type == 'bool':
            if role == Qt.CheckStateRole:
                return value in (Qt.Checked, 2, Qt.Checked.value)
            return str(value).strip().lower() in ('1', 'sim', 'true', 's', 'x')
        if p.type.startswith('ref_'):
            name = str(value).strip()
            if not name:
                if p.required:
                    raise ValueError(f'{p.label}: obrigatório.')
                return ''
            coll = {'ref_node': 'node', 'ref_link': 'link', 'ref_pattern': 'pattern',
                    'ref_curve': 'curve'}[p.type]
            e = net.find_by_name(name, coll)
            if e is None:
                raise ValueError(f"{p.label}: '{name}' não existe.")
            return e.uid
        if p.type == 'choice':
            if str(value) not in p.choices:
                raise ValueError(f'{p.label}: use um de {p.choices}.')
            return str(value)
        if p.type == 'layer':
            if self.ctrl.project.layer_by_name(str(value)) is None:
                raise ValueError(f"Camada '{value}' inexistente.")
            return str(value)
        return parse_value(p, '' if value is None else str(value))


class ElementTable(QWidget):
    def __init__(self, controller, canvas, parent=None):
        super().__init__(parent)
        self.ctrl = controller
        self.canvas = canvas
        v = QVBoxLayout(self)
        v.setContentsMargins(2, 2, 2, 2)
        h = QHBoxLayout()
        self.kind = QComboBox()
        for k in KINDS:
            self.kind.addItem(KIND_LABELS[k], k)
        self.kind.setCurrentIndex(KINDS.index('pipe'))
        h.addWidget(QLabel('Tipo:'))
        h.addWidget(self.kind)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText('Pesquisar / filtrar (todas as colunas)…')
        h.addWidget(self.filter, 1)
        b = QPushButton('Editar em lote…')
        b.clicked.connect(self.batch_edit)
        h.addWidget(b)
        b = QPushButton('Exportar…')
        b.clicked.connect(self.export)
        h.addWidget(b)
        v.addLayout(h)
        self.view = QTableView()
        self.view.setSortingEnabled(True)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                                  | QAbstractItemView.AnyKeyPressed)
        v.addWidget(self.view, 1)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.view.setModel(self.proxy)
        self.filter.textChanged.connect(self.proxy.setFilterFixedString)
        self.kind.currentIndexChanged.connect(self.set_kind)
        self.ctrl.elementsChanged.connect(self._on_changed)
        self.ctrl.projectReplaced.connect(self.set_kind)
        self._sync = False
        self.set_kind()

    def set_kind(self, *_):
        self.model = ElementModel(self.ctrl, self.kind.currentData())
        self.proxy.setSourceModel(self.model)
        self.view.selectionModel().selectionChanged.connect(self._on_view_selection)
        self.view.resizeColumnsToContents()

    def _on_changed(self, cs):
        if cs.added or cs.removed:
            self.model.reload()
        else:
            self.model.dataChanged.emit(self.model.index(0, 0),
                                        self.model.index(self.model.rowCount() - 1,
                                                         self.model.columnCount() - 1))

    def selected_uids(self):
        rows = {self.proxy.mapToSource(i).row() for i in self.view.selectionModel().selectedRows()}
        return [self.model.uids[r] for r in sorted(rows)]

    def _on_view_selection(self, *_):
        uids = self.selected_uids()
        if uids:
            self.ctrl.set_selection(uids, 'table')

    def batch_edit(self):
        uids = self.selected_uids()
        if not uids:
            QMessageBox.information(self, 'Edição em lote', 'Selecione as linhas a editar.')
            return
        props = [p for p in self.model.props if p.batch and p.type in EDITABLE]
        labels = [p.label for p in props]
        lab, ok = QInputDialog.getItem(self, 'Edição em lote',
                                       f'Propriedade ({len(uids)} elementos):', labels, 0, False)
        if not ok:
            return
        p = props[labels.index(lab)]
        if p.type == 'choice':
            val, ok = QInputDialog.getItem(self, 'Edição em lote', p.label, p.choices, 0, False)
        else:
            val, ok = QInputDialog.getText(self, 'Edição em lote', f'Novo valor de {p.label}:')
        if not ok:
            return
        try:
            v = self.model.convert(p, val)
        except ValueError as e:
            QMessageBox.warning(self, 'Valor inválido', str(e))
            return
        if not confirm_existing_diameter(self, self.ctrl.project, uids, p.key):
            return
        self.ctrl.update_elements([(u, {p.key: v}) for u in uids],
                                  f'Editar {p.label} ({len(uids)} elementos)')

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Exportar tabela', '',
                                              'Excel (*.xlsx);;CSV (*.csv)')
        if not path:
            return
        df = tables.elements_df(self.ctrl.project, self.kind.currentData())
        try:
            tables.export_df(df, path, KIND_LABELS[self.kind.currentData()])
        except Exception as e:
            QMessageBox.critical(self, 'Exportar', f'Falha: {e}')
