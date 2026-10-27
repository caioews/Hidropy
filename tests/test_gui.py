"""Testes 15 e 18 + fluxo da interface: desenho, ferramentas, resultados no CAD, cenários."""

import math

import pytest

from src.hydraulics.project_io import load_project, save_project
from src.integration import simulation_adapter, optimization_adapter
from src.results import thematic_views as TV


@pytest.fixture
def window(qapp, simple_project):
    from PySide6.QtWidgets import QMessageBox
    from src.ui.main_window import MainWindow
    orig = QMessageBox.question
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    w = MainWindow(simple_project)
    w.resize(1200, 800)
    w.show()
    qapp.processEvents()
    yield w
    w.ctrl.mark_saved()
    w.close()
    QMessageBox.question = orig


def test_draw_network_with_tools(window, qapp):
    w = window
    c = w.canvas
    net = w.ctrl.project.network
    n0 = len(net.nodes)
    w.activate_tool('junction')
    c.feed_point(351000.0, 7400000.0)
    assert len(net.nodes) == n0 + 1
    w.activate_tool('pipe')
    j9 = net.find_by_name('J9')
    c.feed_point(j9.x, j9.y)                    # começa num nó existente
    c.feed_point(350800.0, 7400000.0)           # vértice
    c.feed_point(351000.0, 7400000.0)           # termina no nó criado acima
    new = [l for l in net.links.values() if l.start == j9.uid and l.vertices]
    assert len(new) == 1 and new[0].vertices == [[350800.0, 7400000.0]]
    assert math.isclose(new[0].length, net.geometric_length(new[0]))
    w.activate_tool('line')
    c.feed_point(0.0, 0.0)
    c.feed_point(10.0, 0.0)
    assert any(e.geom == 'line' for e in w.ctrl.project.cad.values())
    # desfazer remove a linha
    w.ctrl.undo_stack.undo()
    assert not any(e.geom == 'line' for e in w.ctrl.project.cad.values())


def test_window_selection_and_tree_sync(window, qapp):
    from src.cad import selection as SEL
    w = window
    p = w.ctrl.project
    j1, j5 = p.network.find_by_name('J1'), p.network.find_by_name('J5')
    uids = SEL.window(p, w.canvas.index, j1.x - 1, j1.y + 1, j5.x + 1, j5.y - 1, False)
    names = {p.get(u).name for u in uids}
    assert {'J1', 'J2', 'J4', 'J5', 'P2', 'P3'} <= names and 'J9' not in names
    w.ctrl.set_selection(uids, 'canvas')
    qapp.processEvents()
    assert {it.text(0) for it in w.tree.selectedItems()} == names


# 15. resultados exibidos no desenho, associados ao elemento correto
def test_results_shown_on_drawing(window, qapp):
    w = window
    p = w.ctrl.project
    res = simulation_adapter.run_blocking(p)
    assert res['status'] == 'ok'
    w.ctrl.add_result(res)
    assert w.ctrl.is_current(res)
    w.results.set_vars('pressure', 'velocity')
    qapp.processEvents()
    j9 = p.network.find_by_name('J9')
    j1 = p.network.find_by_name('J1')
    style9 = w.canvas.node_style(j9)
    style1 = w.canvas.node_style(j1)
    assert style9['thematic'] and style9['color'] != style1['color']
    scale = TV.ColorScale('pressure', TV.node_values(p, 'pressure', res, None, 0), None)
    assert style9['color'] == scale.color(j9.uid)
    legends = w.canvas.legends()
    assert legends[0].entries
    p.settings.show_pressures = True
    assert f"{res['nodes'][j9.uid]['pressure'][0]:.2f} m" in w.canvas.label_text(j9)
    # a interface não exibe a menção "desatualizado" em lugar nenhum
    w.ctrl.update_element(j9.uid, base_demand=9.0)
    w.canvas.refresh_theme()
    qapp.processEvents()
    w.ctrl.set_selection([j9.uid], 'canvas')
    from PySide6.QtWidgets import QLabel, QGroupBox
    texts = [x.text() for x in w.findChildren(QLabel)] +         [x.title() for x in w.findChildren(QGroupBox)] + [lg.title for lg in w.canvas.legends()]
    assert not any('desatualiz' in t.lower() for t in texts)


