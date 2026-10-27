"""Projeção populacional (métodos aritmético e geométrico).

O estudo salvo fica no projeto (Project.population_studies) e o adotado será usado
no cálculo das vazões nodais.
"""

from __future__ import annotations

import copy
import datetime as _dt

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QSpinBox, QSplitter, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ...hydraulics.population import (BASES, METHODS, PopulationError, PopulationStudy,
                                      compute)
from ...hydraulics.project import now_iso


def parse_number(text: str) -> float:
    """Aceita 12345, 12.345, 12 345, 12.345,6 e 12345.6 (milhar com ponto, decimal com vírgula)."""
    t = text.strip().replace(' ', '').replace(' ', '')
    if ',' in t:
        t = t.replace('.', '').replace(',', '.')
    elif t.count('.') > 1 or (t.count('.') == 1 and len(t.split('.')[1]) == 3):
        t = t.replace('.', '')
    return float(t)


def fmt_dec(v, nd=2) -> str:
    """Número com vírgula decimal e ponto de milhar."""
    return f'{v:,.{nd}f}'.replace(',', '§').replace('.', ',').replace('§', '.')


def fmt_pop(v) -> str:
    """População em habitantes, com separador de milhar brasileiro."""
    return f'{v:,.0f}'.replace(',', '.') if v is not None else '—'


