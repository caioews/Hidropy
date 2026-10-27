"""Importação DXF (seleção de camadas / referência) e conversão CAD → rede hidráulica."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QLabel, QLineEdit, QPlainTextEdit, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QHeaderView)

from ...cad.dxf_importer import DxfImportOptions, unit_scale


class DxfImportDialog(QDialog):
    def __init__(self, info, parent=None):
        super().__init__(parent)
        self.info = info
        self.setWindowTitle('Importar DXF')
        self.resize(640, 520)
        v = QVBoxLayout(self)
        ext = info.extents
        v.addWidget(QLabel(
            f'<b>{info.path}</b><br>Versão: {info.version} — unidades declaradas ($INSUNITS): '
            f'<b>{info.units or "não definidas"}</b>' +
            (f'<br>Extensão: X {ext[0]:.2f} … {ext[2]:.2f}, Y {ext[1]:.2f} … {ext[3]:.2f}'
             if ext else '')))
        v.addWidget(QLabel('Selecione as camadas a importar e as que serão apenas referência '
                           'visual (bloqueadas contra edição). Nenhuma linha é convertida em '
                           'tubulação nesta etapa.'))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['Importar', 'Referência', 'Camada', 'Entidades',
                                              'Tipos'])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        layers = [(n, d) for n, d in info.layers.items() if d['count'] > 0]
        self.table.setRowCount(len(layers))
        for r, (name, d) in enumerate(sorted(layers)):
            for c in (0, 1):
                it = QTableWidgetItem()
                it.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                it.setCheckState(Qt.Checked if c == 0 else Qt.Checked)
                self.table.setItem(r, c, it)
            it = QTableWidgetItem(name)
            it.setForeground(QColor(d['color']))
            self.table.setItem(r, 2, it)
            self.table.setItem(r, 3, QTableWidgetItem(str(d['count'])))
            self.table.setItem(r, 4, QTableWidgetItem(', '.join(
                f'{k}:{n}' for k, n in sorted(d['types'].items()))))
        v.addWidget(self.table, 1)
        form = QFormLayout()
        self.lock = QCheckBox('Bloquear camadas de referência')
        self.lock.setChecked(True)
        form.addRow(self.lock)
        self.explode = QCheckBox('Explodir blocos (INSERT) e cotas em geometria simples')
        self.explode.setChecked(True)
        form.addRow(self.explode)
        self.scale = QComboBox()
        self.scale.addItem('Preservar coordenadas originais (fator 1)', 1.0)
        f = unit_scale(info.units, 'm')
        if info.units and abs(f - 1.0) > 1e-12:
            self.scale.addItem(f'Converter {info.units} → m (fator {f:g})', f)
        self.custom = QDoubleSpinBox()
        self.custom.setDecimals(6)
        self.custom.setRange(1e-6, 1e6)
        self.custom.setValue(1.0)
        self.scale.addItem('Fator personalizado…', -1.0)
        form.addRow('Escala', self.scale)
        form.addRow('Fator personalizado', self.custom)
        v.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText('Importar')
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def options(self) -> DxfImportOptions:
        layers, refs = set(), set()
        for r in range(self.table.rowCount()):
            name = self.table.item(r, 2).text()
            if self.table.item(r, 0).checkState() == Qt.Checked:
                layers.add(name)
                if self.table.item(r, 1).checkState() == Qt.Checked:
                    refs.add(name)
        s = self.scale.currentData()
        if s < 0:
            s = self.custom.value()
        return DxfImportOptions(layers=layers, reference_layers=refs,
                                lock_reference=self.lock.isChecked(), scale=s,
                                explode_blocks=self.explode.isChecked())


class ConvertDialog(QDialog):
    """Parâmetros e pré-visualização da conversão de entidades CAD em tubulações."""

    def __init__(self, project, n_entities, planner, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Converter entidades CAD em tubulações')
        self.planner = planner
        self.plan = None
        v = QVBoxLayout(self)
        v.addWidget(QLabel(f'{n_entities} entidade(s) selecionada(s). Apenas linhas e '
                           'polilinhas são convertidas; o desenho original é mantido.'))
        form = QFormLayout()
        self.tol = QDoubleSpinBox()
        self.tol.setDecimals(4)
        self.tol.setRange(0.0001, 100)
        self.tol.setValue(max(project.settings.connect_tolerance, 0.01))
        self.tol.setSuffix(' m')
        form.addRow('Tolerância para unir extremidades', self.tol)
        self.reuse = QCheckBox('Conectar a nós existentes dentro da tolerância')
        self.reuse.setChecked(True)
        form.addRow(self.reuse)
        self.per_seg = QCheckBox('Um trecho por segmento (senão, um trecho por polilinha com '
                                 'vértices)')
        form.addRow(self.per_seg)
        self.diam = QDoubleSpinBox()
        self.diam.setRange(1, 5000)
        self.diam.setValue(100)
        self.diam.setSuffix(' mm')
        form.addRow('Diâmetro inicial', self.diam)
        self.rough = QDoubleSpinBox()
        self.rough.setRange(0.0001, 1000)
        self.rough.setValue(130)
        form.addRow('Rugosidade', self.rough)
        self.material = QLineEdit('PVC')
        form.addRow('Material', self.material)
        self.elev = QDoubleSpinBox()
        self.elev.setRange(-1000, 10000)
        self.elev.setDecimals(3)
        self.elev.setSuffix(' m')
        form.addRow('Cota das novas junções', self.elev)
        self.existing = QCheckBox('Marcar os trechos criados como existentes (executados)')
        self.existing.setToolTip('Use ao importar o cadastro da rede atual: a otimização não '
                                 'altera o diâmetro desses trechos.')
        form.addRow(self.existing)
        v.addLayout(form)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        v.addWidget(self.preview, 1)
        for w in (self.tol, self.diam, self.rough, self.elev):
            w.valueChanged.connect(self.update_plan)
        for w in (self.reuse, self.per_seg, self.existing):
            w.toggled.connect(self.update_plan)
        self.bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.bb.button(QDialogButtonBox.Ok).setText('Confirmar conversão')
        self.bb.accepted.connect(self.accept)
        self.bb.rejected.connect(self.reject)
        v.addWidget(self.bb)
        self.resize(560, 560)
        self.update_plan()

    def params(self):
        return dict(tol=self.tol.value(), reuse_existing=self.reuse.isChecked(),
                    per_segment=self.per_seg.isChecked(), diameter=self.diam.value(),
                    roughness=self.rough.value(), material=self.material.text(),
                    elevation=self.elev.value(), existing=self.existing.isChecked())

    def update_plan(self, *_):
        self.plan = self.planner(**self.params())
        p = self.plan
        lines = [f'Tubulações a criar: {p.n_pipes}'
                 + (' (marcadas como EXISTENTES)' if self.existing.isChecked() else ''),
                 f'Junções novas: {p.n_new_nodes}',
                 f'Nós existentes reaproveitados: {p.n_reused_nodes}',
                 f'Entidades ignoradas (não lineares ou degeneradas): {p.ignored}']
        if p.ambiguous:
            lines += ['', f'ATENÇÃO — {len(p.ambiguous)} conexão(ões) ambígua(s):'] + p.ambiguous
        lines += ['', 'Interseções no meio das linhas NÃO são conectadas automaticamente; a '
                      'validação aponta nós que tocam tubulações sem conexão.']
        self.preview.setPlainText('\n'.join(lines))
        self.bb.button(QDialogButtonBox.Ok).setEnabled(p.n_pipes > 0)
