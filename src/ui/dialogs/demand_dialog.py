"""Consumos nodais pelo método linear: parâmetros → resumo → aplicar ou cancelar."""

from __future__ import annotations

import copy

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog,
                               QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QMessageBox, QPushButton, QRadioButton,
                               QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout)

from ...hydraulics import demand as D
from ...hydraulics.population import METHODS
from .population_dialog import fmt_dec, fmt_pop


class DemandDialog(QDialog):
    """Parâmetros do método linear. 'Calcular' abre o resumo com Aplicar / Cancelar."""

    def __init__(self, ctrl, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.setWindowTitle('Consumos nodais — método linear')
        self.settings = copy.deepcopy(ctrl.project.demand_settings)
        self.applied = False
        s = self.settings
        st = ctrl.project.population_study()
        v = QVBoxLayout(self)

        box = QGroupBox('População')
        form = QFormLayout(box)
        self.rb_adopted = QRadioButton('Projeção populacional adotada')
        self.rb_manual = QRadioButton('Informar manualmente')
        grp = QButtonGroup(self)
        grp.addButton(self.rb_adopted)
        grp.addButton(self.rb_manual)
        form.addRow(self.rb_adopted)
        self.lbl_study = QLabel()
        self.lbl_study.setWordWrap(True)
        form.addRow(self.lbl_study)
        self.year = QSpinBox()
        self.year.setRange(1800, 2300)
        self.method = QComboBox()
        for k, t in METHODS.items():
            self.method.addItem(t, k)
        form.addRow('Ano', self.year)
        form.addRow('Método', self.method)
        form.addRow(self.rb_manual)
        self.manual = QDoubleSpinBox()
        self.manual.setRange(0, 1e9)
        self.manual.setDecimals(0)
        self.manual.setSuffix(' hab')
        self.manual.setValue(s.manual_population)
        form.addRow('População', self.manual)
        self.lbl_pop = QLabel()
        form.addRow('População utilizada', self.lbl_pop)
        v.addWidget(box)

        box = QGroupBox('Consumo e coeficientes')
        form = QFormLayout(box)
        self.qpc = QDoubleSpinBox()
        self.qpc.setRange(1, 2000)
        self.qpc.setDecimals(1)
        self.qpc.setSuffix(' L/hab·dia')
        self.qpc.setValue(s.per_capita)
        form.addRow('Consumo per capita (q)', self.qpc)
        self.k1 = QDoubleSpinBox()
        self.k2 = QDoubleSpinBox()
        for w, val in ((self.k1, s.k1), (self.k2, s.k2)):
            w.setRange(0.01, 10)
            w.setDecimals(2)
            w.setSingleStep(0.05)
            w.setValue(val)
        self.use_k1 = QCheckBox('aplicar')
        self.use_k1.setChecked(s.use_k1)
        self.use_k2 = QCheckBox('aplicar')
        self.use_k2.setChecked(s.use_k2)
        for label, w, cb in (('K1 — dia de maior consumo', self.k1, self.use_k1),
                             ('K2 — hora de maior consumo', self.k2, self.use_k2)):
            h = QHBoxLayout()
            h.addWidget(w)
            h.addWidget(cb)
            form.addRow(label, h)
        self.mode = QComboBox()
        self.mode.addItem('Substituir a demanda-base atual das junções', 'substituir')
        self.mode.addItem('Somar à demanda-base atual (manter demandas pontuais)', 'somar')
        self.mode.setCurrentIndex(max(0, self.mode.findData(s.mode)))
        form.addRow('Aplicação', self.mode)
        v.addWidget(box)

        n_ex = sum(1 for l in ctrl.project.network.links.values()
                   if l.KIND == 'pipe' and not l.distributes)
        v.addWidget(QLabel(f'Trechos que não distribuem vazão (adutoras): {n_ex}. Ajuste a '
                           'propriedade "Distribui vazão (método linear)" das tubulações.'))
        h = QHBoxLayout()
        h.addStretch()
        b = QPushButton('Calcular')
        b.setDefault(True)
        b.clicked.connect(self.calculate)
        h.addWidget(b)
        b = QPushButton('Fechar')
        b.clicked.connect(self.reject)
        h.addWidget(b)
        v.addLayout(h)

        if st is not None and st.ka is not None:
            self.lbl_study.setText(f"Estudo adotado: <b>{st.name}</b> — horizonte {st.end_year}")
            self.year.setValue(s.population_year or st.end_year)
            self.method.setCurrentIndex(max(0, self.method.findData(
                s.population_method or st.adopted_method)))
        else:
            self.lbl_study.setText('<span style="color:#b00000">Nenhuma projeção adotada '
                                   '(Demandas → Projeção populacional).</span>')
            self.rb_adopted.setEnabled(False)
            s.population_source = 'manual'
        (self.rb_manual if s.population_source == 'manual' else self.rb_adopted).setChecked(True)
        for w in (self.rb_adopted, self.rb_manual):
            w.toggled.connect(self._refresh)
        self.year.valueChanged.connect(self._refresh)
        self.method.currentIndexChanged.connect(self._refresh)
        self.manual.valueChanged.connect(self._refresh)
        self._refresh()

    def _read(self) -> D.DemandSettings:
        s = self.settings
        s.population_source = 'manual' if self.rb_manual.isChecked() else 'adotada'
        st = self.ctrl.project.population_study()
        # guarda 0/'' quando coincide com o estudo (segue o estudo se ele mudar)
        s.population_year = self.year.value() if not st or self.year.value() != st.end_year else 0
        m = self.method.currentData()
        s.population_method = m if not st or m != st.adopted_method else ''
        s.manual_population = self.manual.value()
        s.per_capita, s.k1, s.k2 = self.qpc.value(), self.k1.value(), self.k2.value()
        s.use_k1, s.use_k2 = self.use_k1.isChecked(), self.use_k2.isChecked()
        s.mode = self.mode.currentData()
        return s

    def _refresh(self, *_):
        manual = self.rb_manual.isChecked()
        self.manual.setEnabled(manual)
        self.year.setEnabled(not manual)
        self.method.setEnabled(not manual)
        try:
            pop, origin = D.resolve_population(self.ctrl.project, self._read())
            self.lbl_pop.setText(f'<b>{fmt_pop(pop)} hab</b> ({origin})')
        except D.DemandError as e:
            self.lbl_pop.setText(f'<span style="color:#b00000">{e}</span>')

    def calculate(self):
        s = self._read()
        try:
            pop, origin = D.resolve_population(self.ctrl.project, s)
            res = D.compute_linear(self.ctrl.project, s, pop)
        except D.DemandError as e:
            QMessageBox.warning(self, 'Consumos nodais', str(e))
            return
        summary = DemandSummaryDialog(self.ctrl, res, origin, self)
        if summary.exec() == QDialog.Accepted:
            changes = D.apply_changes(self.ctrl.project, res)
            self.ctrl.project.demand_settings = copy.deepcopy(s)
            self.ctrl.mark_dirty()
            self.ctrl.apply(changes, f'Consumos nodais — método linear ({len(res.nodes)} nós)')
            self.ctrl.message.emit(f'Consumos nodais aplicados: {fmt_dec(res.total_flow, 3)} L/s '
                                   f'distribuídos em {len(res.nodes)} junções.')
            self.applied = True
            self.accept()


class DemandSummaryDialog(QDialog):
    """Resumo do cálculo. Aplicar grava as demandas (com desfazer); Cancelar não altera nada."""

    def __init__(self, ctrl, res: D.LinearResult, origin: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Resumo — consumos nodais pelo método linear')
        self.resize(820, 620)
        net = ctrl.project.network
        v = QVBoxLayout(self)
        old_total = sum(d['old'] for d in res.nodes.values())
        new_total = sum(d['new'] for d in res.nodes.values())
        lines = [
            f'<b>População:</b> {fmt_pop(res.population)} hab ({origin})',
            f'<b>Consumo per capita:</b> {fmt_dec(res.per_capita, 1)} L/hab·dia — '
            f'<b>K1</b> = {fmt_dec(res.k1)} — <b>K2</b> = {fmt_dec(res.k2)}',
            f'<b>Vazão total</b> Q = P·q·K1·K2/86400 = <b>{fmt_dec(res.total_flow, 3)} L/s</b>',
            f'<b>Extensão de rede distribuidora</b> L = {fmt_dec(res.total_length, 2)} m '
            f'({len(res.excluded)} trecho(s) fora do cálculo)',
            f'<b>Vazão linear</b> qm = Q/L = <b>{fmt_dec(res.linear_rate, 6)} L/s·m</b> '
            f'({fmt_dec(res.linear_rate * 1000, 4)} L/s·km)',
            f'<b>Junções:</b> {len(res.nodes)} — demanda-base total atual '
            f'{fmt_dec(old_total, 3)} L/s → nova {fmt_dec(new_total, 3)} L/s '
            f'({"substitui" if res.mode == "substituir" else "soma à"} demanda atual)',
        ]
        lab = QLabel('<br>'.join(lines))
        lab.setTextFormat(Qt.RichText)
        lab.setWordWrap(True)
        v.addWidget(lab)
        if res.warnings:
            w = QLabel('<br>'.join(f'⚠ {x}' for x in res.warnings))
            w.setWordWrap(True)
            w.setStyleSheet('color: #b36b00;')
            v.addWidget(w)
        table = QTableWidget(len(res.nodes), 5)
        table.setHorizontalHeaderLabels(['Junção', 'Extensão de influência (m)',
                                         'Demanda atual (L/s)', 'Calculada (L/s)',
                                         'Nova demanda (L/s)'])
        table.verticalHeader().hide()
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        rows = sorted(res.nodes.items(), key=lambda t: net.nodes[t[0]].name)
        for r, (uid, d) in enumerate(rows):
            vals = [net.nodes[uid].name, d['length'], d['old'], d['added'], d['new']]
            for c, val in enumerate(vals):
                it = QTableWidgetItem()
                if c == 0:
                    it.setText(val)
                else:
                    it.setData(Qt.DisplayRole, round(val, 4 if c > 1 else 2))
                it.setTextAlignment(Qt.AlignCenter)
                if c == 4 and abs(d['new'] - d['old']) > 1e-9:
                    it.setForeground(QColor('#1a7fd0'))
                table.setItem(r, c, it)
        table.setSortingEnabled(True)
        table.sortItems(0, Qt.AscendingOrder)
        v.addWidget(table, 1)
        v.addWidget(QLabel('Aplicar altera a demanda-base das junções (pode ser desfeito com '
                           'Ctrl+Z). Cancelar volta aos parâmetros sem alterar a rede.'))
        h = QHBoxLayout()
        h.addStretch()
        b = QPushButton('Aplicar')
        b.setDefault(True)
        b.clicked.connect(self.accept)
        h.addWidget(b)
        b = QPushButton('Cancelar')
        b.clicked.connect(self.reject)
        h.addWidget(b)
        v.addLayout(h)
