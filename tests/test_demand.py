"""Consumos nodais pelo método linear.

Rede de exemplo: R1 —P1 (400 m)— J1 e malha 3×3 com 6 trechos de 200 m e 6 de 150 m.
L = 400 + 6·200 + 6·150 = 2500 m. Com P = 10.000 hab, q = 150 L/hab·dia, K1 = 1,2, K2 = 1,5:
Q = 10000·150·1,8/86400 = 31,25 L/s ; qm = 31,25/2500 = 0,0125 L/s·m.
"""

import math

import pytest

from src.hydraulics import demand as D
from src.hydraulics.population import PopulationStudy, compute
from src.hydraulics.project_io import load_project, save_project


def settings(**kw):
    s = D.DemandSettings(population_source='manual', manual_population=10000, per_capita=150,
                         k1=1.2, k2=1.5)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def test_linear_method_hand_values(simple_project):
    p = simple_project
    res = D.compute_linear(p, settings(), 10000)
    assert math.isclose(res.total_flow, 31.25)
    assert math.isclose(res.total_length, 2500.0)
    assert math.isclose(res.linear_rate, 0.0125)
    by_name = {p.network.nodes[u].name: d for u, d in res.nodes.items()}
    # J1: P1 inteiro (outra ponta é reservatório) + metade de 200 + metade de 150
    assert math.isclose(by_name['J1']['length'], 400 + 100 + 75)
    assert math.isclose(by_name['J1']['new'], 575 * 0.0125)
    # J5 (centro da malha): 2 × 100 + 2 × 75
    assert math.isclose(by_name['J5']['new'], 350 * 0.0125)
    # J9 (canto): 100 + 75
    assert math.isclose(by_name['J9']['new'], 175 * 0.0125)
    # conservação: a soma das demandas nodais é a vazão total
    assert math.isclose(sum(d['new'] for d in res.nodes.values()), res.total_flow)


def test_coefficients_and_exclusions(simple_project):
    p = simple_project
    res = D.compute_linear(p, settings(use_k2=False), 10000)
    assert math.isclose(res.total_flow, 10000 * 150 * 1.2 / 86400)
    p.network.find_by_name('P1').distributes = False          # adutora
    res = D.compute_linear(p, settings(), 10000)
    assert math.isclose(res.total_length, 2100.0)
    assert len(res.excluded) == 1
    j1 = p.network.find_by_name('J1')
    assert math.isclose(res.nodes[j1.uid]['length'], 175.0)
    assert math.isclose(sum(d['new'] for d in res.nodes.values()), 31.25)


def test_mode_sum_keeps_point_demands(simple_project):
    p = simple_project
    j9 = p.network.find_by_name('J9')
    old = j9.base_demand
    res = D.compute_linear(p, settings(mode='somar'), 10000)
    assert math.isclose(res.nodes[j9.uid]['new'], old + 175 * 0.0125)


def test_population_from_adopted_study(simple_project):
    p = simple_project
    st = compute(PopulationStudy(censuses=[[2000, 10000], [2020, 15000]], start_year=2026,
                                 end_year=2040, adopted_method='geometrico'))
    p.save_population_study(st)
    pop, origin = D.resolve_population(p, D.DemandSettings())
    assert math.isclose(pop, 22500.0) and 'geométrico' in origin
    pop, _ = D.resolve_population(p, D.DemandSettings(population_method='aritmetico'))
    assert math.isclose(pop, 20000.0)
    pop, _ = D.resolve_population(p, D.DemandSettings(population_year=2030))
    assert math.isclose(pop, 10000 * 1.5 ** 1.5)


def test_errors(simple_project):
    p = simple_project
    with pytest.raises(D.DemandError, match='projeção'):
        D.resolve_population(p, D.DemandSettings())
    with pytest.raises(D.DemandError, match='per capita'):
        D.compute_linear(p, settings(per_capita=0), 1000)
    for l in p.network.links.values():
        l.distributes = False
    with pytest.raises(D.DemandError, match='Nenhum trecho'):
        D.compute_linear(p, settings(), 1000)


def test_apply_undo_and_persist(qapp, simple_project, tmp_path):
    from src.ui.controller import DocumentController
    ctrl = DocumentController(simple_project)
    p = ctrl.project
    before = {u: n.base_demand for u, n in p.network.nodes.items() if n.KIND == 'junction'}
    res = D.compute_linear(p, settings(), 10000)
    ctrl.apply(D.apply_changes(p, res), 'Consumos nodais')
    assert math.isclose(sum(n.base_demand for n in p.network.nodes.values()
                            if n.KIND == 'junction'), 31.25)
    ctrl.undo_stack.undo()
    assert {u: n.base_demand for u, n in p.network.nodes.items()
            if n.KIND == 'junction'} == before
    p.demand_settings = settings(per_capita=180)
    path = str(tmp_path / 'd.shcad')
    save_project(p, path)
    q = load_project(path)
    assert q.demand_settings.per_capita == 180
    assert all(l.distributes for l in q.network.links.values())


def test_demand_dialog_cancel_and_apply(qapp, simple_project):
    from PySide6.QtWidgets import QDialog
    from src.ui.controller import DocumentController
    from src.ui.dialogs import demand_dialog as DD
    ctrl = DocumentController(simple_project)
    p = ctrl.project
    dlg = DD.DemandDialog(ctrl)
    assert dlg.rb_manual.isChecked()               # sem projeção adotada
    dlg.manual.setValue(10000)
    assert '10.000 hab' in dlg.lbl_pop.text()
    j5 = p.network.find_by_name('J5')
    old = j5.base_demand
    orig = DD.DemandSummaryDialog.exec
    try:
        DD.DemandSummaryDialog.exec = lambda self: QDialog.Rejected     # Cancelar
        dlg.calculate()
        assert j5.base_demand == old and not dlg.applied
        DD.DemandSummaryDialog.exec = lambda self: QDialog.Accepted     # Aplicar
        dlg.calculate()
    finally:
        DD.DemandSummaryDialog.exec = orig
    assert dlg.applied and math.isclose(p.network.nodes[j5.uid].base_demand, 4.375)
    assert p.demand_settings.manual_population == 10000
    # o resumo é construído com os números do cálculo
    res = D.compute_linear(p, settings(), 10000)
    summ = DD.DemandSummaryDialog(ctrl, res, 'teste')
    assert summ.findChildren(DD.QTableWidget)[0].rowCount() == 9
