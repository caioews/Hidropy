"""União de nós: arrastar um nó sobre outro transfere as ligações e mantém o nó de destino."""

import math
import os

import pytest

from conftest import ROOT
from src.hydraulics import connectivity, editing
from src.hydraulics.models import Control, Junction, Pipe
from src.hydraulics.project import Project
from src.hydraulics.validation import validate

MORRO = os.path.join(os.path.dirname(ROOT), 'RDA_Morro Branco.inp')


def apply(p, changes):
    for uid, before, after in changes:
        if after is None:
            p.remove(uid)
        else:
            p.put_dict(after)
    p.network.invalidate()


def small_net():
    p = Project()
    a = Junction(name='A', x=0, y=0, elevation=10, base_demand=1.0)
    b = Junction(name='B', x=0.03, y=0.0, elevation=12, base_demand=2.0)   # quase em cima de A
    w = Junction(name='W', x=-50, y=0)
    e = Junction(name='E', x=50, y=0)
    n = Junction(name='N', x=0, y=50)
    for j in (a, b, w, e, n):
        p.network.put(j)
    p.network.put(Pipe(name='PW', start=w.uid, end=a.uid))
    p.network.put(Pipe(name='PN', start=n.uid, end=a.uid))
    p.network.put(Pipe(name='PE', start=b.uid, end=e.uid, vertices=[[25, 5]]))
    p.network.put(Pipe(name='PAB', start=a.uid, end=b.uid))                # vira laço
    p.network.put(Control(name='C1', link=p.network.find_by_name('PE').uid,
                          condition='IF NODE BELOW', node=b.uid, value='5'))
    return p, a, b


def test_merge_keeps_target_and_transfers_links():
    p, a, b = small_net()
    plan = editing.merge_nodes(p, b.uid, a.uid)            # move B (src) sobre A (dst)
    assert plan.moved_links == ['PE'] and plan.removed_links == ['PAB']
    assert plan.lost_demand == 2.0
    apply(p, plan.changes)
    net = p.network
    assert b.uid not in net.nodes and net.find_by_name('PAB') is None
    keep = net.nodes[a.uid]
    assert (keep.x, keep.y, keep.elevation, keep.base_demand) == (0, 0, 10, 1.0)
    assert {l.name for l in net.links_of_node(a.uid)} == {'PW', 'PN', 'PE'}
    pe = net.find_by_name('PE')
    assert pe.start == a.uid and pe.vertices == [[25, 5]]
    assert net.find_by_name('C1').node == a.uid             # controle redirecionado
    assert not connectivity.coincident_nodes(net, 0.05)


def test_merge_reports_parallel_links():
    p, a, b = small_net()
    w = p.network.find_by_name('W')
    p.network.put(Pipe(name='PW2', start=w.uid, end=b.uid))
    plan = editing.merge_nodes(p, b.uid, a.uid)
    assert ('PW2', 'PW') in plan.parallel


@pytest.mark.skipif(not os.path.exists(MORRO), reason='rede Morro Branco ausente')
def test_morro_branco_nodes_101_563():
    from src.integration.inp_importer import import_inp
    p = Project()
    net, _ = import_inp(MORRO, p)
    p.network = net
    n101, n563 = net.find_by_name('101'), net.find_by_name('563')
    assert 'NOS_COINCIDENTES' in {i.code for i in validate(p)}
    links = {l.name for l in net.links_of_node(n101.uid)} | \
        {l.name for l in net.links_of_node(n563.uid)}
    plan = editing.merge_nodes(p, n563.uid, n101.uid)
    apply(p, plan.changes)
    assert '563' not in {n.name for n in p.network.nodes.values()}
    assert {l.name for l in p.network.links_of_node(n101.uid)} == links       # cruzamento
    assert math.isclose(p.network.nodes[n101.uid].elevation, n101.elevation)
    assert 'NOS_COINCIDENTES' not in {i.code for i in validate(p)}
    from src.integration import simulation_adapter
    assert simulation_adapter.run_blocking(p)['status'] == 'ok'


def test_drag_node_onto_node_merges_with_undo(qapp, monkeypatch):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox
    from src.ui.main_window import MainWindow
    p, a, b = small_net()
    monkeypatch.setattr(QMessageBox, 'question', staticmethod(lambda *x, **k: QMessageBox.Yes))
    w = MainWindow(p)
    w.resize(1000, 700)
    w.show()
    qapp.processEvents()
    c = w.canvas
    w.activate_tool('select')
    c.resetTransform()
    c.scale_view(1000.0)                          # zoom máximo: 3 cm = 30 px na tela
    c.center_on_model(0.015, 0.0)
    qapp.processEvents()
    vp = c.viewport()
    pa = c.mapFromScene(c.m2s(a.x, a.y))
    pb = c.mapFromScene(c.m2s(b.x, b.y))
    assert (pb - pa).manhattanLength() > 20
    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, pb)
    assert w.ctrl.selection == [b.uid]
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, pb)
    step = (pa - pb) / 4
    for k in range(1, 5):
        QTest.mouseMove(vp, pb + step * k)
    assert c.tool.merge_target == a.uid                   # destaque "unir a A" durante o arraste
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, pa)
    net = w.ctrl.project.network
    assert b.uid not in net.nodes and w.ctrl.selection == [a.uid]
    assert net.nodes[a.uid].x == 0 and net.find_by_name('PE').start == a.uid
    w.ctrl.undo_stack.undo()                              # um único passo desfaz tudo
    assert b.uid in net.nodes and net.find_by_name('PE').start == b.uid
    assert net.find_by_name('PAB') is not None
    # arrastar para um ponto vazio continua sendo só mover
    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, pb)
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, pb)
    QTest.mouseMove(vp, pb + QPoint(0, 60))
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, pb + QPoint(0, 60))
    assert b.uid in net.nodes and net.nodes[b.uid].y < 0
    w.ctrl.mark_saved()
    w.close()
