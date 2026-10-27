"""Projeção populacional: métodos aritmético e geométrico, armazenamento e diálogo."""

import math

import pytest

from src.hydraulics.population import PopulationStudy, PopulationError, compute
from src.hydraulics.project import Project
from src.hydraulics.project_io import load_project, save_project

CENSOS = [[2010, 12000], [2000, 10000], [2020, 15000]]     # fora de ordem de propósito


def study(**kw):
    d = dict(censuses=CENSOS, start_year=2026, end_year=2046, step=5)
    d.update(kw)
    return compute(PopulationStudy(**d))


def test_arithmetic_and_geometric_first_last():
    s = study(base='extremos', end_year=2040, adopted_method='aritmetico')
    assert s.censuses[0] == [2000, 10000.0]                    # ordenado por ano
    assert math.isclose(s.ka, 250.0)                          # (15000-10000)/20
    assert math.isclose(s.kg, math.log(1.5) / 20)
    assert math.isclose(s.population(2040, 'aritmetico'), 20000.0)
    assert math.isclose(s.population(2040, 'geometrico'), 22500.0)   # 10000 * 1,5^2
    assert math.isclose(s.design_population, 20000.0)
    assert math.isclose(s.growth_rate, 1.5 ** (1 / 20) - 1)
    # métodos reproduzem os censos usados na base
    assert math.isclose(s.population(2020, 'geometrico'), 15000.0)


def test_last_two_censuses_base():
    s = study(base='ultimos', end_year=2040, adopted_method='geometrico')
    assert math.isclose(s.ka, 300.0)
    assert math.isclose(s.population(2040, 'aritmetico'), 21000.0)
    assert math.isclose(s.design_population, 12000 * 1.25 ** 3)


def test_table_years_include_horizon():
    s = study(start_year=2026, end_year=2047, step=5)
    years = [r['ano'] for r in s.table]
    assert years == [2026, 2031, 2036, 2041, 2046, 2047]
    assert all(r['geometrico'] > r['aritmetico'] for r in s.table)   # crescimento acelerado


@pytest.mark.parametrize('kw, msg', [
    (dict(censuses=[[2000, 100]]), 'dois censos'),
    (dict(censuses=[[2000, 100], [2000, 200]]), 'repetidos'),
    (dict(censuses=[[2000, 100], [2010, 0]]), 'maior que zero'),
    (dict(end_year=2020, start_year=2030), 'alcance'),
])
def test_invalid_inputs(kw, msg):
    with pytest.raises(PopulationError, match=msg):
        study(**kw)


def test_declining_population_warns():
    s = study(censuses=[[2000, 10000], [2020, 6000]], end_year=2080, start_year=2026)
    assert 'negativa' in s.notes
    assert s.population(2080, 'geometrico') > 0


def test_study_saved_in_project(tmp_path):
    p = Project()
    s = study(adopted_method='geometrico', name='Bairro A')
    p.save_population_study(s)
    other = study(base='ultimos', name='Bairro B')
    p.save_population_study(other, adopt=False)
    path = str(tmp_path / 'pop.shcad')
    save_project(p, path)
    q = load_project(path)
    assert [x.name for x in q.population_studies] == ['Bairro A', 'Bairro B']
    adopted = q.population_study()
    assert adopted.name == 'Bairro A'
    assert math.isclose(adopted.design_population, s.design_population)
    assert adopted.table == s.table
    q.delete_population_study(adopted.uid)
    assert q.population_study().name == 'Bairro B'


def test_population_dialog(qapp):
    from PySide6.QtWidgets import QMessageBox
    from src.ui.controller import DocumentController
    from src.ui.dialogs.population_dialog import PopulationDialog, parse_number
    assert parse_number('12.345') == 12345 and parse_number('12.345,5') == 12345.5
    assert parse_number('1234.5') == 1234.5 and parse_number('15000') == 15000
    ctrl = DocumentController(Project())
    dlg = PopulationDialog(ctrl)
    for y, pop in ((2000, '10.000'), (2010, '12000'), (2020, '15000')):
        dlg.add_census(y, None)
        dlg.census.item(dlg.census.rowCount() - 1, 1).setText(pop)
    dlg.start.setValue(2020)
    dlg.end.setValue(2040)
    dlg.method.setCurrentIndex(dlg.method.findData('geometrico'))
    assert dlg.btn_save.isEnabled()
    assert '22.500 hab' in dlg.summary.text()
    assert dlg.table.rowCount() == 21
    assert dlg.save()
    st = ctrl.project.population_study()
    assert st is not None and math.isclose(st.design_population, 22500.0)
    assert ctrl.dirty
    # dados inválidos desabilitam o salvamento
    dlg.census.item(0, 1).setText('abc')
    assert not dlg.btn_save.isEnabled()
    orig = QMessageBox.question
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Discard)
    try:
        dlg.close()
    finally:
        QMessageBox.question = orig
    # reabrir carrega o estudo adotado
    dlg2 = PopulationDialog(ctrl)
    assert dlg2.census.rowCount() == 3 and '22.500 hab' in dlg2.summary.text()
    dlg2.close()
