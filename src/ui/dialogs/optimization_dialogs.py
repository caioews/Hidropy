"""Configuração da otimização (parâmetros reais de main4.py) e apresentação dos resultados."""

from __future__ import annotations

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel,
                               QMessageBox, QPlainTextEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
                               QAbstractItemView)

from ...results import tables
from ..results_panel import fill_table
from .forms import FieldForm


class OptimizationSettingsDialog(QDialog):
    """Cada campo corresponde a uma constante existente em main4.py (nome entre colchetes)."""

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Configurar otimização de diâmetros (main4.py)')
        self.resize(640, 640)
        self.project = project
        o = project.opt_settings
        ga = [
            ('semente', 'Semente aleatória [SEMENTE]', 'int', {'min': 0, 'max': 2 ** 31 - 1}),
            ('tam_populacao', 'Tamanho da população [TAM_POPULACAO]', 'int', {'min': 2,
                                                                             'max': 100000}),
            ('num_geracoes', 'Número de gerações [NUM_GERACOES]', 'int', {'min': 1,
                                                                         'max': 100000}),
            ('prob_cruzamento', 'Prob. de cruzamento [PROB_CRUZAMENTO]', 'float',
             {'min': 0, 'max': 1, 'step': 0.05}),
            ('prob_mutacao', 'Prob. de mutação do indivíduo [PROB_MUTACAO]', 'float',
             {'min': 0, 'max': 1, 'step': 0.05}),
            ('prob_mut_gene', 'Prob. de mutação por gene [PROB_MUT_GENE]', 'float_opt',
             {'placeholder': 'vazio = 2/nº de trechos (regra do script)'}),
            ('tam_torneio', 'Tamanho do torneio [TAM_TORNEIO]', 'int', {'min': 2, 'max': 100}),
            ('parada_sem_melhora', 'Parada: gerações sem melhora [PARADA_SEM_MELHORA]', 'int',
             {'min': 1, 'max': 100000}),
        ]
        cons = [
            ('pressao_min', 'Pressão mínima (mca) [PRESSAO_MIN]', 'float', {'min': 0}),
            ('pressao_max', 'Pressão máxima (mca) [PRESSAO_MAX]', 'float', {'min': 0}),
            ('tolerancia_pressao', 'Tolerância de pressão (mca) [TOLERANCIA_PRESSAO]', 'float',
             {'min': 0, 'decimals': 4}),
            ('perda_admitida_excecao', 'Perda admitida nos nós no limite topográfico (m) '
             '[PERDA_ADMITIDA_EXCECAO]', 'float', {'min': 0}),
            ('pressao_min_absoluta', 'Piso de pressão para aviso (mca) [PRESSAO_MIN_ABSOLUTA]',
             'float', {'min': 0}),
            ('velocidade_max', 'Velocidade máxima (m/s) [VELOCIDADE_MAX]', 'float', {'min': 0}),
            ('aplicar_limite_perda_unitaria', 'Penalizar perda unitária '
             '[APLICAR_LIMITE_PERDA_UNITARIA]', 'bool', None),
            ('perda_carga_max', 'Perda unitária máxima (m/km) [PERDA_CARGA_MAX]', 'float',
             {'min': 0}),
        ]
        rng = [
            ('dn_min_permitido', 'DN mínimo permitido [DN_MIN_PERMITIDO]', 'float_opt', None),
            ('dn_max_permitido', 'DN máximo permitido [DN_MAX_PERMITIDO]', 'float_opt', None),
            ('margem_dn_acima', 'Margem de degraus acima do DN necessário [MARGEM_DN_ACIMA]',
             'int', {'min': 0, 'max': 20}),
        ]
        tabs = QTabWidget()
        self.f_ga = FieldForm(o, ga)
        self.f_cons = FieldForm(o, cons)
        tabs.addTab(self.f_ga, 'Algoritmo genético')
        tabs.addTab(self.f_cons, 'Restrições e penalização')
        w = QWidget()
        lv = QVBoxLayout(w)
        self.f_rng = FieldForm(o, rng)
        lv.addWidget(self.f_rng)
        lv.addWidget(QLabel('Catálogo de diâmetros candidatos [CATALOGO_COMPLETO] — DN (mm), '
                            'diâmetro de cálculo (m), custo (R$/m):'))
        self.cat = QTableWidget(0, 3)
        self.cat.setHorizontalHeaderLabels(['DN (mm)', 'Diâmetro de cálculo (m)', 'Custo (R$/m)'])
        self.cat.verticalHeader().hide()
        for row in o.catalogo_completo:
            self._add_row(row)
        lv.addWidget(self.cat, 1)
        h = QHBoxLayout()
        for text, fn in (('Adicionar linha', lambda: self._add_row([0, 0.0, 0.0])),
                         ('Remover linha', self._del_row)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            h.addWidget(b)
        h.addStretch()
        lv.addLayout(h)
        lv.addWidget(QLabel('O incremento entre candidatos é definido pelas linhas do catálogo '
                            '(o script não possui parâmetro de incremento).'))
        tabs.addTab(w, 'Diâmetros candidatos e custos')
        v = QVBoxLayout(self)
        v.addWidget(tabs)
        n_fixed, L_fixed = tables.existing_summary(project)
        v.addWidget(QLabel(f'<b>Trechos existentes preservados</b> [TRECHOS_FIXOS]: {n_fixed} '
                           f'({L_fixed:,.1f} m) — mantêm o diâmetro e ficam fora do custo. '
                           'Marque-os em Rede hidráulica → Marcar trechos selecionados como '
                           'existentes.<br>Bombas e válvulas não são dimensionadas pelo script.'))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText('Salvar parâmetros')
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _add_row(self, row):
        r = self.cat.rowCount()
        self.cat.insertRow(r)
        for c, v in enumerate(row):
            self.cat.setItem(r, c, QTableWidgetItem(f'{v:g}'))

    def _del_row(self):
        rows = sorted({i.row() for i in self.cat.selectedIndexes()}, reverse=True)
        for r in rows:
            self.cat.removeRow(r)

    def accept(self):
        try:
            cat = []
            for r in range(self.cat.rowCount()):
                vals = [float(self.cat.item(r, c).text().replace(',', '.')) for c in range(3)]
                cat.append([int(vals[0]) if vals[0].is_integer() else vals[0], vals[1], vals[2]])
            if len(cat) < 1:
                raise ValueError('O catálogo precisa de pelo menos um diâmetro.')
            cat.sort(key=lambda c: c[1])
            if any(c[1] <= 0 or c[2] < 0 for c in cat):
                raise ValueError('Diâmetros devem ser > 0 e custos ≥ 0.')
            vals = {**self.f_ga.values(), **self.f_cons.values(), **self.f_rng.values()}
        except (ValueError, AttributeError) as e:
            QMessageBox.warning(self, 'Parâmetros inválidos', str(e))
            return
        if vals['prob_mut_gene'] is not None and not 0 <= vals['prob_mut_gene'] <= 1:
            QMessageBox.warning(self, 'Parâmetros inválidos', 'PROB_MUT_GENE deve estar em [0, 1].')
            return
        for k, v in vals.items():
            setattr(self.project.opt_settings, k, v)
        self.project.opt_settings.catalogo_completo = cat
        super().accept()


class OptimizationResultDialog(QDialog):
    """Mostra a solução do main4.py sem alterar o modelo; o usuário decide o que fazer."""

    VIEW, APPLY, SCENARIO = 1, 2, 3

    def __init__(self, ctrl, result, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Resultado da otimização (main4.py)')
        self.resize(1000, 640)
        self.ctrl = ctrl
        self.result = result
        self.choice = 0
        p = ctrl.project
        s = result.get('summary', {})
        v = QVBoxLayout(self)
        fixed = [d for d in result.get('pipes', {}).values() if d.get('fixed')]
        n_ex, L_ex = len(fixed), sum(d.get('length') or 0 for d in fixed)
        custo_orig = s.get('custo_original')
        econ = ''
        if custo_orig:
            econ = (f" — rede original pelo catálogo: R$ {custo_orig:,.2f} "
                    f"(diferença {100 * (s['custo'] - custo_orig) / custo_orig:+.1f}%)")
        v.addWidget(QLabel(
            f"<b>Custo da solução:</b> R$ {s.get('custo', 0):,.2f}{econ}<br>"
            f"<b>Viável:</b> {'SIM' if s.get('viavel') else 'NÃO'} — violação "
            f"{s.get('violacao', 0):.4g}; nós abaixo do alvo: {s.get('n_p_baixa')}; acima do "
            f"máximo: {s.get('n_p_alta')}; trechos acima de v máx.: {s.get('n_v_alta')}<br>"
            f"<b>Pressão</b> mín/máx: {s.get('p_min', 0):.2f} / {s.get('p_max', 0):.2f} m — "
            f"<b>velocidade máx.</b>: {s.get('v_max', 0):.3f} m/s — faixa de DN do script: "
            f"{s.get('faixa_dn')} — avaliações únicas: {s.get('avaliacoes_unicas')}<br>"
            f"<b>Trechos existentes preservados:</b> {n_ex} ({L_ex:,.1f} m) — diâmetro mantido "
            f"e fora do custo<br>"
            f"Script original inalterado: {'sim' if result.get('script_unchanged') else 'NÃO'}"))
        tabs = QTabWidget()
        self.t_pipes = QTableWidget()
        self.t_nodes = QTableWidget()
        for t in (self.t_pipes, self.t_nodes):
            t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.df_pipes = tables.optimization_df(p, result)
        self.df_nodes = tables.optimization_nodes_df(p, result)
        fill_table(self.t_pipes, self.df_pipes)
        fill_table(self.t_nodes, self.df_nodes)
        tabs.addTab(self.t_pipes, 'Trechos: original × otimizado')
        tabs.addTab(self.t_nodes, 'Nós: pressões antes × depois')
        logw = QPlainTextEdit(result.get('log', ''))
        logw.setReadOnly(True)
        tabs.addTab(logw, 'Saída do script')
        v.addWidget(tabs, 1)
        h = QHBoxLayout()
        for text, code, tip in (
                ('Visualizar no desenho (sem modificar)', self.VIEW,
                 'Colore a rede pela alteração de diâmetro; o modelo não é alterado.'),
                ('Aplicar diâmetros ao projeto atual', self.APPLY,
                 'Altera os diâmetros (pode ser desfeito). Exige nova simulação.'),
                ('Criar cenário otimizado', self.SCENARIO,
                 'Cria uma cópia da rede com os diâmetros otimizados.')):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, c=code: self._choose(c))
            h.addWidget(b)
        b = QPushButton('Exportar tabelas…')
        b.clicked.connect(self.export)
        h.addWidget(b)
        h.addStretch()
        b = QPushButton('Fechar')
        b.clicked.connect(self.reject)
        h.addWidget(b)
        v.addLayout(h)

    def _choose(self, code):
        self.choice = code
        self.accept()

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Exportar comparação', '',
                                              'Excel (*.xlsx);;CSV (*.csv)')
        if path:
            try:
                tables.export_many({'Trechos': self.df_pipes, 'Nos': self.df_nodes}, path)
            except Exception as e:
                QMessageBox.critical(self, 'Exportar', str(e))
