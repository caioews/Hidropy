"""Exportação DXF: planta de cálculo ou planta de execução."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QRadioButton, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ...cad import dxf_plans as DP
from ...cad import fittings as F


class DxfExportDialog(QDialog):
    def __init__(self, ctrl, time_index=0, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.time_index = time_index
        self.points = None
        self.setWindowTitle('Exportar DXF')
        self.resize(900, 640)
        s = ctrl.project.settings
        self.sim = ctrl.project.latest_result('simulation')
        v = QVBoxLayout(self)

        top = QHBoxLayout()
        self.rb_calc = QRadioButton('Planta de cálculo (resultados)')
        self.rb_exec = QRadioButton('Planta de execução (peças de conexão)')
        g = QButtonGroup(self)
        g.addButton(self.rb_calc)
        g.addButton(self.rb_exec)
        top.addWidget(self.rb_calc)
        top.addWidget(self.rb_exec)
        top.addStretch()
        v.addLayout(top)

        common = QFormLayout()
        self.h = QDoubleSpinBox()
        self.h.setRange(0.01, 1000)
        self.h.setDecimals(2)
        self.h.setSuffix(' m')
        self.h.setValue(s.dxf_text_height)
        self.h.setToolTip('Altura dos textos. Os blocos de conexão usam a mesma escala.')
        common.addRow('Altura dos textos (escala das conexões)', self.h)
        self.cad = QCheckBox('Incluir o desenho de referência (camadas CAD visíveis)')
        self.cad.setChecked(s.dxf_include_cad)
        common.addRow(self.cad)
        v.addLayout(common)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._calc_page(s))
        self.stack.addWidget(self._exec_page(s))
        v.addWidget(self.stack, 1)

        h = QHBoxLayout()
        h.addStretch()
        self.btn_export = QPushButton('Exportar…')
        self.btn_export.setDefault(True)
        self.btn_export.clicked.connect(self.export)
        h.addWidget(self.btn_export)
        b = QPushButton('Fechar')
        b.clicked.connect(self.reject)
        h.addWidget(b)
        v.addLayout(h)

        self.rb_calc.toggled.connect(lambda on: self.stack.setCurrentIndex(0 if on else 1))
        (self.rb_exec if s.dxf_plan == 'exec' else self.rb_calc).setChecked(True)
        self.stack.setCurrentIndex(1 if s.dxf_plan == 'exec' else 0)
        for w in (self.h, self.tol, self.minseg, self.ends, self.vertex, self.caps):
            sig = getattr(w, 'valueChanged', None) or getattr(w, 'currentIndexChanged', None) \
                or w.toggled
            sig.connect(self._invalidate)

    # ------------------------------------------------------------------ páginas
    def _calc_page(self, s):
        w = QWidget()
        v = QVBoxLayout(w)
        if self.sim:
            times = self.sim.get('times', [0])
            ti = min(self.time_index, len(times) - 1)
            info = (f'Resultados da última simulação, instante {times[ti] / 3600:.2f} h '
                    '(o instante é o selecionado no painel de resultados).')
        else:
            info = ('Não há simulação neste cenário: somente os dados de cadastro podem ser '
                    'exportados. Execute a simulação (F5) para incluir resultados.')
        lab = QLabel(info)
        lab.setWordWrap(True)
        v.addWidget(lab)
        h = QHBoxLayout()
        self.link_cb, self.node_cb = {}, {}
        for title, fields, results, chosen, store in (
                ('Informações dos trechos', DP.LINK_FIELDS, DP.RESULT_LINK,
                 s.dxf_calc_link_fields, self.link_cb),
                ('Informações dos nós', DP.NODE_FIELDS, DP.RESULT_NODE, s.dxf_calc_node_fields,
                 self.node_cb)):
            box = QGroupBox(title)
            grid = QGridLayout(box)
            for k, (key, label) in enumerate(fields.items()):
                cb = QCheckBox(label + (' *' if key in results else ''))
                cb.setChecked(key in chosen)
                if key in results and not self.sim:
                    cb.setChecked(False)          # a preferência salva não é alterada
                    cb.setEnabled(False)
                grid.addWidget(cb, k % 6, k // 6)
                store[key] = cb
            h.addWidget(box)
        v.addLayout(h)
        self.arrows = QCheckBox('Setas de sentido de escoamento *')
        self.arrows.setChecked(s.dxf_calc_arrows and bool(self.sim))
        self.arrows.setEnabled(bool(self.sim))
        v.addWidget(self.arrows)
        v.addWidget(QLabel('* resultado da simulação. A planta de cálculo não inclui peças de '
                           'conexão.'))
        v.addStretch()
        return w

    def _exec_page(self, s):
        w = QWidget()
        v = QVBoxLayout(w)
        box = QGroupBox('Etapa 1 — critérios das conexões')
        form = QFormLayout(box)
        self.tol = QDoubleSpinBox()
        self.tol.setRange(0, 45)
        self.tol.setDecimals(1)
        self.tol.setSuffix(' °')
        self.tol.setValue(s.fit_tolerance)
        self.tol.setToolTip('Deflexão que a própria junta absorve: abaixo dela não se usa curva.')
        form.addRow('Deflexão admissível na junta', self.tol)
        self.minseg = QDoubleSpinBox()
        self.minseg.setRange(0.0, 50.0)
        self.minseg.setDecimals(2)
        self.minseg.setSuffix(' m')
        self.minseg.setValue(s.fit_min_segment)
        self.minseg.setToolTip('Vértices a menos desta distância do ponto anterior são unidos: '
                               'evita dobras falsas em segmentos de poucos centímetros (por '
                               'exemplo, vértice coincidente com o nó). As deflexões se somam '
                               'numa só peça.')
        form.addRow('Comprimento mínimo de segmento', self.minseg)
        self.ends = QComboBox()
        for k, t in F.END_MODES.items():
            self.ends.addItem(t, k)
        self.ends.setCurrentIndex(max(0, self.ends.findData(s.fit_curve_ends)))
        form.addRow('Extremidades (bolsa / ponta)', self.ends)
        self.vertex = QCheckBox('Prever curvas nos vértices das tubulações')
        self.vertex.setChecked(s.fit_vertex_bends)
        form.addRow(self.vertex)
        self.caps = QCheckBox('CAP nas pontas de rede')
        self.caps.setChecked(s.fit_caps)
        form.addRow(self.caps)
        self.callouts = QCheckBox('Linhas de chamada com peças, material e diâmetros')
        self.callouts.setChecked(s.fit_callouts)
        form.addRow(self.callouts)
        self.callout_style = QComboBox()
        for k, t in DP.CALLOUT_STYLES.items():
            self.callout_style.addItem(t, k)
        self.callout_style.setCurrentIndex(max(0, self.callout_style.findData(
            s.fit_callout_style)))
        self.callouts.toggled.connect(self.callout_style.setEnabled)
        self.callout_style.setEnabled(s.fit_callouts)
        form.addRow('Tipo de chamada', self.callout_style)
        self.table_cb = QCheckBox('Quadro "Relação de conexões" (quantitativo)')
        self.table_cb.setChecked(s.fit_table)
        form.addRow(self.table_cb)
        self.labels = QCheckBox('Rótulo dos trechos (ID, material, DN, comprimento)')
        self.labels.setChecked(s.fit_pipe_labels)
        form.addRow(self.labels)
        hl = QHBoxLayout()
        self.lib = QLineEdit(s.fittings_library)
        self.lib.setPlaceholderText('biblioteca do programa (blocos unifilares BB e BP)')
        b = QPushButton('…')
        b.clicked.connect(self._pick_lib)
        hl.addWidget(self.lib)
        hl.addWidget(b)
        form.addRow('Biblioteca de blocos (DXF)', hl)
        v.addWidget(box)

        box = QGroupBox('Etapa 2 — conferência das conexões por junção e vértice')
        bv = QVBoxLayout(box)
        hb = QHBoxLayout()
        b = QPushButton('Analisar conexões')
        b.clicked.connect(self.analyze)
        hb.addWidget(b)
        self.only_warn = QCheckBox('Mostrar só pontos com observações')
        self.only_warn.toggled.connect(self._fill_review)
        hb.addWidget(self.only_warn)
        self.review_lbl = QLabel('')
        hb.addWidget(self.review_lbl, 1)
        bv.addLayout(hb)
        self.review = QTableWidget(0, 3)
        self.review.setHorizontalHeaderLabels(['Local', 'Peças', 'Observações'])
        self.review.verticalHeader().hide()
        self.review.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.review.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.review.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        bv.addWidget(self.review, 1)
        bv.addWidget(QLabel('Relação de conexões:'))
        self.qty = QPlainTextEdit()
        self.qty.setReadOnly(True)
        self.qty.setMaximumHeight(120)
        bv.addWidget(self.qty)
        v.addWidget(box, 1)
        return w

    def _pick_lib(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Biblioteca de blocos', self.lib.text(),
                                              'DXF (*.dxf)')
        if path:
            self.lib.setText(path)
            self._invalidate()

    # ------------------------------------------------------------------ execução
    def _fit_options(self) -> F.FittingOptions:
        return F.FittingOptions(tolerance=self.tol.value(), curve_ends=self.ends.currentData(),
                                vertex_bends=self.vertex.isChecked(), caps=self.caps.isChecked(),
                                min_segment=self.minseg.value())

    def _invalidate(self, *_):
        self.points = None
        if hasattr(self, 'review_lbl'):
            self.review_lbl.setText('Critérios alterados: analise novamente.')

    def analyze(self):
        self.points = F.analyze_network(self.ctrl.project, self._fit_options(),
                                        scale=self.h.value())
        self._fill_review()
        q = F.quantities(self.points)
        self.qty.setPlainText('\n'.join(f'{n:>4}  {lab}' for lab, n in q.items())
                              if q else 'Nenhuma peça necessária.')
        n_pts = sum(1 for p in self.points if p.pieces)
        n_warn = sum(1 for p in self.points if p.warnings)
        self.review_lbl.setText(f'{n_pts} ponto(s) com peças, {sum(q.values())} peça(s), '
                                f'{n_warn} ponto(s) com observações.')

    def _fill_review(self, *_):
        if self.points is None:
            return
        rows = [(fp, pcs) for fp in self.points
                for pcs in [DP.callout_lines(fp) if fp.pieces else []]
                if (fp.pieces or fp.warnings) and (fp.warnings or not self.only_warn.isChecked())]
        self.review.setRowCount(len(rows))
        for r, (fp, pcs) in enumerate(rows):
            items = [fp.name, '; '.join(pcs) or '—', ' '.join(fp.warnings)]
            for c, t in enumerate(items):
                it = QTableWidgetItem(t)
                it.setToolTip(t)
                if c == 2 and t:
                    it.setForeground(Qt.darkYellow)
                self.review.setItem(r, c, it)
        self.review.resizeRowsToContents()

    def _save_settings(self):
        s = self.ctrl.project.settings
        s.dxf_plan = 'exec' if self.rb_exec.isChecked() else 'calc'
        s.dxf_text_height = self.h.value()
        s.dxf_include_cad = self.cad.isChecked()
        for attr, boxes, results in (('dxf_calc_link_fields', self.link_cb, DP.RESULT_LINK),
                                     ('dxf_calc_node_fields', self.node_cb, DP.RESULT_NODE)):
            keep = [] if self.sim else [k for k in getattr(s, attr) if k in results]
            setattr(s, attr, [k for k, cb in boxes.items() if cb.isChecked()] + keep)
        if self.sim:
            s.dxf_calc_arrows = self.arrows.isChecked()
        s.fit_tolerance = self.tol.value()
        s.fit_min_segment = self.minseg.value()
        s.fit_curve_ends = self.ends.currentData()
        s.fit_vertex_bends = self.vertex.isChecked()
        s.fit_caps = self.caps.isChecked()
        s.fit_callouts = self.callouts.isChecked()
        s.fit_callout_style = self.callout_style.currentData()
        s.fit_table = self.table_cb.isChecked()
        s.fit_pipe_labels = self.labels.isChecked()
        s.fittings_library = self.lib.text().strip()
        self.ctrl.mark_dirty()

    def export(self):
        exec_plan = self.rb_exec.isChecked()
        lib = self.lib.text().strip()
        if exec_plan and lib and not os.path.exists(lib):
            QMessageBox.warning(self, 'Exportar DXF', f'Biblioteca não encontrada:\n{lib}')
            return
        default = 'planta_execucao.dxf' if exec_plan else 'planta_calculo.dxf'
        path, _ = QFileDialog.getSaveFileName(self, 'Exportar DXF', default, 'DXF (*.dxf)')
        if not path:
            return
        if not path.lower().endswith('.dxf'):
            path += '.dxf'
        self._save_settings()
        p = self.ctrl.project
        try:
            if exec_plan:
                if self.points is None:
                    self.analyze()
                opts = DP.ExecOptions(text_height=self.h.value(),
                                      include_cad=self.cad.isChecked(),
                                      pipe_labels=self.labels.isChecked(),
                                      callouts=self.callouts.isChecked(),
                                      callout_style=self.callout_style.currentData(),
                                      table=self.table_cb.isChecked(), library=lib,
                                      fittings=self._fit_options())
                DP.export_exec_plan(p, path, opts, self.points)
                n = sum(len(fp.pieces) for fp in self.points)
                msg = f'Planta de execução exportada ({n} peças): {path}'
            else:
                opts = DP.CalcOptions(
                    text_height=self.h.value(), include_cad=self.cad.isChecked(),
                    link_fields=[k for k, cb in self.link_cb.items() if cb.isChecked()],
                    node_fields=[k for k, cb in self.node_cb.items() if cb.isChecked()],
                    arrows=self.arrows.isChecked(), time_index=self.time_index)
                DP.export_calc_plan(p, path, opts, self.sim)
                msg = f'Planta de cálculo exportada: {path}'
        except Exception as e:
            QMessageBox.critical(self, 'Exportar DXF', f'Falha ao exportar:\n{e}')
            return
        self.ctrl.message.emit(msg)
        QMessageBox.information(self, 'Exportar DXF', msg)
        self.accept()
