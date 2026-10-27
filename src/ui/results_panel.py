"""Painel de resultados: mapa temático, instante de visualização, tabelas, gráfico temporal."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QInputDialog,
                               QLabel, QMessageBox, QPlainTextEdit, QPushButton, QSlider,
                               QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget, QAbstractItemView)

from ..results import tables, thematic_views as TV


class NumItem(QTableWidgetItem):
    """Número exibido com casas fixas (sem notação científica) e ordenado pelo valor."""

    def __init__(self, value: float):
        super().__init__(_fmt(value))
        self.value = value
        self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def __lt__(self, other):
        if isinstance(other, NumItem):
            return self.value < other.value
        return False                     # células vazias ficam depois dos números


def _fmt(v: float) -> str:
    from PySide6.QtCore import QLocale
    loc = QLocale()
    loc.setNumberOptions(QLocale.OmitGroupSeparator)
    txt = loc.toString(float(v), 'f', 4)
    dec = loc.decimalPoint()
    if dec in txt:
        txt = txt.rstrip('0').rstrip(dec)
    return txt


def fill_table(table: QTableWidget, df):
    table.setSortingEnabled(False)
    table.clear()
    table.setRowCount(len(df))
    table.setColumnCount(len(df.columns))
    table.setHorizontalHeaderLabels([str(c) for c in df.columns])
    for r, row in enumerate(df.itertuples(index=False)):
        for c, v in enumerate(row):
            if isinstance(v, float):
                it = NumItem(v) if v == v else QTableWidgetItem('')   # NaN => vazio
            else:
                it = QTableWidgetItem('' if v is None else str(v))
            table.setItem(r, c, it)
    table.setSortingEnabled(True)
    table.resizeColumnsToContents()


class ResultsPanel(QWidget):
    themeChanged = Signal()

    def __init__(self, controller, canvas, parent=None):
        super().__init__(parent)
        self.ctrl = controller
        self.canvas = canvas
        v = QVBoxLayout(self)
        v.setContentsMargins(2, 2, 2, 2)
        self.status = QLabel('Sem resultados.')
        self.status.setWordWrap(True)
        v.addWidget(self.status)

        h = QHBoxLayout()
        h.addWidget(QLabel('Nós:'))
        self.node_var = QComboBox()
        for k, t in TV.NODE_VARS.items():
            self.node_var.addItem(t, k)
        h.addWidget(self.node_var)
        h.addWidget(QLabel('Ligações:'))
        self.link_var = QComboBox()
        for k, t in TV.LINK_VARS.items():
            self.link_var.addItem(t, k)
        h.addWidget(self.link_var)
        v.addLayout(h)
        h = QHBoxLayout()
        self.highlight = QCheckBox('Destacar fora dos limites')
        self.highlight.setChecked(True)
        h.addWidget(self.highlight)
        h.addWidget(QLabel('Classes:'))
        self.classes = QSpinBox()
        self.classes.setRange(2, 7)
        self.classes.setValue(5)
        h.addWidget(self.classes)
        b = QPushButton('Faixas…')
        b.setToolTip('Definir limites das classes manualmente (vazio = automático)')
        b.clicked.connect(self.edit_breaks)
        h.addWidget(b)
        h.addStretch()
        v.addLayout(h)
        h = QHBoxLayout()
        h.addWidget(QLabel('Instante:'))
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        h.addWidget(self.slider, 1)
        self.time_lbl = QLabel('0,00 h')
        h.addWidget(self.time_lbl)
        v.addLayout(h)

        self.tabs = QTabWidget()
        self.nodes_tab = QTableWidget()
        self.links_tab = QTableWidget()
        for t in (self.nodes_tab, self.links_tab):
            t.setEditTriggers(QAbstractItemView.NoEditTriggers)
            t.setSelectionBehavior(QAbstractItemView.SelectRows)
            t.cellDoubleClicked.connect(self._row_activated)
        self.tabs.addTab(self.nodes_tab, 'Nós')
        self.tabs.addTab(self.links_tab, 'Trechos')
        self.plot_host = QWidget()
        self._plot_ready = False
        self.tabs.addTab(self.plot_host, 'Gráfico temporal')
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.tabs.addTab(self.summary, 'Resumo / restrições')
        v.addWidget(self.tabs, 1)
        h = QHBoxLayout()
        b = QPushButton('Exportar resultados (planilha)…')
        b.clicked.connect(self.export)
        h.addWidget(b)
        h.addStretch()
        v.addLayout(h)

        self.node_breaks = None
        self.link_breaks = None
        for w in (self.node_var, self.link_var):
            w.currentIndexChanged.connect(self.apply_theme)
        self.highlight.toggled.connect(self.apply_theme)
        self.classes.valueChanged.connect(self.apply_theme)
        self.slider.valueChanged.connect(self._time_changed)
        self.tabs.currentChanged.connect(lambda i: self.update_plot())
        self.ctrl.resultsChanged.connect(self.refresh)
        self.ctrl.elementsChanged.connect(lambda cs: self.refresh_status())
        self.ctrl.projectReplaced.connect(self.refresh)
        self.ctrl.selectionChanged.connect(lambda *_: self.update_plot())
        self.refresh()

    # ------------------------------------------------------------------
    def sim(self):
        return self.ctrl.project.latest_result('simulation')

    def opt(self):
        return self.canvas.theme_opt or self.ctrl.project.latest_result('optimization')

    def set_vars(self, node_var=None, link_var=None):
        if node_var is not None:
            self.node_var.setCurrentIndex(max(0, self.node_var.findData(node_var)))
        if link_var is not None:
            self.link_var.setCurrentIndex(max(0, self.link_var.findData(link_var)))
        self.apply_theme()

    def apply_theme(self):
        cfg = TV.ThemeConfig(node_var=self.node_var.currentData() or '',
                             link_var=self.link_var.currentData() or '',
                             time_index=self.slider.value(),
                             node_breaks=self.node_breaks, link_breaks=self.link_breaks,
                             highlight_limits=self.highlight.isChecked(),
                             classes=self.classes.value())
        self.canvas.set_theme(cfg)
        self.themeChanged.emit()

    def edit_breaks(self):
        which, ok = QInputDialog.getItem(self, 'Faixas', 'Aplicar a:', ['Nós', 'Ligações'], 0,
                                         False)
        if not ok:
            return
        cur = self.node_breaks if which == 'Nós' else self.link_breaks
        text, ok = QInputDialog.getText(self, 'Faixas', 'Limites crescentes separados por ";" '
                                        '(vazio = automático):',
                                        text='; '.join(f'{b:g}' for b in (cur or [])))
        if not ok:
            return
        try:
            vals = [float(t.replace(',', '.')) for t in text.split(';') if t.strip()]
        except ValueError:
            QMessageBox.warning(self, 'Faixas', 'Valores inválidos.')
            return
        if vals != sorted(vals):
            QMessageBox.warning(self, 'Faixas', 'Os limites devem ser crescentes.')
            return
        if which == 'Nós':
            self.node_breaks = vals or None
        else:
            self.link_breaks = vals or None
        self.apply_theme()

    def _time_changed(self, v):
        sim = self.sim()
        times = sim.get('times', [0]) if sim else [0]
        t = times[min(v, len(times) - 1)] if times else 0
        self.time_lbl.setText(f'{t / 3600:.2f} h')
        self.apply_theme()
        self.fill_tables()

    def refresh(self):
        sim = self.sim()
        n = len(sim.get('times', [])) if sim else 0
        self.slider.blockSignals(True)
        self.slider.setRange(0, max(0, n - 1))
        self.slider.setEnabled(n > 1)
        self.slider.blockSignals(False)
        self.refresh_status()
        self.apply_theme()
        self.fill_tables()
        self.update_plot()

    def refresh_status(self):
        sim, opt = self.sim(), self.ctrl.project.latest_result('optimization')
        parts = []
        if sim:
            parts.append(f"Simulação de {sim['created'].replace('T', ' ')} — "
                         f"{len(sim.get('times', []))} instante(s)")
        else:
            parts.append('Nenhuma simulação bem-sucedida neste cenário.')
        if opt:
            parts.append(f"Otimização de {opt['created'].replace('T', ' ')}")
        self.status.setText('<br>'.join(parts))

    def fill_tables(self):
        p = self.ctrl.project
        sim = self.sim()
        t = self.slider.value()
        fill_table(self.nodes_tab, tables.node_results_df(p, sim, t))
        fill_table(self.links_tab, tables.link_results_df(p, sim, t))
        self.summary.setPlainText(self._summary_text(sim))

    def _summary_text(self, sim) -> str:
        p = self.ctrl.project
        if not sim:
            return 'Sem simulação.'
        o = p.sim_options
        lines = [f"Motor: {sim.get('engine')}   Instantes: {len(sim.get('times', []))}"]
        pres = [v for d in (sim['nodes'][u] for u in sim['nodes']
                            if p.network.nodes.get(u) and p.network.nodes[u].KIND == 'junction')
                for v in (d.get('pressure') or []) if v is not None]
        vel = [abs(v) for d in sim['links'].values() for v in (d.get('velocity') or [])
               if v is not None]
        if pres:
            lines.append(f'Pressão nas junções (período): mín {min(pres):.2f} m, '
                         f'máx {max(pres):.2f} m')
        if vel:
            lines.append(f'Velocidade (período): máx {max(vel):.3f} m/s')
        v = TV.violations(p, sim)
        net = p.network

        def names(us):
            return ', '.join(sorted((net.nodes.get(u) or net.links.get(u)).name for u in us
                                    if (net.nodes.get(u) or net.links.get(u))))
        lines.append('')
        lines.append(f'Limites: pressão {o.pressure_min:g}–{o.pressure_max:g} m, '
                     f'velocidade ≤ {o.velocity_max:g} m/s'
                     + (f', ≥ {o.velocity_min:g} m/s' if o.velocity_min > 0 else ''))
        lines.append(f"Pressão abaixo do mínimo: {len(v['p_low'])} {names(v['p_low'])}")
        lines.append(f"Pressão acima do máximo: {len(v['p_high'])} {names(v['p_high'])}")
        lines.append(f"Velocidade acima do máximo: {len(v['v_high'])} {names(v['v_high'])}")
        if o.velocity_min > 0:
            lines.append(f"Velocidade abaixo do mínimo: {len(v['v_low'])} {names(v['v_low'])}")
        lines.append(f"Inversão de sentido no período: {len(v['reverse'])} {names(v['reverse'])}")
        neg = [u for u, d in sim['links'].items()
               if (TV.value_at(d.get('flow'), self.slider.value()) or 0) < 0]
        lines.append(f'Vazão negativa (sentido contrário ao cadastro) no instante: {len(neg)}')
        if sim.get('warnings'):
            lines.append('')
            lines.append('Advertências do EPANET:')
            lines += sim['warnings'][:200]
        if sim.get('unmapped'):
            lines.append(f"Resultados sem elemento correspondente: {sim['unmapped']}")
        return '\n'.join(lines)

    def _row_activated(self, row, col):
        table = self.sender()
        name = table.item(row, 0).text()
        coll = 'node' if table is self.nodes_tab else 'link'
        e = self.ctrl.project.network.find_by_name(name, coll)
        if e is not None:
            self.ctrl.set_selection([e.uid], 'results')
            self.canvas.zoom_to([e.uid])

    # ------------------------------------------------------------------ gráfico
    def _ensure_plot(self):
        if self._plot_ready:
            return True
        try:
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
            from matplotlib.figure import Figure
        except Exception as e:     # pragma: no cover
            lay = QVBoxLayout(self.plot_host)
            lay.addWidget(QLabel(f'Matplotlib indisponível: {e}'))
            self._plot_ready = None
            return False
        lay = QVBoxLayout(self.plot_host)
        h = QHBoxLayout()
        h.addWidget(QLabel('Variável:'))
        self.plot_var = QComboBox()
        h.addWidget(self.plot_var, 1)
        lay.addLayout(h)
        self.fig = Figure(figsize=(5, 3), tight_layout=True)
        self.fig_canvas = FigureCanvasQTAgg(self.fig)
        lay.addWidget(self.fig_canvas, 1)
        self.plot_var.currentIndexChanged.connect(lambda i: self._draw_plot())
        self._plot_ready = True
        return True

    def update_plot(self):
        if self.tabs.currentWidget() is not self.plot_host:
            return
        if not self._ensure_plot():
            return
        sel = self.ctrl.selected_elements()
        e = sel[0] if sel else None
        opts = []
        if e is not None and e.COLLECTION == 'node':
            opts = [('pressure', 'Pressão (m)'), ('head', 'Carga (m)'),
                    ('demand', 'Demanda (L/s)')]
            if e.KIND == 'tank':
                opts.insert(0, ('level', 'Nível (m)'))
        elif e is not None and e.COLLECTION == 'link':
            opts = [('flow', 'Vazão (L/s)'), ('velocity', 'Velocidade (m/s)'),
                    ('unit_headloss', 'Perda unitária (m/km)'), ('headloss', 'Perda (m)'),
                    ('status', 'Estado')]
        cur = self.plot_var.currentData()
        self.plot_var.blockSignals(True)
        self.plot_var.clear()
        for k, t in opts:
            self.plot_var.addItem(t, k)
        i = self.plot_var.findData(cur)
        self.plot_var.setCurrentIndex(i if i >= 0 else 0)
        self.plot_var.blockSignals(False)
        self._draw_plot()

    def _draw_plot(self):
        if not self._plot_ready:
            return
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        sim = self.sim()
        sel = self.ctrl.selected_elements()
        var = self.plot_var.currentData()
        if not sim or not sel or not var:
            ax.text(0.5, 0.5, 'Selecione um nó ou ligação após simular.', ha='center',
                    va='center', transform=ax.transAxes)
            self.fig_canvas.draw_idle()
            return
        e = sel[0]
        store = sim.get('nodes' if e.COLLECTION == 'node' else 'links', {})
        series = (store.get(e.uid) or {}).get(var)
        if not series:
            ax.text(0.5, 0.5, 'Variável não calculada para este elemento.', ha='center',
                    va='center', transform=ax.transAxes)
        else:
            hrs = [t / 3600 for t in sim['times']]
            ax.plot(hrs, [v if v is not None else float('nan') for v in series], marker='.')
            ax.axvline(hrs[min(self.slider.value(), len(hrs) - 1)], color='#999', ls='--')
            ax.set_xlabel('Tempo (h)')
            ax.set_ylabel(self.plot_var.currentText())
            ax.set_title(e.name)
            ax.grid(True, alpha=0.3)
            o = self.ctrl.project.sim_options
            if var == 'pressure' and e.KIND == 'junction':
                ax.axhline(o.pressure_min, color='#d7191c', lw=0.8)
            if var == 'level' and e.KIND == 'tank':
                ax.axhline(e.min_level, color='#d7191c', lw=0.8)
                ax.axhline(e.max_level, color='#d7191c', lw=0.8)
        self.fig_canvas.draw_idle()

    # ------------------------------------------------------------------
    def export(self):
        """Planilha com os resultados de nós e trechos (abas 'Nos' e 'Trechos')."""
        p = self.ctrl.project
        sim = self.sim()
        if not sim:
            QMessageBox.information(self, 'Exportar resultados',
                                    'Execute uma simulação antes de exportar os resultados.')
            return
        all_times = False
        n = len(sim.get('times', []))
        if n > 1:
            t_now = sim['times'][min(self.slider.value(), n - 1)] / 3600
            opts = [f'Instante selecionado ({t_now:.2f} h)', f'Todos os instantes ({n})']
            choice, ok = QInputDialog.getItem(self, 'Exportar resultados', 'Exportar:', opts, 0,
                                              False)
            if not ok:
                return
            all_times = choice == opts[1]
        path, _ = QFileDialog.getSaveFileName(self, 'Exportar resultados (planilha)',
                                              'resultados.xlsx', 'Excel (*.xlsx);;CSV (*.csv)')
        if not path:
            return
        if not path.lower().endswith(('.xlsx', '.csv')):
            path += '.xlsx'
        try:
            out = tables.export_results(p, sim, path, self.slider.value(), all_times)
        except Exception as e:
            QMessageBox.critical(self, 'Exportar resultados', f'Falha ao exportar: {e}')
            return
        QMessageBox.information(self, 'Exportar resultados', 'Gerado(s):\n' + '\n'.join(out))
