"""Janela principal: menus, barras de ferramentas, painéis, arquivos e execução dos cálculos."""

from __future__ import annotations

import logging
import os

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (QDockWidget, QFileDialog, QInputDialog, QLabel, QMainWindow,
                               QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QToolBar,
                               QDialog, QVBoxLayout, QCheckBox, QDialogButtonBox)

from ..cad import drawing_tools as T
from ..cad.canvas import CadCanvas
from ..hydraulics import editing
from ..hydraulics.models import KIND_LABELS
from ..hydraulics.project import Project
from ..hydraulics.project_io import (EXTENSION, ProjectFormatError, load_project, save_project)
from ..hydraulics.validation import has_errors
from ..integration import optimization_adapter
from ..results import reports
from .command_line import CommandLine
from .controller import DocumentController
from .element_table import ElementTable
from .layers_panel import LayersPanel
from .network_tree import NetworkTree
from .properties_panel import PropertiesPanel
from .results_panel import ResultsPanel
from .run_controller import RunController
from .validation_panel import ValidationPanel
from . import toolbar as TB

log = logging.getLogger(__name__)
APP_NAME = 'HidroPy'


class MainWindow(QMainWindow):
    def __init__(self, project: Project | None = None):
        super().__init__()
        self.ctrl = DocumentController(project or Project())
        self.canvas = CadCanvas(self.ctrl)
        self.setCentralWidget(self.canvas)
        self.runner = RunController(self.ctrl, self)
        self.resize(1500, 920)
        self._build_docks()
        self._build_status()
        self._build_actions()
        self._build_menus()
        self._build_toolbars()
        self._connect()
        self.canvas.rebuild()
        self.activate_tool('select')
        self.update_title()
        self.update_counts()

    # ================================================================== montagem
    def _dock(self, title, widget, area, name):
        d = QDockWidget(title, self)
        d.setObjectName(name)
        d.setWidget(widget)
        self.addDockWidget(area, d)
        return d

    def _build_docks(self):
        self.tree = NetworkTree(self.ctrl)
        self.props = PropertiesPanel(self.ctrl, self.canvas)
        self.layers = LayersPanel(self.ctrl)
        self.results = ResultsPanel(self.ctrl, self.canvas)
        self.validation = ValidationPanel(self.ctrl)
        self.table = ElementTable(self.ctrl, self.canvas)
        self.logw = QPlainTextEdit()
        self.logw.setReadOnly(True)
        self.logw.setMaximumBlockCount(20000)
        self.setCorner(Qt.BottomLeftCorner, Qt.LeftDockWidgetArea)
        self.setCorner(Qt.BottomRightCorner, Qt.RightDockWidgetArea)
        self.d_tree = self._dock('Rede', self.tree, Qt.LeftDockWidgetArea, 'tree')
        self.d_props = self._dock('Propriedades', self.props, Qt.RightDockWidgetArea, 'props')
        self.d_layers = self._dock('Camadas', self.layers, Qt.RightDockWidgetArea, 'layers')
        self.tabifyDockWidget(self.d_props, self.d_layers)
        self.d_props.raise_()
        self.d_results = self._dock('Resultados', self.results, Qt.RightDockWidgetArea,
                                    'results')
        self.d_valid = self._dock('Validação', self.validation, Qt.BottomDockWidgetArea, 'valid')
        self.d_log = self._dock('Log de execução', self.logw, Qt.BottomDockWidgetArea, 'log')
        self.d_table = self._dock('Tabela de elementos', self.table, Qt.BottomDockWidgetArea,
                                  'table')
        self.tabifyDockWidget(self.d_valid, self.d_log)
        self.tabifyDockWidget(self.d_log, self.d_table)
        self.d_valid.raise_()
        QTimer.singleShot(0, self._initial_dock_sizes)
        self.cmd = CommandLine(self.canvas)
        tb = QToolBar('Coordenadas', self)
        tb.setObjectName('cmdline')
        tb.addWidget(self.cmd)
        self.addToolBar(Qt.BottomToolBarArea, tb)

    def _initial_dock_sizes(self):
        w = max(self.width(), 1000)
        self.resizeDocks([self.d_tree], [int(w * 0.15)], Qt.Horizontal)
        self.resizeDocks([self.d_props], [int(w * 0.24)], Qt.Horizontal)
        self.resizeDocks([self.d_props, self.d_results], [int(self.height() * 0.45),
                                                          int(self.height() * 0.45)], Qt.Vertical)
        self.resizeDocks([self.d_valid], [int(self.height() * 0.2)], Qt.Vertical)
        self.canvas.fit_all()

    def _build_status(self):
        sb = self.statusBar()
        self.st_msg = QLabel('')
        self.st_coord = QLabel('X: —  Y: —')
        self.st_snap = QLabel('')
        self.st_zoom = QLabel('')
        self.st_unit = QLabel('Unidade: m')
        self.st_count = QLabel('')
        self.st_project = QLabel('')
        self.st_sim = QLabel('Simulação: —')
        self.st_valid = QLabel('Validação: —')
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(170)
        self.progress.setVisible(False)
        self.btn_cancel = QPushButton('Cancelar')
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self.runner.cancel)
        sb.addWidget(self.st_msg, 1)
        for w in (self.st_coord, self.st_snap, self.st_zoom, self.st_unit, self.st_count,
                  self.st_project, self.st_sim, self.st_valid, self.progress, self.btn_cancel):
            sb.addPermanentWidget(w)

    def _act(self, text, slot=None, shortcut=None, checkable=False, tip='', checked=False):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if checkable:
            a.setCheckable(True)
            a.setChecked(checked)
        if tip:
            a.setStatusTip(tip)
            a.setToolTip(f'{text} — {tip}' if tip else text)
        if slot:
            a.triggered.connect(slot)
        return a

    def _build_actions(self):
        A = self._act
        s = self.ctrl.project.settings
        self.a = {}
        a = self.a
        a['new'] = A('Novo projeto', self.file_new, 'Ctrl+N')
        a['open'] = A('Abrir projeto…', self.file_open, 'Ctrl+O')
        a['save'] = A('Salvar', self.file_save, 'Ctrl+S')
        a['saveas'] = A('Salvar como…', self.file_save_as, 'Ctrl+Shift+S')
        a['import_dxf'] = A('Importar DXF…', self.import_dxf, 'Ctrl+I')
        a['export_dxf'] = A('Exportar DXF…', self.export_dxf)
        a['import_inp'] = A('Importar rede EPANET (.inp)…', self.import_inp)
        a['export_inp'] = A('Exportar rede EPANET (.inp)…', self.export_inp)
        a['quit'] = A('Sair', self.close, 'Ctrl+Q')
        a['undo'] = self.ctrl.undo_stack.createUndoAction(self, 'Desfazer')
        a['undo'].setShortcut(QKeySequence.Undo)
        a['redo'] = self.ctrl.undo_stack.createRedoAction(self, 'Refazer')
        a['redo'].setShortcuts([QKeySequence('Ctrl+Y'), QKeySequence('Ctrl+Shift+Z')])
        a['copy'] = A('Copiar', self.edit_copy, 'Ctrl+C')
        a['paste'] = A('Colar (no cursor)', self.edit_paste, 'Ctrl+V')
        a['delete'] = A('Excluir', self.edit_delete, 'Del')
        a['selall'] = A('Selecionar tudo', self.edit_select_all, 'Ctrl+A')
        a['move'] = A('Mover por deslocamento…', self.edit_move, 'Ctrl+M')
        a['rotate'] = A('Rotacionar…', self.edit_rotate, 'Ctrl+R')
        a['mirror'] = A('Espelhar…', self.edit_mirror)
        a['fit'] = A('Ajustar à rede (zoom total)', self.canvas.fit_all, 'Home')
        a['zoom_sel'] = A('Zoom na seleção', lambda: self.canvas.zoom_to(self.ctrl.selection),
                          'Ctrl+Home')
        a['zoom_in'] = A('Aproximar', lambda: self.canvas.scale_view(1.25), 'Ctrl++')
        a['zoom_out'] = A('Afastar', lambda: self.canvas.scale_view(0.8), 'Ctrl+-')

        def toggle(key, label, attr, shortcut=None):
            a[key] = A(label, None, shortcut, checkable=True, checked=getattr(s, attr))
            a[key].toggled.connect(lambda v, at=attr: self._set_setting(at, v))
        toggle('grid', 'Grade', 'grid_visible', 'F7')
        toggle('snap_grid', 'Snap à grade', 'snap_grid', 'F9')
        toggle('snap_obj', 'Snap a objetos (nós e extremidades)', 'snap_endpoints', 'F3')
        toggle('lbl_nodes', 'Nomes dos nós', 'show_node_labels')
        toggle('lbl_links', 'Nomes das tubulações', 'show_link_labels')
        toggle('lbl_diam', 'Diâmetros', 'show_diameters')
        toggle('lbl_press', 'Pressões', 'show_pressures')
        toggle('lbl_flow', 'Vazões', 'show_flows')
        toggle('lbl_vel', 'Velocidades', 'show_velocities')
        toggle('arrows', 'Setas de escoamento', 'show_flow_arrows')
        toggle('symbols', 'Símbolos hidráulicos', 'show_symbols')
        toggle('refs', 'Camadas de referência', 'show_reference_layers')

        self.tool_group = QActionGroup(self)
        self.tool_actions = {}

        def tool(key, label, shortcut=None, tip=''):
            act = A(label, lambda checked=False, k=key: self.activate_tool(k), shortcut,
                    checkable=True, tip=tip)
            self.tool_group.addAction(act)
            self.tool_actions[key] = act
            a['tool_' + key] = act
        tool('select', 'Selecionar', 'Esc')
        tool('pan', 'Pan')
        tool('line', 'Linha', 'L')
        tool('polyline', 'Polilinha', 'Shift+L')
        tool('rect', 'Retângulo', 'Shift+R')
        tool('circle', 'Círculo', 'Shift+C')
        tool('arc', 'Arco (3 pontos)', 'Shift+A')
        tool('text', 'Texto', 'Shift+T')
        tool('dimension', 'Cota', 'Shift+D')
        tool('measure', 'Medir distância', 'M')
        tool('junction', 'Inserir junção', 'J')
        tool('reservoir', 'Inserir reservatório', 'R')
        tool('tank', 'Inserir tanque', 'T')
        tool('pipe', 'Desenhar tubulação', 'P')
        tool('pump', 'Inserir bomba', 'B')
        tool('valve', 'Inserir válvula', 'V')
        tool('split', 'Dividir tubulação')

        a['mark_existing'] = A('Marcar trechos selecionados como existentes',
                               lambda: self.mark_existing(True), 'Ctrl+Shift+E',
                               tip='Trechos executados: a otimização não altera o diâmetro')
        a['mark_projected'] = A('Marcar trechos selecionados como projetados',
                                lambda: self.mark_existing(False), 'Ctrl+Shift+P')
        a['convert'] = A('Converter entidades CAD em tubulações…', self.convert_cad)
        a['curves'] = A('Curvas…', lambda: self.open_editor('curve', ''))
        a['patterns'] = A('Padrões temporais…', lambda: self.open_editor('pattern', ''))
        a['controls'] = A('Controles…', lambda: self.open_editor('control', ''))
        a['scenarios'] = A('Cenários…', self.open_scenarios)
        a['validate'] = A('Validar rede', self.run_validation, 'F4')
        a['table'] = A('Tabela de elementos', lambda: (self.d_table.show(), self.d_table.raise_()))
        a['population'] = A('Projeção populacional…', self.population_projection,
                            tip='Métodos aritmético e geométrico; o estudo adotado fica salvo '
                                'no projeto')
        a['nodal_demand'] = A('Consumos nodais (método linear)…', self.nodal_demands,
                              tip='Distribui a vazão da população projetada pelos nós, '
                                  'proporcional à extensão de rede')
        a['sim_opts'] = A('Opções de simulação…', self.sim_options)
        a['simulate'] = A('Executar simulação', self.run_simulation, 'F5')
        a['opt_cfg'] = A('Configurar otimização…', self.opt_settings)
        a['optimize'] = A('Executar otimização (main4.py)', self.run_optimization, 'F6')
        a['opt_last'] = A('Ver último resultado da otimização…', self.show_last_optimization)
        a['cancel'] = A('Cancelar cálculo em execução', self.runner.cancel)
        a['results'] = A('Painel de resultados', lambda: (self.d_results.show(),
                                                         self.d_results.raise_()))
        a['th_press'] = A('Mapa: pressão nos nós', lambda: self.results.set_vars('pressure', None))
        a['th_vel'] = A('Mapa: velocidade', lambda: self.results.set_vars(None, 'velocity'))
        a['th_flow'] = A('Mapa: vazão (com setas)', self.theme_flow)
        a['th_diam'] = A('Mapa: diâmetro cadastrado', lambda: self.results.set_vars(None,
                                                                                    'diameter'))
        a['th_diam_opt'] = A('Mapa: diâmetro otimizado',
                             lambda: self.results.set_vars(None, 'opt_diameter'))
        a['th_existing'] = A('Mapa: trechos existentes × projetados',
                             lambda: self.results.set_vars(None, 'existing'))
        a['th_change'] = A('Mapa: alteração de diâmetro (otimização)',
                           lambda: self.results.set_vars(None, 'diam_change'))
        a['th_clear'] = A('Limpar mapa temático', lambda: self.results.set_vars('', ''))
        a['report'] = A('Gerar relatório…', self.make_report)
        a['export_res'] = A('Exportar resultados de nós e trechos (planilha)…',
                            self.results.export, 'Ctrl+E')
        a['runs_dir'] = A('Abrir pasta de execuções', self.open_runs_dir)
        a['logfile'] = A('Abrir arquivo de log', self.open_logfile)
        a['settings'] = A('Configurações…', self.settings_dialog)
        a['readme'] = A('Manual do HidroPy', self.open_readme, 'F1')
        a['about'] = A('Sobre o HidroPy', self.about)

    def _build_menus(self):
        a = self.a
        mb = self.menuBar()

        def menu(title, items):
            m = mb.addMenu(title)
            for it in items:
                if it is None:
                    m.addSeparator()
                elif isinstance(it, tuple):
                    sub = m.addMenu(it[0])
                    for x in it[1]:
                        sub.addAction(a[x]) if x else sub.addSeparator()
                else:
                    m.addAction(a[it])
            return m
        menu('&Arquivo', ['new', 'open', 'save', 'saveas', None, 'import_dxf', 'export_dxf',
                          None, 'import_inp', 'export_inp', None, 'export_res', None, 'quit'])
        menu('&Editar', ['undo', 'redo', None, 'copy', 'paste', 'delete', 'selall', None,
                         'move', 'rotate', 'mirror'])
        m = menu('&Visualizar', ['fit', 'zoom_sel', 'zoom_in', 'zoom_out', None, 'grid', None,
                                 'lbl_nodes', 'lbl_links', 'lbl_diam', 'lbl_press', 'lbl_flow',
                                 'lbl_vel', 'arrows', 'symbols', 'refs', None])
        for d in (self.d_tree, self.d_props, self.d_layers, self.d_results, self.d_valid,
                  self.d_log, self.d_table):
            m.addAction(d.toggleViewAction())
        menu('&Desenhar', ['tool_select', 'tool_pan', None, 'tool_line', 'tool_polyline',
                           'tool_rect', 'tool_circle', 'tool_arc', 'tool_text', 'tool_dimension',
                           None, 'tool_measure', None, 'snap_grid', 'snap_obj'])
        menu('&Rede hidráulica', ['tool_junction', 'tool_reservoir', 'tool_tank', 'tool_pipe',
                                  'tool_pump', 'tool_valve', 'tool_split', None, 'mark_existing',
                                  'mark_projected', None, 'convert', None,
                                  'curves', 'patterns', 'controls', None, 'scenarios', None,
                                  'validate', 'table'])
        menu('De&mandas', ['population', 'nodal_demand'])
        menu('&Simulação', ['sim_opts', 'simulate', 'cancel'])
        menu('&Otimização', ['opt_cfg', 'optimize', 'opt_last', 'cancel'])
        menu('Res&ultados', ['results', None, 'th_press', 'th_vel', 'th_flow', 'th_diam',
                             'th_diam_opt', 'th_change', 'th_existing', 'th_clear', None, 'export_res', 'report'])
        menu('&Ferramentas', ['tool_measure', 'table', 'validate', None, 'runs_dir', 'logfile'])
        menu('&Configurações', ['settings', 'sim_opts', 'opt_cfg'])
        menu('A&juda', ['readme', 'about'])

    def _build_toolbars(self):
        TB.build_toolbars(self)

    def _connect(self):
        c = self.ctrl
        c.dirtyChanged.connect(lambda d: self.update_title())
        c.elementsChanged.connect(lambda cs: self._on_model_changed())
        c.projectReplaced.connect(self._on_project_replaced)
        c.scenarioChanged.connect(self.tree.rebuild)
        c.scenarioChanged.connect(self.update_title)
        c.selectionChanged.connect(self._on_selection)
        self.canvas.cursorMoved.connect(self._on_cursor)
        self.canvas.zoomChanged.connect(lambda s: self.st_zoom.setText(f'Escala: {s:.3g} px/m'))
        self.canvas.statusMessage.connect(self.st_msg.setText)
        self.ctrl.message.connect(self.st_msg.setText)
        self.canvas.contextMenuRequested.connect(self.canvas_context_menu)
        self.layers.currentLayerChanged.connect(self._set_current_layer)
        self.tree.openEditor.connect(self.open_editor)
        self.tree.scenarioActivated.connect(self._activate_scenario)
        self.tree.resultActivated.connect(self._result_activated)
        self.validation.elementActivated.connect(self._focus_element)
        self.validation.validated.connect(
            lambda e, w: self.st_valid.setText(f'Validação: {e} erro(s), {w} adv.'))
        self.runner.output.connect(self.logw.appendPlainText)
        self.runner.progress.connect(self._on_progress)
        self.runner.finished.connect(self._on_run_finished)
        self._count_timer = QTimer(self, singleShot=True, interval=200, timeout=self.update_counts)

    # ================================================================== util
    def _set_setting(self, attr, value):
        setattr(self.ctrl.project.settings, attr, value)
        if attr == 'snap_endpoints':
            s = self.ctrl.project.settings
            s.snap_nodes = s.snap_midpoints = s.snap_intersections = value
        if attr == 'show_reference_layers':
            self.ctrl.layersChanged.emit()
        self.canvas.refresh_theme()
        self.canvas.refresh_all_styles()

    def _sync_toggles(self):
        s = self.ctrl.project.settings
        for key, attr in (('grid', 'grid_visible'), ('snap_grid', 'snap_grid'),
                          ('snap_obj', 'snap_endpoints'), ('lbl_nodes', 'show_node_labels'),
                          ('lbl_links', 'show_link_labels'), ('lbl_diam', 'show_diameters'),
                          ('lbl_press', 'show_pressures'), ('lbl_flow', 'show_flows'),
                          ('lbl_vel', 'show_velocities'), ('arrows', 'show_flow_arrows'),
                          ('symbols', 'show_symbols'), ('refs', 'show_reference_layers')):
            self.a[key].blockSignals(True)
            self.a[key].setChecked(getattr(s, attr))
            self.a[key].blockSignals(False)

    def _set_current_layer(self, name):
        self.canvas.current_layer = name

    def activate_tool(self, key):
        cls = {'select': T.SelectTool, 'pan': T.PanTool, 'line': T.LineTool,
               'polyline': T.PolylineTool, 'rect': T.RectTool, 'circle': T.CircleTool,
               'arc': T.ArcTool, 'text': T.TextTool, 'dimension': T.DimensionTool,
               'measure': T.MeasureTool, 'split': T.SplitPipeTool}
        if key == 'select' and isinstance(self.canvas.tool, T.SelectTool):
            # Esc com a seleção ativa: limpa a seleção
            self.ctrl.set_selection([], 'canvas')
            return
        if key in ('junction', 'reservoir', 'tank'):
            tool = T.NodeTool(self.canvas, key)
        elif key in ('pipe', 'pump', 'valve'):
            tool = T.LinkTool(self.canvas, key)
        else:
            tool = cls[key](self.canvas)
        self.canvas.set_tool(tool)
        if key in self.tool_actions:
            self.tool_actions[key].setChecked(True)
        self.canvas.setFocus()

    def update_title(self):
        p = self.ctrl.project
        name = os.path.basename(p.path) if p.path else 'sem título'
        scen = p.scenario().name
        self.setWindowTitle(f'{APP_NAME} — {name} — cenário: {scen}[*]')
        self.setWindowModified(self.ctrl.dirty)
        self.st_project.setText('Projeto: ' + ('alterado' if self.ctrl.dirty else 'salvo'))

    def update_counts(self):
        c = self.ctrl.project.network.counts()
        n_nodes = sum(c.get(k, 0) for k in ('junction', 'reservoir', 'tank'))
        n_links = sum(c.get(k, 0) for k in ('pipe', 'pump', 'valve'))
        self.st_count.setText(f'Nós: {n_nodes}  Ligações: {n_links}  CAD: '
                              f'{len(self.ctrl.project.cad)}')
        sim = self.ctrl.project.latest_result('simulation')
        if self.runner.running:
            return
        if sim is None:
            self.st_sim.setText('Simulação: não executada')
        else:
            self.st_sim.setText('Simulação: executada')

    def _on_model_changed(self):
        self._count_timer.start()

    def _on_project_replaced(self):
        self.canvas.rebuild()
        self._sync_toggles()
        self.update_title()
        self.update_counts()

    def _on_selection(self, uids, source):
        if uids:
            self.d_props.raise_()
        if source in ('tree', 'table', 'results', 'validation') and uids:
            self.canvas.zoom_to(uids) if len(uids) < 50 else None
        if len(uids) == 1:
            e = self.ctrl.project.get(uids[0])
            if e is not None:
                self.st_msg.setText(f'{KIND_LABELS.get(e.KIND, e.KIND)} {e.name} selecionado.')
        elif uids:
            self.st_msg.setText(f'{len(uids)} elementos selecionados.')

    def _on_cursor(self, x, y, snap):
        self.st_coord.setText(f'X: {x:.3f}  Y: {y:.3f}')
        self.st_snap.setText(f'[{snap}]' if snap else '')

    def _focus_element(self, uid):
        self.ctrl.set_selection([uid], 'validation')
        self.canvas.zoom_to([uid])

    def _on_progress(self, value, maximum, text):
        running = self.runner.running
        self.progress.setVisible(running)
        self.btn_cancel.setVisible(running)
        self.progress.setRange(0, maximum)
        self.progress.setValue(value)
        self.progress.setFormat(text or '%p%')
        self.progress.setTextVisible(True)
        if running:
            self.st_sim.setText(text)

    # ================================================================== arquivos
    def confirm_discard(self) -> bool:
        if not self.ctrl.dirty:
            return True
        r = QMessageBox.question(self, 'Alterações não salvas',
                                 'O projeto possui alterações não salvas. Salvar agora?',
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.file_save()
        return r == QMessageBox.Discard

    def file_new(self):
        if self.runner.running or not self.confirm_discard():
            return
        self.ctrl.replace_project(Project())

    def file_open(self, path=None):
        if self.runner.running or not self.confirm_discard():
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, 'Abrir projeto', '',
                                                  f'Projeto SHCAD (*{EXTENSION});;Todos (*.*)')
        if not path:
            return
        try:
            p = load_project(path)
        except (OSError, ProjectFormatError, ValueError, KeyError) as e:
            QMessageBox.critical(self, 'Abrir projeto', f'Não foi possível abrir:\n{e}')
            return
        self.ctrl.replace_project(p)
        self.logw.appendPlainText(f'Projeto aberto: {path}')

    def file_save(self) -> bool:
        p = self.ctrl.project
        if not p.path:
            return self.file_save_as()
        return self._save_to(p.path)

    def file_save_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(self, 'Salvar projeto', self.ctrl.project.path or
                                              '', f'Projeto SHCAD (*{EXTENSION})')
        if not path:
            return False
        if not path.lower().endswith(EXTENSION):
            path += EXTENSION
        return self._save_to(path)

    def _save_to(self, path) -> bool:
        try:
            save_project(self.ctrl.project, path)
        except OSError as e:
            QMessageBox.critical(self, 'Salvar', f'Falha ao salvar:\n{e}')
            return False
        self.ctrl.mark_saved()
        self.update_title()
        self.st_msg.setText(f'Projeto salvo em {path} (cópia anterior em .bak).')
        return True

    def closeEvent(self, ev):
        if self.runner.running:
            if QMessageBox.question(self, 'Sair', 'Há um cálculo em execução. Cancelar e '
                                    'sair?') != QMessageBox.Yes:
                ev.ignore()
                return
            self.runner.cancel()
        if not self.confirm_discard():
            ev.ignore()
            return
        ev.accept()

    # ------------------------------------------------------------------ DXF / INP
    def import_dxf(self, path=None):
        from ..cad.dxf_importer import inspect_dxf, import_dxf
        from .dialogs.dxf_dialogs import DxfImportDialog
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, 'Importar DXF', '', 'DXF (*.dxf)')
        if not path:
            return
        try:
            info = inspect_dxf(path)
        except Exception as e:
            QMessageBox.critical(self, 'Importar DXF', f'Arquivo DXF inválido:\n{e}')
            return
        dlg = DxfImportDialog(info, self)
        if dlg.exec() != QDialog.Accepted:
            return
        opts = dlg.options()
        try:
            res = import_dxf(path, opts)
        except Exception as e:
            QMessageBox.critical(self, 'Importar DXF', f'Falha na importação:\n{e}')
            return
        self.apply_dxf_import(res, path)

    def apply_dxf_import(self, res, path):
        p = self.ctrl.project
        if p.bounds() is None and res.entities:
            from ..cad import geometry as G
            pts = [pt for e in res.entities for pt in G.cad_polyline(e)]
            if pts:
                x0, y0, _, _ = G.bbox(pts)
                p.display_origin = (round(x0, -2), round(y0, -2))
                self.canvas.rebuild()
        for l in res.layers:
            ex = p.layer_by_name(l.name)
            if ex is None:
                p.add_layer(l)
            else:
                ex.reference = ex.reference or l.reference
                ex.locked = ex.locked or l.locked
        if res.units:
            p.settings.dxf_source_units = res.units
        if path not in p.meta['external_files']:
            p.meta['external_files'].append(os.path.abspath(path))
        self.ctrl.layersChanged.emit()
        self.ctrl.add_elements(res.entities, f'Importar DXF ({len(res.entities)} entidades)')
        self.canvas.fit_all()
        msg = f'DXF importado: {len(res.entities)} entidades em {len(res.layers)} camadas.'
        if res.skipped:
            msg += ' Não importadas: ' + ', '.join(f'{k}: {n}' for k, n in res.skipped.items())
        self.logw.appendPlainText(msg)
        self.st_msg.setText(msg)

    def export_dxf(self):
        from .dialogs.dxf_export_dialog import DxfExportDialog
        DxfExportDialog(self.ctrl, self.canvas.theme.time_index, self).exec()

    def _prepare_inp(self, path):
        """Verifica o .inp, converte para UTF-8 e pede autorização para corrigir problemas.
        Devolve o caminho da cópia a importar, ou None se a importação foi interrompida."""
        from ..integration.inp_check import InpError, check_inp, prepare
        name = os.path.basename(path)
        try:
            chk = check_inp(path)
        except InpError as e:
            QMessageBox.critical(self, 'Arquivo .inp inválido',
                                 f'Não é possível importar "{name}".\n\n{e}')
            return None
        if chk.converted:
            self.logw.appendPlainText(f'{name}: codificação {chk.encoding_label} convertida para '
                                      'UTF-8 (o arquivo original não foi alterado).')
        for w in chk.warnings:
            self.logw.appendPlainText(f'Aviso ({name}): {w}')
        if not chk.issues:
            return prepare(chk, apply_fixes=False)
        box = QMessageBox(QMessageBox.Warning, 'Problemas no arquivo .inp',
                          f'O arquivo "{name}" tem {len(chk.issues)} problema(s) que impedem a '
                          'leitura pelo EPANET, como palavras-chave traduzidas para o '
                          'português ou números com vírgula decimal.\n\n'
                          f'{chk.summary(8)}\n\n'
                          'Deseja corrigir e importar? O arquivo original não será alterado.',
                          parent=self)
        box.setDetailedText('\n'.join(f'Linha {i.line}:\n  antes:  {i.original}\n  depois: '
                                      f'{i.fixed}' for i in chk.issues))
        fix = box.addButton('Corrigir e importar', QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(fix)
        box.exec()
        if box.clickedButton() is not fix:
            self.st_msg.setText('Importação cancelada: o arquivo .inp não foi corrigido.')
            return None
        for i in chk.issues:
            self.logw.appendPlainText(f'Corrigido ({name}, linha {i.line}): {i.message}')
        return prepare(chk, apply_fixes=True)

    def import_inp(self, path=None):
        from ..integration.inp_importer import import_inp
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, 'Importar rede EPANET', '',
                                                  'EPANET (*.inp)')
        if not path:
            return
        prepared = self._prepare_inp(path)
        if prepared is None:
            return
        p = self.ctrl.project
        if p.network.nodes and QMessageBox.question(
                self, 'Importar .inp', 'A rede hidráulica do cenário ativo será substituída '
                '(a geometria CAD é mantida; a operação pode ser desfeita). Continuar?') \
                != QMessageBox.Yes:
            return
        try:
            net, warns = import_inp(prepared, p)
        except Exception as e:
            QMessageBox.critical(self, 'Importar .inp',
                                 f'Não foi possível ler a rede do arquivo:\n{e}')
            return
        changes = editing.delete(p, [e.uid for e in p.network.elements()])
        changes += editing.add(list(net.elements()))
        if not p.network.nodes and p.bounds() is None:
            b = net.bounds()
            if b:
                p.display_origin = (round(b[0], -2), round(b[1], -2))
        self.ctrl.apply(changes, f'Importar {os.path.basename(path)}')
        self.canvas.rebuild()
        for w in warns:
            self.logw.appendPlainText('Aviso: ' + w)
        self.st_msg.setText(f'Rede importada: {len(net.nodes)} nós, {len(net.links)} ligações.')

    def export_inp(self):
        from ..integration.input_exporter import write_inp
        path, _ = QFileDialog.getSaveFileName(self, 'Exportar rede EPANET', '', 'EPANET (*.inp)')
        if not path:
            return
        try:
            write_inp(self.ctrl.project, path)
        except Exception as e:
            QMessageBox.critical(self, 'Exportar .inp', f'Falha:\n{e}')
            return
        self.st_msg.setText(f'Rede exportada: {path}')

    # ================================================================== edição
    def edit_copy(self):
        if not self.ctrl.selection:
            return
        self.ctrl.clipboard = editing.copy_selection(self.ctrl.project, self.ctrl.selection)
        n = len(self.ctrl.clipboard['items'])
        sk = self.ctrl.clipboard['skipped_links']
        self.st_msg.setText(f'{n} elemento(s) copiado(s)' + (
            f'; {sk} ligação(ões) ignorada(s) por não ter os dois nós na seleção.' if sk else '.'))

    def edit_paste(self):
        clip = self.ctrl.clipboard
        if not clip or not clip['items']:
            return
        from ..hydraulics.models import element_from_dict
        from ..cad import geometry as G
        pts = []
        for d in clip['items']:
            e = element_from_dict(d)
            if e.COLLECTION == 'node':
                pts.append((e.x, e.y))
            elif e.COLLECTION == 'cad':
                pts += [tuple(p[:2]) for p in e.points]
        if not pts:
            return
        x0, y0, x1, y1 = G.bbox(pts)
        cx, cy = self.canvas.cursor_model
        changes = editing.paste(self.ctrl.project, clip, cx - (x0 + x1) / 2, cy - (y0 + y1) / 2)
        self.ctrl.apply(changes, 'Colar')
        self.ctrl.set_selection([c[0] for c in changes], 'paste')

    def edit_delete(self):
        if self.ctrl.selection:
            self.ctrl.delete(self.ctrl.selection, f'Excluir {len(self.ctrl.selection)} elemento(s)')

    def edit_select_all(self):
        from ..cad.selection import selectable
        p = self.ctrl.project
        uids = [e.uid for e in list(p.network.nodes.values()) + list(p.network.links.values())
                + list(p.cad.values()) if selectable(p, e)]
        self.ctrl.set_selection(uids, 'canvas')

    def _need_selection(self):
        if not self.ctrl.selection:
            QMessageBox.information(self, 'Edição', 'Selecione os elementos primeiro.')
            return False
        return True

    def edit_move(self):
        if not self._need_selection():
            return
        text, ok = QInputDialog.getText(self, 'Mover', 'Deslocamento ΔX, ΔY (m):', text='0, 0')
        if not ok:
            return
        try:
            dx, dy = (float(t) for t in text.replace(';', ',').split(','))
        except ValueError:
            QMessageBox.warning(self, 'Mover', 'Formato: ΔX, ΔY')
            return
        self.ctrl.apply(editing.move(self.ctrl.project, self.ctrl.selection, dx, dy), 'Mover')

    def edit_rotate(self):
        if not self._need_selection():
            return
        cx, cy = editing.centroid(self.ctrl.project, self.ctrl.selection)
        ang, ok = QInputDialog.getDouble(self, 'Rotacionar', 'Ângulo (graus, anti-horário):', 90,
                                         -360, 360, 3)
        if not ok:
            return
        text, ok = QInputDialog.getText(self, 'Rotacionar', 'Centro X, Y (m):',
                                        text=f'{cx:.3f}, {cy:.3f}')
        if not ok:
            return
        try:
            cx, cy = (float(t) for t in text.replace(';', ',').split(','))
        except ValueError:
            return
        self.ctrl.apply(editing.rotate(self.ctrl.project, self.ctrl.selection, cx, cy, ang),
                        'Rotacionar')

    def edit_mirror(self):
        if not self._need_selection():
            return
        cx, cy = editing.centroid(self.ctrl.project, self.ctrl.selection)
        axis, ok = QInputDialog.getItem(self, 'Espelhar', 'Eixo (pelo centro da seleção):',
                                        ['Vertical', 'Horizontal'], 0, False)
        if not ok:
            return
        keep = QMessageBox.question(self, 'Espelhar', 'Manter os originais (espelhar uma '
                                    'cópia)?') == QMessageBox.Yes
        p = self.ctrl.project
        a, b = ((cx, cy - 1), (cx, cy + 1)) if axis == 'Vertical' else ((cx - 1, cy), (cx + 1, cy))
        uids = self.ctrl.selection
        self.ctrl.undo_stack.beginMacro('Espelhar')
        if keep:
            clip = editing.copy_selection(p, uids)
            ch = editing.paste(p, clip, 0, 0)
            self.ctrl.apply(ch, 'Copiar')
            uids = [c[0] for c in ch]
        self.ctrl.apply(editing.mirror(p, uids, *a, *b), 'Espelhar')
        self.ctrl.undo_stack.endMacro()

    def mark_existing(self, value: bool):
        p = self.ctrl.project
        pipes = [u for u in self.ctrl.selection
                 if getattr(p.network.links.get(u), 'KIND', '') == 'pipe']
        if not pipes:
            QMessageBox.information(self, 'Trechos existentes',
                                    'Selecione uma ou mais tubulações (clique, janela ou árvore).')
            return
        changes = editing.set_existing(p, pipes, value)
        label = 'existentes' if value else 'projetados'
        if not changes:
            self.st_msg.setText(f'Os {len(pipes)} trecho(s) selecionado(s) já estão {label}.')
            return
        self.ctrl.apply(changes, f'Marcar {len(changes)} trecho(s) como {label}')
        L = sum(p.network.hydraulic_length(p.network.links[u]) for u in pipes)
        self.st_msg.setText(f'{len(changes)} trecho(s) marcado(s) como {label} '
                            f'({L:,.1f} m selecionados).')

    def canvas_context_menu(self, global_pos):
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        sel = self.ctrl.selection
        if sel:
            m.addAction(self.a['mark_existing'])
            m.addAction(self.a['mark_projected'])
            m.addSeparator()
            for k in ('copy', 'delete', 'move', 'rotate', 'mirror', 'zoom_sel'):
                m.addAction(self.a[k])
            if any(u in self.ctrl.project.cad for u in sel):
                m.addSeparator()
                m.addAction(self.a['convert'])
        else:
            for k in ('paste', 'selall', 'fit'):
                m.addAction(self.a[k])
        m.exec(global_pos)

    def convert_cad(self):
        from .dialogs.dxf_dialogs import ConvertDialog
        p = self.ctrl.project
        cad = [u for u in self.ctrl.selection if u in p.cad]
        if not cad:
            QMessageBox.information(self, 'Converter', 'Selecione linhas ou polilinhas CAD. '
                                    'Camadas bloqueadas precisam ser desbloqueadas para seleção.')
            return

        def planner(tol, **kw):
            return editing.cad_to_pipes(p, cad, tol, **kw)
        dlg = ConvertDialog(p, len(cad), planner, self)
        if dlg.exec() != QDialog.Accepted or dlg.plan is None:
            return
        plan = dlg.plan
        if plan.ambiguous and QMessageBox.question(
                self, 'Conexões ambíguas', f'{len(plan.ambiguous)} conexão(ões) ambígua(s) '
                '(veja a lista). Confirmar mesmo assim?') != QMessageBox.Yes:
            return
        self.ctrl.apply(plan.changes, f'Converter {plan.n_pipes} entidades em tubulações')
        self.st_msg.setText(f'{plan.n_pipes} tubulações e {plan.n_new_nodes} junções criadas.')

    def open_editor(self, kind, uid):
        from .dialogs.data_dialogs import CurvesDialog, PatternsDialog, ControlsDialog
        if kind == 'zoom':
            self.canvas.zoom_to([uid])
            return
        cls = {'curve': CurvesDialog, 'pattern': PatternsDialog, 'control': ControlsDialog}.get(kind)
        if cls is None:
            self.d_table.show()
            self.d_table.raise_()
            return
        cls(self.ctrl, uid, self).exec()

    def open_scenarios(self):
        from .dialogs.data_dialogs import ScenariosDialog
        ScenariosDialog(self.ctrl, self).exec()

    def _activate_scenario(self, uid):
        if uid == self.ctrl.project.active_scenario:
            return
        if self.runner.running:
            QMessageBox.information(self, 'Cenários', 'Aguarde o término do cálculo.')
            return
        self.ctrl.switch_scenario(uid)

    def _result_activated(self, uid):
        r = next((x for x in self.ctrl.project.results() if x['uid'] == uid), None)
        if r is None:
            return
        if r['status'] != 'ok':
            self._show_failure(r)
        elif r['kind'] == 'optimization':
            self.show_optimization(r)
        else:
            self.d_results.show()
            self.d_results.raise_()

    # ================================================================== cálculo
    def run_validation(self):
        self.d_valid.show()
        self.d_valid.raise_()
        return self.validation.run()

    def _prevalidate(self) -> bool:
        issues = self.run_validation()
        if has_errors(issues):
            n = sum(1 for i in issues if i.is_error)
            QMessageBox.warning(self, 'Validação', f'A rede possui {n} erro(s) impeditivo(s). '
                                'Corrija-os antes de executar (veja o painel Validação).')
            return False
        if issues:
            return QMessageBox.question(self, 'Validação', f'Há {len(issues)} advertência(s). '
                                        'Executar mesmo assim?') == QMessageBox.Yes
        return True

    def population_projection(self):
        from .dialogs.population_dialog import PopulationDialog
        PopulationDialog(self.ctrl, self).exec()
        self.update_title()

    def nodal_demands(self):
        from .dialogs.demand_dialog import DemandDialog
        if not any(n.KIND == 'junction' for n in self.ctrl.project.network.nodes.values()):
            QMessageBox.information(self, 'Consumos nodais', 'A rede não possui junções.')
            return
        DemandDialog(self.ctrl, self).exec()

    def sim_options(self):
        from .dialogs.options_dialogs import SimOptionsDialog
        if SimOptionsDialog(self.ctrl.project, self).exec() == QDialog.Accepted:
            self.ctrl.invalidate_hash()
            self.ctrl.mark_dirty()
            self.canvas.refresh_theme()
            self.update_counts()

    def opt_settings(self):
        from .dialogs.optimization_dialogs import OptimizationSettingsDialog
        if OptimizationSettingsDialog(self.ctrl.project, self).exec() == QDialog.Accepted:
            self.ctrl.mark_dirty()

    def settings_dialog(self):
        from .dialogs.options_dialogs import SettingsDialog
        if SettingsDialog(self.ctrl.project, self).exec() == QDialog.Accepted:
            self.ctrl.mark_dirty()
            self._sync_toggles()
            self.canvas.refresh_all_styles()

    def _start(self, kind):
        if self.runner.running:
            QMessageBox.information(self, 'Cálculo', 'Já existe um cálculo em execução.')
            return
        if not self._prevalidate():
            return
        if kind == 'optimize':
            script = optimization_adapter.script_path(self.ctrl.project)
            if not os.path.exists(script):
                QMessageBox.critical(self, 'Otimização', f'Script não encontrado:\n{script}')
                return
        self.d_log.show()
        self.d_log.raise_()
        try:
            self.runner.start(kind)
        except Exception as e:
            log.exception('falha ao iniciar')
            QMessageBox.critical(self, 'Cálculo', f'Não foi possível preparar o cálculo:\n{e}')
            return
        for k in ('simulate', 'optimize'):
            self.a[k].setEnabled(False)

    def run_simulation(self):
        self._start('simulate')

    def run_optimization(self):
        self._start('optimize')

    def _on_run_finished(self, res):
        for k in ('simulate', 'optimize'):
            self.a[k].setEnabled(True)
        self.progress.setVisible(False)
        self.btn_cancel.setVisible(False)
        if res['status'] == 'cancelled':
            self.logw.appendPlainText('Cálculo cancelado. O projeto não foi alterado.')
            self.update_counts()
            return
        self.ctrl.add_result(res)
        self.update_counts()
        if res['status'] != 'ok':
            self._show_failure(res)
            return
        if res['kind'] == 'simulation':
            self.logw.appendPlainText('Simulação concluída; resultados associados por '
                                      f"identificador ({len(res['nodes'])} nós, "
                                      f"{len(res['links'])} ligações).")
            if res.get('unmapped'):
                self.logw.appendPlainText(f"Sem correspondência: {res['unmapped']}")
            if not self.canvas.theme.node_var and not self.canvas.theme.link_var:
                self.results.set_vars('pressure', 'velocity')
                self.canvas.fit_all()       # reenquadra deixando espaço para as legendas
            self.d_results.show()
            self.d_results.raise_()
        else:
            self.show_optimization(res)

    def _show_failure(self, res):
        msg = res.get('error') or 'Falha desconhecida.'
        box = QMessageBox(QMessageBox.Critical, 'Falha no cálculo',
                          f'{msg}\n\nO projeto foi preservado sem alterações.', parent=self)
        details = '\n'.join(x for x in (res.get('traceback', ''), res.get('report', ''),
                                        res.get('log', '')[-6000:]) if x)
        if details:
            box.setDetailedText(details)
        box.exec()

    def show_last_optimization(self):
        r = self.ctrl.project.latest_result('optimization')
        if r is None:
            QMessageBox.information(self, 'Otimização', 'Nenhuma otimização concluída neste '
                                    'cenário.')
            return
        self.show_optimization(r)

    def show_optimization(self, res):
        from .dialogs.optimization_dialogs import OptimizationResultDialog
        dlg = OptimizationResultDialog(self.ctrl, res, self)
        if dlg.exec() != QDialog.Accepted:
            return
        if dlg.choice == dlg.VIEW:
            self.canvas.preview_opt_uid = res['uid']
            self.results.set_vars(None, 'diam_change')
            self.a['lbl_diam'].setChecked(True)
            self.st_msg.setText('Visualizando a solução otimizada — o modelo NÃO foi alterado.')
        elif dlg.choice == dlg.APPLY:
            self.apply_optimized(res)
        elif dlg.choice == dlg.SCENARIO:
            self.scenario_from_optimization(res)

    def _diameter_changes(self, net, res):
        return optimization_adapter.diameter_changes(net, res)

    def apply_optimized(self, res):
        p = self.ctrl.project
        if not self.ctrl.is_current(res) and QMessageBox.question(
                self, 'Aplicar', 'A rede mudou desde a otimização. Aplicar assim mesmo?') \
                != QMessageBox.Yes:
            return
        items = self._diameter_changes(p.network, res)
        self.ctrl.update_elements([(u, {'diameter': d}) for u, d in items],
                                  f'Aplicar diâmetros otimizados ({len(items)} trechos)')
        self.canvas.preview_opt_uid = res['uid']
        QMessageBox.information(self, 'Diâmetros aplicados',
                                f'{len(items)} trecho(s) alterado(s). Execute uma nova '
                                'simulação para obter os resultados da rede modificada.')

    def scenario_from_optimization(self, res):
        p = self.ctrl.project
        name, ok = QInputDialog.getText(self, 'Cenário otimizado', 'Nome do cenário:',
                                        text=f'{p.scenario().name} — otimizada')
        if not ok or not name.strip():
            return
        s = optimization_adapter.create_optimized_scenario(p, res, name.strip())
        self.ctrl.mark_dirty()
        self.ctrl.scenarioChanged.emit()
        if QMessageBox.question(self, 'Cenário criado', f"Cenário '{s.name}' criado. "
                                'Ativá-lo agora?') == QMessageBox.Yes:
            self.ctrl.switch_scenario(s.uid)

    def theme_flow(self):
        self.a['arrows'].setChecked(True)
        self.results.set_vars(None, 'flow')

    # ================================================================== relatórios etc.
    def make_report(self):
        dlg = QDialog(self)
        dlg.setWindowTitle('Gerar relatório')
        v = QVBoxLayout(dlg)
        checks = {}
        for k, t in reports.REPORTS.items():
            cb = QCheckBox(t)
            cb.setChecked(True)
            v.addWidget(cb)
            checks[k] = cb
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        if dlg.exec() != QDialog.Accepted:
            return
        which = {k for k, cb in checks.items() if cb.isChecked()}
        path, filt = QFileDialog.getSaveFileName(self, 'Salvar relatório', '',
                                                 'PDF (*.pdf);;HTML (*.html)')
        if not path:
            return
        html = reports.build_report(self.ctrl, which, self.canvas.theme.time_index)
        try:
            if path.lower().endswith('.html') or 'HTML' in filt:
                if not path.lower().endswith('.html'):
                    path += '.html'
                reports.save_html(html, path)
            else:
                if not path.lower().endswith('.pdf'):
                    path += '.pdf'
                reports.save_pdf(html, path)
        except Exception as e:
            QMessageBox.critical(self, 'Relatório', f'Falha: {e}')
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def open_runs_dir(self):
        from ..integration.runner import runs_root
        QDesktopServices.openUrl(QUrl.fromLocalFile(runs_root()))

    def open_logfile(self):
        from ..utils.logging_setup import log_path
        QDesktopServices.openUrl(QUrl.fromLocalFile(log_path()))

    def open_readme(self):
        from .dialogs.help_dialogs import ManualDialog
        ManualDialog(self).exec()

    def about(self):
        from .dialogs.help_dialogs import AboutDialog
        AboutDialog(self).exec()