class PopulationDialog(QDialog):
    def __init__(self, ctrl, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.setWindowTitle('Projeção populacional')
        self.resize(1150, 700)
        self.study: PopulationStudy | None = None
        self._loading = False
        self._unsaved = False

        root = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel('Estudo:'))
        self.studies = QComboBox()
        self.studies.setMinimumWidth(320)
        top.addWidget(self.studies, 1)
        for text, fn in (('Novo estudo', self.new_study), ('Excluir estudo', self.delete_study)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            top.addWidget(b)
        root.addLayout(top)

        split = QSplitter(Qt.Horizontal)
        root.addWidget(split, 1)

        # ---------------------------------------------------------- entrada
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        box = QGroupBox('Dados censitários')
        bv = QVBoxLayout(box)
        self.census = QTableWidget(0, 2)
        self.census.setHorizontalHeaderLabels(['Ano', 'População (hab)'])
        self.census.verticalHeader().hide()
        self.census.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        bv.addWidget(self.census)
        hb = QHBoxLayout()
        for text, fn in (('+ censo', lambda: self.add_census()), ('− censo', self.del_census),
                         ('Colar', self.paste_census)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            hb.addWidget(b)
        bv.addLayout(hb)
        bv.addWidget(QLabel('Colar aceita linhas "ano;população" ou copiadas do Excel.'))
        lv.addWidget(box, 1)

        box = QGroupBox('Parâmetros')
        form = QFormLayout(box)
        self.name = QLineEdit()
        form.addRow('Nome do estudo', self.name)
        self.base = QComboBox()
        for k, t in BASES.items():
            self.base.addItem(t, k)
        self.base.setToolTip('Par de censos usado no cálculo dos coeficientes Ka e Kg.')
        form.addRow('Coeficientes a partir de', self.base)
        self.start = QSpinBox()
        self.end = QSpinBox()
        for s in (self.start, self.end):
            s.setRange(1800, 2300)
        form.addRow('Ano inicial do plano', self.start)
        form.addRow('Ano de alcance (horizonte)', self.end)
        self.step = QSpinBox()
        self.step.setRange(1, 50)
        self.step.setSuffix(' ano(s)')
        form.addRow('Passo da tabela', self.step)
        self.method = QComboBox()
        for k, t in METHODS.items():
            self.method.addItem(t, k)
        form.addRow('Método adotado', self.method)
        lv.addWidget(box)
        split.addWidget(left)

        # ---------------------------------------------------------- resultados
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.RichText)
        rv.addWidget(self.summary)
        inner = QSplitter(Qt.Vertical)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['Ano', 'Aritmético (hab)', 'Geométrico (hab)'])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        inner.addWidget(self.table)
        self.plot_host = QWidget()
        self._init_plot()
        inner.addWidget(self.plot_host)
        inner.setSizes([300, 320])
        rv.addWidget(inner, 1)
        split.addWidget(right)
        split.setSizes([380, 770])

        bottom = QHBoxLayout()
        b = QPushButton('Exportar tabela…')
        b.clicked.connect(self.export)
        bottom.addWidget(b)
        bottom.addStretch()
        self.btn_save = QPushButton('Salvar no projeto e adotar')
        self.btn_save.setDefault(True)
        self.btn_save.clicked.connect(self.save)
        bottom.addWidget(self.btn_save)
        b = QPushButton('Fechar')
        b.clicked.connect(self.close)
        bottom.addWidget(b)
        root.addLayout(bottom)

        self.census.itemChanged.connect(self._changed)
        for w in (self.start, self.end, self.step):
            w.valueChanged.connect(self._changed)
        for w in (self.base, self.method):
            w.currentIndexChanged.connect(self._changed)
        self.name.textEdited.connect(self._changed)
        self.studies.activated.connect(self._pick_study)

        self._fill_studies()
        adopted = self.ctrl.project.population_study()
        self.load(copy.deepcopy(adopted) if adopted else self._blank())

    # ------------------------------------------------------------------ estudos
    def _blank(self) -> PopulationStudy:
        y = _dt.date.today().year
        n = len(self.ctrl.project.population_studies) + 1
        return PopulationStudy(name=f'Projeção populacional {n}', start_year=y,
                               end_year=y + 20, step=1, adopted_method='geometrico')

    def _fill_studies(self, select: str = ''):
        p = self.ctrl.project
        self.studies.blockSignals(True)
        self.studies.clear()
        for s in p.population_studies:
            mark = '  [ADOTADO]' if s.uid == p.adopted_population else ''
            self.studies.addItem(f'{s.name} — {fmt_pop(s.design_population)} hab em '
                                 f'{s.end_year} ({METHODS[s.adopted_method]}){mark}', s.uid)
        if not p.population_studies:
            self.studies.addItem('(nenhum estudo salvo)', '')
        i = self.studies.findData(select or p.adopted_population)
        self.studies.setCurrentIndex(max(0, i))
        self.studies.blockSignals(False)

    def _confirm_discard(self) -> bool:
        if not self._unsaved:
            return True
        r = QMessageBox.question(self, 'Projeção populacional',
                                 'O estudo atual tem alterações não salvas. Salvar no projeto?',
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save()
        return r == QMessageBox.Discard

    def _pick_study(self, i):
        uid = self.studies.itemData(i)
        if not uid or (self.study and uid == self.study.uid):
            return
        if not self._confirm_discard():
            self._fill_studies(self.study.uid if self.study else '')
            return
        self.load(copy.deepcopy(self.ctrl.project.population_study(uid)))

    def new_study(self):
        if self._confirm_discard():
            self.load(self._blank())
            self._unsaved = True

    def delete_study(self):
        if self.study is None or self.ctrl.project.population_study(self.study.uid) is None:
            return
        if QMessageBox.question(self, 'Excluir estudo',
                                f"Excluir o estudo '{self.study.name}' do projeto?") \
                != QMessageBox.Yes:
            return
        self.ctrl.project.delete_population_study(self.study.uid)
        self.ctrl.mark_dirty()
        self._unsaved = False
        self._fill_studies()
        nxt = self.ctrl.project.population_study()
        self.load(copy.deepcopy(nxt) if nxt else self._blank())

    # ------------------------------------------------------------------ carga / edição
    def load(self, study: PopulationStudy):
        self._loading = True
        self.study = study
        self.name.setText(study.name)
        self.census.setRowCount(0)
        for year, pop in study.censuses:
            self.add_census(year, pop)
        self.base.setCurrentIndex(max(0, self.base.findData(study.base)))
        self.method.setCurrentIndex(max(0, self.method.findData(study.adopted_method)))
        self.start.setValue(int(study.start_year or _dt.date.today().year))
        self.end.setValue(int(study.end_year or self.start.value() + 20))
        self.step.setValue(int(study.step or 1))
        self._loading = False
        self._unsaved = False
        self.recompute()

    def add_census(self, year=None, pop=None):
        r = self.census.rowCount()
        self._loading, was = True, self._loading
        self.census.insertRow(r)
        self.census.setItem(r, 0, QTableWidgetItem('' if year is None else f'{year:g}'))
        self.census.setItem(r, 1, QTableWidgetItem('' if pop is None else f'{pop:g}'))
        self._loading = was
        if year is None:
            self.census.editItem(self.census.item(r, 0))

    def del_census(self):
        rows = sorted({i.row() for i in self.census.selectedIndexes()}, reverse=True)
        for r in rows:
            self.census.removeRow(r)
        self._changed()

    def paste_census(self):
        text = QGuiApplication.clipboard().text()
        rows = []
        for line in text.splitlines():
            bits = [b for b in line.replace(';', '\t').split('\t') if b.strip()]
            if len(bits) < 2:
                bits = line.split()
            try:
                rows.append((parse_number(bits[0]), parse_number(bits[1])))
            except (ValueError, IndexError):
                continue
        if not rows:
            QMessageBox.information(self, 'Colar', 'Nenhuma linha "ano população" encontrada na '
                                    'área de transferência.')
            return
        for y, p in rows:
            self.add_census(y, p)
        self._changed()

    def _read_censuses(self) -> list:
        out = []
        for r in range(self.census.rowCount()):
            a, b = self.census.item(r, 0), self.census.item(r, 1)
            ta = (a.text() if a else '').strip()
            tb = (b.text() if b else '').strip()
            if not ta and not tb:
                continue
            try:
                year = float(ta.replace(',', '.'))
                pop = parse_number(tb)
            except ValueError:
                raise PopulationError(f'Linha {r + 1} dos censos: valores inválidos.')
            out.append([year, pop])
        return out

    def _changed(self, *_):
        if self._loading:
            return
        self._unsaved = True
        self.recompute()

    def recompute(self) -> bool:
        s = self.study
        try:
            s.name = self.name.text().strip() or 'Projeção populacional'
            s.censuses = self._read_censuses()
            s.base = self.base.currentData()
            s.adopted_method = self.method.currentData()
            s.start_year, s.end_year, s.step = self.start.value(), self.end.value(), \
                self.step.value()
            compute(s)
        except PopulationError as e:
            s.ka = s.kg = None
            s.table = []
            self.summary.setText(f'<span style="color:#b00000">{e}</span>')
            self.table.setRowCount(0)
            self._draw()
            self.btn_save.setEnabled(False)
            return False
        self.btn_save.setEnabled(True)
        (t0, p0), (t1, p1) = (s.censuses[0], s.censuses[-1]) if s.base == 'extremos' else \
            (s.censuses[-2], s.censuses[-1])
        self.summary.setText(
            f'Base: censos de <b>{t0:g}</b> ({fmt_pop(p0)} hab) e <b>{t1:g}</b> '
            f'({fmt_pop(p1)} hab)<br>'
            f'<b>Aritmético:</b> Ka = {fmt_dec(s.ka)} hab/ano — P(t) = P₀ + Ka·(t − t₀)<br>'
            f'<b>Geométrico:</b> Kg = {fmt_dec(s.kg, 6)} /ano (taxa equivalente '
            f'{fmt_dec(100 * s.growth_rate, 3)}% a.a.) — P(t) = P₀·e^(Kg·(t − t₀))<br>'
            f'<b>População de projeto ({METHODS[s.adopted_method]}, {s.end_year}): '
            f'{fmt_pop(s.design_population)} hab</b>'
            + (f'<br><span style="color:#b00000">{s.notes}</span>' if s.notes else ''))
        self._fill_table()
        self._draw()
        return True

    def _fill_table(self):
        s = self.study
        self.table.setRowCount(len(s.table))
        bold = QFont()
        bold.setBold(True)
        col = {'aritmetico': 1, 'geometrico': 2}[s.adopted_method]
        for r, row in enumerate(s.table):
            items = [QTableWidgetItem(str(row['ano'])), QTableWidgetItem(fmt_pop(row['aritmetico'])),
                     QTableWidgetItem(fmt_pop(row['geometrico']))]
            for c, it in enumerate(items):
                it.setTextAlignment(Qt.AlignCenter)
                if c == col:
                    it.setFont(bold)
                    it.setBackground(QColor(44, 123, 182, 45))
                self.table.setItem(r, c, it)

    # ------------------------------------------------------------------ gráfico
    def _init_plot(self):
        lay = QVBoxLayout(self.plot_host)
        lay.setContentsMargins(0, 0, 0, 0)
        try:
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
            from matplotlib.figure import Figure
        except Exception as e:      # pragma: no cover
            self.fig = None
            lay.addWidget(QLabel(f'Gráfico indisponível: {e}'))
            return
        self.fig = Figure(figsize=(6, 3), tight_layout=True)
        self.fig_canvas = FigureCanvasQTAgg(self.fig)
        lay.addWidget(self.fig_canvas)

    def _draw(self):
        if self.fig is None:
            return
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        s = self.study
        if s.censuses:
            try:
                xs = [c[0] for c in s.censuses]
                ys = [c[1] for c in s.censuses]
                ax.plot(xs, ys, 'ko', label='Censos')
            except (TypeError, IndexError):
                pass
        if s.table and s.ka is not None:
            t0 = min(min(c[0] for c in s.censuses), s.start_year)
            years = list(range(int(t0), int(s.end_year) + 1))
            for m, color in (('aritmetico', '#2c7bb6'), ('geometrico', '#d7191c')):
                ax.plot(years, [s.population(y, m) for y in years], color=color,
                        lw=2.4 if m == s.adopted_method else 1.2,
                        label=METHODS[m] + (' (adotado)' if m == s.adopted_method else ''))
            ax.axvspan(s.start_year, s.end_year, color='#999999', alpha=0.12,
                       label='Horizonte do plano')
            ax.legend(loc='upper left', fontsize=8)
        ax.set_xlabel('Ano')
        ax.set_ylabel('População (hab)')
        ax.grid(True, alpha=0.3)
        ax.yaxis.set_major_formatter(lambda v, pos: fmt_pop(v))
        self.fig_canvas.draw_idle()

    # ------------------------------------------------------------------ ações
    def save(self) -> bool:
        if not self.recompute():
            QMessageBox.warning(self, 'Projeção populacional', 'Corrija os dados antes de salvar.')
            return False
        s = self.study
        s.created = now_iso()
        self.ctrl.project.save_population_study(copy.deepcopy(s), adopt=True)
        self.ctrl.mark_dirty()
        self._unsaved = False
        self._fill_studies(s.uid)
        self.ctrl.message.emit(f'Projeção salva e adotada: {fmt_pop(s.design_population)} hab em '
                               f'{s.end_year} ({METHODS[s.adopted_method]}).')
        return True

    def export(self):
        if not self.study or not self.study.table:
            return
        import pandas as pd
        from ...results import tables
        path, _ = QFileDialog.getSaveFileName(self, 'Exportar projeção', 'projecao.xlsx',
                                              'Excel (*.xlsx);;CSV (*.csv)')
        if not path:
            return
        s = self.study
        df = pd.DataFrame([{'Ano': r['ano'], 'Aritmético (hab)': round(r['aritmetico']),
                            'Geométrico (hab)': round(r['geometrico'])} for r in s.table])
        try:
            tables.export_df(df, path, 'Projecao')
        except Exception as e:
            QMessageBox.critical(self, 'Exportar', str(e))

    def closeEvent(self, ev):
        if self._confirm_discard():
            ev.accept()
        else:
            ev.ignore()

    def reject(self):
        self.close()
