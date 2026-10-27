"""Editores de curvas, padrões, controles e cenários."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QPlainTextEdit)

from ...hydraulics import editing
from ...hydraulics.models import (Curve, Pattern, Control, CURVE_TYPES, CONTROL_CONDITIONS)

CURVE_AXES = {'PUMP': ('Vazão (L/s)', 'Carga (m)'), 'EFFICIENCY': ('Vazão (L/s)', 'Rend. (%)'),
              'VOLUME': ('Altura (m)', 'Volume (m³)'), 'HEADLOSS': ('Vazão (L/s)', 'Perda (m)')}


class _ListEditor(QDialog):
    KIND = ''
    TITLE = ''

    def __init__(self, ctrl, select_uid='', parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.setWindowTitle(self.TITLE)
        self.resize(760, 480)
        h = QHBoxLayout(self)
        left = QVBoxLayout()
        self.list = QListWidget()
        left.addWidget(self.list, 1)
        hb = QHBoxLayout()
        for text, fn in (('Novo', self.new), ('Excluir', self.delete)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            hb.addWidget(b)
        left.addLayout(hb)
        h.addLayout(left, 1)
        self.right = QVBoxLayout()
        h.addLayout(self.right, 3)
        self.build_editor()
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        b = bb.addButton('Aplicar', QDialogButtonBox.ApplyRole)
        b.clicked.connect(self.save_current)
        bb.rejected.connect(self.reject)
        self.right.addWidget(bb)
        self.list.currentItemChanged.connect(self._changed)
        self.reload(select_uid)

    def store(self):
        return getattr(self.ctrl.project.network, self.KIND + 's')

    def reload(self, select=''):
        self.list.blockSignals(True)
        self.list.clear()
        row = 0
        for i, (u, e) in enumerate(self.store().items()):
            it = QListWidgetItem(e.name)
            it.setData(Qt.UserRole, u)
            self.list.addItem(it)
            if u == select:
                row = i
        self.list.blockSignals(False)
        if self.list.count():
            self.list.setCurrentRow(row)
            self._changed(self.list.currentItem(), None)
        else:
            self.load(None)

    def current(self):
        it = self.list.currentItem()
        return self.store().get(it.data(Qt.UserRole)) if it else None

    def _changed(self, cur, prev):
        self.load(self.current())

    def new(self):
        net = self.ctrl.project.network
        e = self.make(net.unique_name(self.KIND))
        self.ctrl.add_elements([e], f'Novo {self.KIND}')
        self.reload(e.uid)

    def delete(self):
        e = self.current()
        if e is None:
            return
        if QMessageBox.question(self, 'Excluir', f"Excluir '{e.name}'? As referências a ele "
                                "serão removidas.") != QMessageBox.Yes:
            return
        self.ctrl.delete([e.uid], f'Excluir {e.name}')
        self.reload()

    def save_current(self):
        e = self.current()
        if e is None:
            return
        try:
            props = self.collect()
        except ValueError as ex:
            QMessageBox.warning(self, 'Valor inválido', str(ex))
            return
        other = self.ctrl.project.network.find_by_name(props.get('name', e.name), e.COLLECTION)
        if other is not None and other.uid != e.uid:
            QMessageBox.warning(self, 'Identificador', 'Identificador já utilizado.')
            return
        self.ctrl.apply(editing.update(self.ctrl.project, e.uid, **props), f'Editar {e.name}')
        self.reload(e.uid)


class CurvesDialog(_ListEditor):
    KIND = 'curve'
    TITLE = 'Curvas (bomba, rendimento, volume, perda)'

    def make(self, name):
        return Curve(name=name, curve_type='PUMP', points=[[0, 50], [10, 45], [20, 30]])

    def build_editor(self):
        form = QFormLayout()
        self.name = QLineEdit()
        self.ctype = QComboBox()
        self.ctype.addItems(CURVE_TYPES)
        form.addRow('Identificador', self.name)
        form.addRow('Tipo', self.ctype)
        self.right.addLayout(form)
        self.pts = QTableWidget(0, 2)
        self.pts.verticalHeader().hide()
        self.right.addWidget(self.pts, 1)
        hb = QHBoxLayout()
        for text, fn in (('+ ponto', self.add_point), ('− ponto', self.del_point),
                         ('Importar CSV…', self.import_csv)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            hb.addWidget(b)
        hb.addStretch()
        self.right.addLayout(hb)
        self.hint = QLabel('Bomba: 1 ponto (projeto), 3 pontos ou ≥ 4 pontos; X crescente.')
        self.right.addWidget(self.hint)
        self.ctype.currentTextChanged.connect(self._axes)

    def _axes(self, t):
        self.pts.setHorizontalHeaderLabels(list(CURVE_AXES.get(t, ('X', 'Y'))))

    def load(self, e):
        self.pts.setRowCount(0)
        enabled = e is not None
        for w in (self.name, self.ctype, self.pts):
            w.setEnabled(enabled)
        if not e:
            self.name.setText('')
            return
        self.name.setText(e.name)
        self.ctype.setCurrentText(e.curve_type)
        self._axes(e.curve_type)
        for x, y in e.points:
            self.add_point(x, y)

    def add_point(self, x=0.0, y=0.0):
        r = self.pts.rowCount()
        self.pts.insertRow(r)
        self.pts.setItem(r, 0, QTableWidgetItem(f'{x:g}'))
        self.pts.setItem(r, 1, QTableWidgetItem(f'{y:g}'))

    def del_point(self):
        for r in sorted({i.row() for i in self.pts.selectedIndexes()}, reverse=True):
            self.pts.removeRow(r)

    def import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Pontos da curva', '', 'CSV/TXT (*.csv *.txt)')
        if not path:
            return
        pts = []
        with open(path, encoding='utf-8-sig') as f:
            for line in f:
                bits = [b for b in line.replace(';', ' ').replace('\t', ' ').split() if b]
                try:
                    pts.append((float(bits[0].replace(',', '.')), float(bits[1].replace(',', '.'))))
                except (ValueError, IndexError):
                    continue
        self.pts.setRowCount(0)
        for x, y in pts:
            self.add_point(x, y)

    def collect(self):
        pts = []
        for r in range(self.pts.rowCount()):
            try:
                pts.append([float(self.pts.item(r, c).text().replace(',', '.')) for c in (0, 1)])
            except (ValueError, AttributeError):
                raise ValueError(f'Ponto {r + 1} inválido.')
        name = self.name.text().strip()
        if not name:
            raise ValueError('Identificador vazio.')
        return {'name': name, 'curve_type': self.ctype.currentText(), 'points': pts}


class PatternsDialog(_ListEditor):
    KIND = 'pattern'
    TITLE = 'Padrões temporais (multiplicadores por passo de padrão)'

    def make(self, name):
        return Pattern(name=name, multipliers=[1.0] * 24)

    def build_editor(self):
        form = QFormLayout()
        self.name = QLineEdit()
        form.addRow('Identificador', self.name)
        self.right.addLayout(form)
        self.right.addWidget(QLabel('Multiplicadores (separados por espaço, ";" ou quebra de '
                                    'linha):'))
        self.text = QPlainTextEdit()
        self.right.addWidget(self.text, 1)
        self.info = QLabel('')
        self.right.addWidget(self.info)

    def load(self, e):
        enabled = e is not None
        self.name.setEnabled(enabled)
        self.text.setEnabled(enabled)
        if not e:
            self.name.setText('')
            self.text.setPlainText('')
            return
        self.name.setText(e.name)
        self.text.setPlainText(' '.join(f'{m:g}' for m in e.multipliers))
        step = self.ctrl.project.sim_options.pattern_step_h
        self.info.setText(f'{len(e.multipliers)} valores × passo de {step:g} h = '
                          f'{len(e.multipliers) * step:g} h; média '
                          f'{sum(e.multipliers) / max(1, len(e.multipliers)):.3f}')

    def collect(self):
        raw = self.text.toPlainText().replace(';', ' ').split()
        try:
            mult = [float(t.replace(',', '.')) for t in raw]
        except ValueError:
            raise ValueError('Multiplicador inválido.')
        if not mult:
            raise ValueError('Informe ao menos um multiplicador.')
        name = self.name.text().strip()
        if not name:
            raise ValueError('Identificador vazio.')
        return {'name': name, 'multipliers': mult}


class ControlsDialog(_ListEditor):
    KIND = 'control'
    TITLE = 'Controles operacionais simples ([CONTROLS] do EPANET)'

    def make(self, name):
        link = next(iter(self.ctrl.project.network.links), '')
        return Control(name=name, link=link)

    def build_editor(self):
        form = QFormLayout()
        self.name = QLineEdit()
        self.link = QComboBox()
        self.action = QComboBox()
        self.action.setEditable(True)
        self.action.addItems(['OPEN', 'CLOSED'])
        self.cond = QComboBox()
        self.cond.addItems(CONTROL_CONDITIONS)
        self.node = QComboBox()
        self.value = QLineEdit()
        form.addRow('Identificador', self.name)
        form.addRow('Ligação', self.link)
        form.addRow('Ação (OPEN, CLOSED ou ajuste)', self.action)
        form.addRow('Condição', self.cond)
        form.addRow('Nó (nível do tanque ou pressão)', self.node)
        form.addRow('Valor (m, ou hora: 6 / 6:30 / 6:00 AM)', self.value)
        self.right.addLayout(form)
        self.right.addWidget(QLabel('Regras com condições compostas ([RULES]) ainda não são '
                                    'suportadas pela integração.'))
        self.right.addStretch()
        self.cond.currentTextChanged.connect(lambda t: self.node.setEnabled(t.startswith('IF')))

    def load(self, e):
        net = self.ctrl.project.network
        self.link.clear()
        for u, l in sorted(net.links.items(), key=lambda t: t[1].name):
            self.link.addItem(l.name, u)
        self.node.clear()
        for u, n in sorted(net.nodes.items(), key=lambda t: t[1].name):
            self.node.addItem(n.name, u)
        enabled = e is not None
        for w in (self.name, self.link, self.action, self.cond, self.node, self.value):
            w.setEnabled(enabled)
        if not e:
            return
        self.name.setText(e.name)
        self.link.setCurrentIndex(max(0, self.link.findData(e.link)))
        self.action.setCurrentText(e.action)
        self.cond.setCurrentText(e.condition)
        self.node.setCurrentIndex(max(0, self.node.findData(e.node)))
        self.node.setEnabled(e.condition.startswith('IF'))
        self.value.setText(e.value)

    def collect(self):
        name = self.name.text().strip()
        if not name:
            raise ValueError('Identificador vazio.')
        action = self.action.currentText().strip().upper()
        if action not in ('OPEN', 'CLOSED'):
            try:
                float(action.replace(',', '.'))
                action = action.replace(',', '.')
            except ValueError:
                raise ValueError('Ação deve ser OPEN, CLOSED ou número.')
        cond = self.cond.currentText()
        val = self.value.text().strip()
        if not val:
            raise ValueError('Informe o valor da condição.')
        if cond.startswith('IF'):
            try:
                float(val.replace(',', '.'))
                val = val.replace(',', '.')
            except ValueError:
                raise ValueError('Valor de nível/pressão deve ser numérico.')
        return {'name': name, 'link': self.link.currentData() or '', 'action': action,
                'condition': cond, 'node': self.node.currentData() if cond.startswith('IF')
                else '', 'value': val}


class ScenariosDialog(QDialog):
    """Cenários por cópia controlada da rede."""

    def __init__(self, ctrl, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.setWindowTitle('Cenários')
        self.resize(560, 360)
        v = QVBoxLayout(self)
        v.addWidget(QLabel('Cada cenário guarda uma cópia própria da rede hidráulica e seus '
                           'resultados. A geometria CAD é comum a todos.'))
        self.list = QListWidget()
        v.addWidget(self.list, 1)
        h = QHBoxLayout()
        for text, fn in (('Novo (cópia do ativo)', self.new), ('Renomear', self.rename),
                         ('Ativar', self.activate), ('Excluir', self.delete)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            h.addWidget(b)
        v.addLayout(h)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.reload()

    def reload(self):
        p = self.ctrl.project
        self.list.clear()
        for s in p.scenarios:
            parent = next((x.name for x in p.scenarios if x.uid == s.parent), '')
            it = QListWidgetItem(f"{s.name}{'  [ATIVO]' if s.uid == p.active_scenario else ''}"
                                 f"  — criado {s.created[:16].replace('T', ' ')}"
                                 + (f' a partir de {parent}' if parent else '')
                                 + (f' — {s.description}' if s.description else ''))
            it.setData(Qt.UserRole, s.uid)
            self.list.addItem(it)

    def _sel(self):
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def new(self):
        name, ok = QInputDialog.getText(self, 'Novo cenário', 'Nome (ex.: Demandas futuras):')
        if not ok or not name.strip():
            return
        desc, _ = QInputDialog.getText(self, 'Novo cenário', 'Descrição (opcional):')
        self.ctrl.project.create_scenario(name.strip(), desc)
        self.ctrl.mark_dirty()
        self.ctrl.scenarioChanged.emit()
        self.reload()

    def rename(self):
        uid = self._sel()
        if not uid:
            return
        s = self.ctrl.project.scenario(uid)
        name, ok = QInputDialog.getText(self, 'Renomear', 'Nome:', text=s.name)
        if ok and name.strip():
            s.name = name.strip()
            self.ctrl.mark_dirty()
            self.ctrl.scenarioChanged.emit()
            self.reload()

    def activate(self):
        uid = self._sel()
        if not uid or uid == self.ctrl.project.active_scenario:
            return
        if self.ctrl.undo_stack.count() and QMessageBox.question(
                self, 'Ativar cenário', 'O histórico de desfazer será limpo. Continuar?') \
                != QMessageBox.Yes:
            return
        self.ctrl.switch_scenario(uid)
        self.reload()

    def delete(self):
        uid = self._sel()
        if not uid:
            return
        try:
            s = self.ctrl.project.scenario(uid)
            if QMessageBox.question(self, 'Excluir', f"Excluir o cenário '{s.name}' e seus "
                                    "resultados?") != QMessageBox.Yes:
                return
            self.ctrl.project.delete_scenario(uid)
        except ValueError as e:
            QMessageBox.warning(self, 'Cenários', str(e))
            return
        self.ctrl.mark_dirty()
        self.ctrl.scenarioChanged.emit()
        self.reload()