# 18. salvar e reabrir um cenário otimizado
def test_optimized_scenario_save_and_reopen(window, qapp, tmp_path):
    w = window
    p = w.ctrl.project
    p.opt_settings.num_geracoes = 5
    p.opt_settings.tam_populacao = 16
    res = optimization_adapter.run_blocking(p)
    assert res['status'] == 'ok', res.get('error')
    w.ctrl.add_result(res)
    original = {l.uid: l.diameter for l in p.network.links.values()}
    from PySide6.QtWidgets import QInputDialog
    orig_get = QInputDialog.getText
    QInputDialog.getText = staticmethod(lambda *a, **k: ('Rede otimizada', True))
    try:
        w.scenario_from_optimization(res)
    finally:
        QInputDialog.getText = orig_get
    assert p.scenario().name == 'Rede otimizada'
    opt = optimization_adapter.optimized_diameters(res)
    for uid, d in opt.items():
        assert p.network.links[uid].diameter == d
    path = str(tmp_path / 'cenarios.shcad')
    save_project(p, path)
    q = load_project(path)
    assert [s.name for s in q.scenarios] == ['Rede original', 'Rede otimizada']
    assert q.scenario().name == 'Rede otimizada'
    for uid, d in opt.items():
        assert q.network.links[uid].diameter == d
    q.switch_scenario(q.scenarios[0].uid)
    assert {l.uid: l.diameter for l in q.network.links.values()} == original
    assert q.scenarios[1].results and q.scenarios[1].results[0]['kind'] == 'optimization'


def test_apply_optimized_marks_results_stale(window, qapp):
    w = window
    p = w.ctrl.project
    sim = simulation_adapter.run_blocking(p)
    w.ctrl.add_result(sim)
    fake_opt = {'uid': 'x', 'kind': 'optimization', 'status': 'ok',
                'inp_sha256': w.ctrl.current_hash(),
                'pipes': {p.network.find_by_name('P2').uid: {'opt_diam_mm': 75.0,
                                                             'orig_diam_mm': 150.0}}}
    from PySide6.QtWidgets import QMessageBox
    orig = QMessageBox.information
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    try:
        w.apply_optimized(fake_opt)
    finally:
        QMessageBox.information = orig
    assert p.network.find_by_name('P2').diameter == 75.0
    assert not w.ctrl.is_current(sim)
    w.ctrl.undo_stack.undo()
    assert p.network.find_by_name('P2').diameter == 150.0
    assert w.ctrl.is_current(sim)


def test_report_and_tables(window, qapp, tmp_path):
    from src.results import reports, tables
    w = window
    p = w.ctrl.project
    w.ctrl.add_result(simulation_adapter.run_blocking(p))
    html = reports.build_report(w.ctrl, set(reports.REPORTS))
    assert 'Pressão (m)' in html and 'Cadastro' in html
    pdf = str(tmp_path / 'r.pdf')
    reports.save_pdf(html, pdf)
    with open(pdf, 'rb') as f:
        assert f.read(4) == b'%PDF'
    df = tables.elements_df(p, 'pipe')
    tables.export_df(df, str(tmp_path / 't.xlsx'))
    tables.export_df(df, str(tmp_path / 't.csv'))
    assert len(df) == len(p.network.links)


