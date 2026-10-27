"""Opções de simulação e configurações gerais do projeto."""

from __future__ import annotations

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QTabWidget, QVBoxLayout,
                               QWidget, QFormLayout)

from .forms import FieldForm


class SimOptionsDialog(QDialog):
    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Opções de simulação')
        self.project = project
        o = project.sim_options
        pats = [('', '(nenhum)')] + [(u, p.name) for u, p in project.network.patterns.items()]
        spec = [
            ('duration_h', 'Duração (h) — 0 = regime permanente', 'float',
             {'min': 0, 'max': 8760, 'decimals': 2}),
            ('hydraulic_step_h', 'Passo hidráulico (h)', 'float', {'min': 0.001, 'max': 24,
                                                                   'decimals': 3}),
            ('pattern_step_h', 'Passo dos padrões (h)', 'float', {'min': 0.001, 'max': 24,
                                                                  'decimals': 3}),
            ('report_step_h', 'Passo de relatório (h)', 'float', {'min': 0.001, 'max': 24,
                                                                  'decimals': 3}),
            ('start_clocktime_h', 'Hora de início (h)', 'float', {'min': 0, 'max': 24,
                                                                  'decimals': 2}),
            ('headloss', 'Fórmula de perda de carga', 'choice',
             {'choices': [('H-W', 'Hazen-Williams'), ('D-W', 'Darcy-Weisbach'),
                          ('C-M', 'Chezy-Manning')]}),
            ('trials', 'Máximo de iterações', 'int', {'min': 1, 'max': 10000}),
            ('accuracy', 'Precisão', 'float', {'min': 1e-6, 'max': 0.1, 'decimals': 6}),
            ('demand_multiplier', 'Multiplicador global de demanda (coef. de consumo)', 'float',
             {'min': 0, 'max': 100, 'decimals': 3}),
            ('viscosity', 'Viscosidade relativa', 'float', {'min': 0, 'max': 100}),
            ('specific_gravity', 'Densidade relativa', 'float', {'min': 0, 'max': 100}),
            ('default_pattern', 'Padrão de demanda padrão', 'choice', {'choices': pats}),
        ]
        limits = [
            ('pressure_min', 'Pressão mínima (m)', 'float', {'min': -100, 'max': 1000}),
            ('pressure_max', 'Pressão máxima (m)', 'float', {'min': 0, 'max': 1000}),
            ('velocity_min', 'Velocidade mínima (m/s) — 0 desativa', 'float', {'min': 0,
                                                                               'max': 50}),
            ('velocity_max', 'Velocidade máxima (m/s)', 'float', {'min': 0, 'max': 50}),
        ]
        tabs = QTabWidget()
        self.f1 = FieldForm(o, spec)
        self.f2 = FieldForm(o, limits)
        tabs.addTab(self.f1, 'Motor (EPANET)')
        w = QWidget()
        lv = QVBoxLayout(w)
        lv.addWidget(QLabel('Limites usados na verificação de restrições e nos destaques dos '
                            'mapas temáticos (não alteram o cálculo).'))
        lv.addWidget(self.f2)
        tabs.addTab(w, 'Limites de verificação')
        v = QVBoxLayout(self)
        v.addWidget(tabs)
        v.addWidget(QLabel('Simulação dirigida por pressão e qualidade da água: não integradas '
                           '(ver ANALISE_DO_PROJETO.md).'))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def accept(self):
        self.f1.apply()
        self.f2.apply()
        super().accept()


class SettingsDialog(QDialog):
    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Configurações')
        s = project.settings
        self.project = project
        spec_cad = [
            ('grid_spacing', 'Espaçamento da grade (m)', 'float', {'min': 0.001, 'max': 1e5}),
            ('grid_visible', 'Grade visível', 'bool', None),
            ('snap_grid', 'Snap à grade', 'bool', None),
            ('snap_nodes', 'Snap a nós', 'bool', None),
            ('snap_endpoints', 'Snap a extremidades e centros', 'bool', None),
            ('snap_midpoints', 'Snap a pontos médios', 'bool', None),
            ('snap_intersections', 'Snap a interseções', 'bool', None),
            ('snap_tolerance_px', 'Tolerância de snap (pixels)', 'float', {'min': 1, 'max': 50}),
            ('connect_tolerance', 'Tolerância de coincidência/conexão (m)', 'float',
             {'min': 0.0001, 'max': 100, 'decimals': 4,
              'tip': 'usada na validação e na conversão CAD → rede'}),
            ('auto_create_junction', 'Criar junção ao desenhar ligação em ponto vazio', 'bool',
             None),
            ('length_unit', 'Unidade de comprimento do desenho', 'choice',
             {'choices': [('m', 'metro (m)')]}),
        ]
        tabs = QTabWidget()
        self.f1 = FieldForm(s, spec_cad)
        tabs.addTab(self.f1, 'Desenho')
        w = QWidget()
        form = QFormLayout(w)
        self.py = QLineEdit(s.python_interpreter)
        self.py.setPlaceholderText('vazio = mesmo interpretador da interface')
        b = QPushButton('…')
        b.clicked.connect(lambda: self._pick(self.py, 'Python (python.exe python*)'))
        h = QHBoxLayout()
        h.addWidget(self.py)
        h.addWidget(b)
        form.addRow('Interpretador Python dos cálculos', h)
        self.script = QLineEdit(s.script_path)
        self.script.setPlaceholderText('vazio = main4.py da pasta do programa')
        b2 = QPushButton('…')
        b2.clicked.connect(lambda: self._pick(self.script, 'Python (*.py)'))
        h2 = QHBoxLayout()
        h2.addWidget(self.script)
        h2.addWidget(b2)
        form.addRow('Script de otimização', h2)
        form.addRow(QLabel('O interpretador precisa ter wntr e deap instalados '
                           '(requirements.txt).'))
        tabs.addTab(w, 'Integração')
        v = QVBoxLayout(self)
        v.addWidget(tabs)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _pick(self, edit, filt):
        path, _ = QFileDialog.getOpenFileName(self, 'Selecionar arquivo', edit.text(), filt)
        if path:
            edit.setText(path)

    def accept(self):
        try:
            self.f1.apply()
        except ValueError as e:
            QMessageBox.warning(self, 'Configurações', str(e))
            return
        self.project.settings.python_interpreter = self.py.text().strip()
        self.project.settings.script_path = self.script.text().strip()
        super().accept()