def test_mouse_select_drag_move_and_zoom(window, qapp):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    w = window
    c = w.canvas
    p = w.ctrl.project
    w.activate_tool('select')
    c.fit_all()
    qapp.processEvents()
    j5 = p.network.find_by_name('J5')
    pos = c.mapFromScene(c.m2s(j5.x, j5.y))
    vp = c.viewport()
    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, pos)
    assert w.ctrl.selection == [j5.uid]
    # arrastar o nó selecionado 40 px para a direita
    x0 = j5.x
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, pos)
    for k in range(1, 5):
        QTest.mouseMove(vp, pos + QPoint(10 * k, 0))
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, pos + QPoint(40, 0))
    moved = p.network.nodes[j5.uid].x - x0
    assert moved > 0 and math.isclose(moved, 40 / c.ppm, rel_tol=0.35)
    # zoom com a roda mantém o ponto sob o cursor
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtCore import QPointF
    before = c.view2model(pos)
    s0 = c.ppm
    ev = QWheelEvent(QPointF(pos), QPointF(vp.mapToGlobal(pos)), QPoint(0, 0), QPoint(0, 120),
                     Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    c.wheelEvent(ev)
    assert c.ppm > s0
    after = c.view2model(pos)
    assert math.dist(before, after) < 2 / c.ppm
    # Esc limpa a seleção
    w.a['tool_select'].trigger()
    assert w.ctrl.selection == []


def test_existing_pipes_marking_style_and_protection(window, qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox
    w = window
    p = w.ctrl.project
    net = p.network
    p2, p3 = net.find_by_name('P2'), net.find_by_name('P3')
    j1 = net.find_by_name('J1')
    # marcar pela seleção (nós selecionados juntos são ignorados)
    w.ctrl.set_selection([p2.uid, p3.uid, j1.uid], 'canvas')
    w.mark_existing(True)
    assert net.links[p2.uid].existing and net.links[p3.uid].existing
    # estilo tracejado no desenho; projetadas continuam contínuas
    pen = w.canvas.items_by_uid[p2.uid].pen()
    assert pen.style() == Qt.CustomDashLine
    assert w.canvas.items_by_uid[net.find_by_name('P4').uid].pen().style() == Qt.SolidLine
    # árvore separa existentes de projetadas
    w.tree.rebuild()
    texts = [w.tree.itemText(it) for it in w.tree._all_items()]
    assert 'Tubulações existentes (2)' in texts and 'Tubulações projetadas (11)' in texts
    # mapa temático
    w.results.set_vars(None, 'existing')
    lg = w.canvas.legends()[0]
    assert '2 existente(s)' in lg.note
    # aviso ao editar o diâmetro: "Não" mantém, "Sim" altera
    orig = QMessageBox.question
    try:
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
        w.ctrl.set_selection([p2.uid], 'canvas')
        w.props._commit([net.links[p2.uid]], 'diameter', 75.0)
        assert net.links[p2.uid].diameter == 150.0
        w.props._commit([net.links[p2.uid]], 'roughness', 120.0)   # outras propriedades: livre
        assert net.links[p2.uid].roughness == 120.0
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
        w.props._commit([net.links[p2.uid]], 'diameter', 75.0)
        assert net.links[p2.uid].diameter == 75.0
    finally:
        QMessageBox.question = orig
    # aplicar diâmetros otimizados nunca altera trecho existente
    fake = {'uid': 'y', 'kind': 'optimization', 'status': 'ok',
            'inp_sha256': w.ctrl.current_hash(),
            'pipes': {p2.uid: {'opt_diam_mm': 50.0, 'orig_diam_mm': 75.0},
                      net.find_by_name('P4').uid: {'opt_diam_mm': 50.0, 'orig_diam_mm': 150.0}}}
    orig_info = QMessageBox.information
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    try:
        w.apply_optimized(fake)
    finally:
        QMessageBox.information = orig_info
    assert net.links[p2.uid].diameter == 75.0
    assert net.find_by_name('P4').diameter == 50.0
    # desmarcar e desfazer
    w.ctrl.set_selection([p3.uid], 'canvas')
    w.mark_existing(False)
    assert not net.links[p3.uid].existing
    w.ctrl.undo_stack.undo()
    assert net.links[p3.uid].existing
