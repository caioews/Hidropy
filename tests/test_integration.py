"""Testes 12–14, 16, 17, 19 e 20: execução real do motor e do main4.py existente."""

import hashlib
import json
import math
import os
import random

import pytest

from conftest import MAIN4
from src.hydraulics.models import Junction, Pipe
from src.integration import simulation_adapter, optimization_adapter, runner
from src.integration.results_importer import map_simulation


def sha(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


@pytest.fixture(scope='module')
def main4_hash():
    return sha(MAIN4)


# 12 e 13. executar o motor e ler os resultados reais
def test_simulation_runs_and_returns_real_results(simple_project):
    res = simulation_adapter.run_blocking(simple_project)
    assert res['status'] == 'ok', res.get('error')
    assert res['engine'] == 'wntr.sim.EpanetSimulator'
    assert not res['unmapped']
    net = simple_project.network
    assert set(res['nodes']) == set(net.nodes)
    assert set(res['links']) == set(net.links)
    # conferência independente com o próprio WNTR sobre o .inp gerado
    import wntr
    wn = wntr.network.WaterNetworkModel(os.path.join(res['workdir'], 'rede.inp'))
    ref = wntr.sim.EpanetSimulator(wn).run_sim(file_prefix=os.path.join(res['workdir'], 'chk'))
    for uid, d in res['nodes'].items():
        name = net.nodes[uid].name
        assert math.isclose(d['pressure'][0], float(ref.node['pressure'][name].iloc[0]),
                            abs_tol=1e-6)
    # balanço de massa: vazão do reservatório = soma das demandas (L/s)
    demand = sum(n.base_demand for n in net.nodes.values() if n.KIND == 'junction')
    p1 = net.find_by_name('P1')
    assert math.isclose(res['links'][p1.uid]['flow'][0], demand, rel_tol=1e-4)


def test_extended_period_simulation(eps_project):
    res = simulation_adapter.run_blocking(eps_project)
    assert res['status'] == 'ok', res.get('error')
    assert len(res['times']) == 25
    tank = eps_project.network.find_by_name('RES_ELEV')
    levels = res['nodes'][tank.uid]['level']
    assert len(levels) == 25 and len(set(round(l, 3) for l in levels)) > 1
    pump = eps_project.network.find_by_name('B1')
    st = res['links'][pump.uid]['status']
    assert set(st) <= {0.0, 1.0, 2.0, 3.0}


# 14. associação por identificador, independente da ordem
def test_results_associated_by_identifier_not_position(simple_project):
    p = simple_project
    # insere elementos em ordem diferente da ordem dos nomes
    net = p.network
    items = list(net.nodes.values())
    random.Random(3).shuffle(items)
    net.nodes = {e.uid: e for e in items}
    res = simulation_adapter.run_blocking(p)
    assert res['status'] == 'ok'
    # embaralha o JSON devolvido pelo trabalhador e remapeia
    job = simulation_adapter.prepare(p)
    with open(os.path.join(res['workdir'], 'result.json'), encoding='utf-8') as f:
        raw = json.load(f)
    raw['nodes'] = dict(reversed(list(raw['nodes'].items())))
    remapped = map_simulation(raw, job)
    for uid in net.nodes:
        assert remapped['nodes'][uid]['pressure'] == res['nodes'][uid]['pressure']
    j9 = net.find_by_name('J9')
    j1 = net.find_by_name('J1')
    # J9 está mais baixo que J1: deve ter maior pressão
    assert res['nodes'][j9.uid]['pressure'][0] > res['nodes'][j1.uid]['pressure'][0]


# 16, 17 e 20. otimização com o main4.py existente
def test_optimization_runs_existing_script(simple_project, main4_hash):
    p = simple_project
    p.opt_settings.num_geracoes = 8
    p.opt_settings.tam_populacao = 20
    p.network.find_by_name('P13').fixed_in_optimization = True
    lines = []
    res = optimization_adapter.run_blocking(p, on_output=lines.append)
    assert res['status'] == 'ok', res.get('error') + '\n' + res.get('log', '')
    log = '\n'.join(lines)
    assert 'ALVO DE PRESSAO POR NO' in log and 'MELHOR SOLUCAO ENCONTRADA' in log
    assert res['script_unchanged'] is True
    assert sha(MAIN4) == main4_hash
    s = res['summary']
    assert s['custo'] > 0 and isinstance(s['viavel'], bool)
    pipes = res['pipes']
    assert set(pipes) == {l.uid for l in p.network.links.values()}
    fixed = p.network.find_by_name('P13')
    assert pipes[fixed.uid]['fixed'] and pipes[fixed.uid]['opt_diam_mm'] == 150.0
    from src.results import tables
    df = tables.optimization_df(p, res)
    assert df[df['ID'] == 'P13'].iloc[0]['Situação'] == 'existente — mantido'
    assert (df['Situação'] == 'projetado').sum() == len(pipes) - 1
    catalog = {c[1] * 1000 for c in p.opt_settings.catalogo_completo}
    for uid, d in pipes.items():
        assert d['orig_diam_mm'] == p.network.links[uid].diameter
        if not d['fixed']:
            assert d['opt_diam_mm'] in catalog
    # a otimização não altera o modelo
    assert p.network.find_by_name('P1').diameter == 250.0
    # custo da solução = soma de L x custo do catálogo
    total = sum(d['cost_opt'] for d in pipes.values() if not d['fixed'])
    assert math.isclose(total, s['custo'], rel_tol=1e-9)
    assert set(optimization_adapter.optimized_diameters(res)) == \
        {u for u, d in pipes.items() if not d['fixed']}


def test_optimization_rejects_unknown_constant(simple_project, tmp_path, main4_hash):
    from src.integration.workers.optimization_worker import load_patched
    with pytest.raises(RuntimeError, match='NAO_EXISTE'):
        load_patched(MAIN4, {'NAO_EXISTE': 1})
    assert sha(MAIN4) == main4_hash


# 19. erros do mecanismo de cálculo
def test_engine_failure_is_reported(simple_project):
    p = simple_project
    net = p.network
    # componente sem fonte: o EPANET não consegue resolver
    a, b = Junction(name='ILHA_A', x=0, y=0, base_demand=5), Junction(name='ILHA_B', x=10, y=0)
    net.put(a)
    net.put(b)
    net.put(Pipe(name='ILHA', start=a.uid, end=b.uid))
    res = simulation_adapter.run_blocking(p)
    assert res['status'] == 'failed'
    assert res['error']


def test_bad_interpreter_is_reported(simple_project):
    simple_project.settings.python_interpreter = r'C:\nao\existe\python.exe'
    job = simulation_adapter.prepare(simple_project)
    try:
        code, log = runner.run_blocking(job, 30)
    except OSError as e:
        code, log = -1, str(e)
    res = simulation_adapter.collect(job, log)
    assert code != 0 and res['status'] == 'failed'


def test_results_spreadsheet(tmp_path, simple_project, eps_project):
    import pandas as pd
    from src.results import tables
    res = simulation_adapter.run_blocking(simple_project)
    path = str(tmp_path / 'resultados.xlsx')
    tables.export_results(simple_project, res, path)
    nodes = pd.read_excel(path, sheet_name='Nos')
    links = pd.read_excel(path, sheet_name='Trechos')
    assert list(nodes.columns) == ['ID', 'Tipo', 'X (m)', 'Y (m)', 'Cota (m)', 'Demanda (L/s)',
                                   'Pressão (m)', 'Carga hidráulica (m)']
    assert list(links.columns) == ['ID', 'Tipo', 'Nó inicial', 'Nó final', 'Vazão (L/s)',
                                   'Comprimento (m)', 'Diâmetro (mm)', 'Rugosidade', 'Material',
                                   'Velocidade (m/s)', 'Perda de carga unitária (m/km)',
                                   'Perda de carga (m)', 'Fator de atrito', 'Estado operacional']
    j9 = simple_project.network.find_by_name('J9')
    row = nodes[nodes['ID'] == 'J9'].iloc[0]
    assert math.isclose(row['Pressão (m)'], res['nodes'][j9.uid]['pressure'][0], rel_tol=1e-9)
    assert math.isclose(row['X (m)'], j9.x) and math.isclose(row['Cota (m)'], j9.elevation)
    p2 = links[links['ID'] == 'P2'].iloc[0]
    assert p2['Comprimento (m)'] == 200 and p2['Diâmetro (mm)'] == 150
    assert 0.005 < p2['Fator de atrito'] < 0.08 and p2['Estado operacional'] == 'Aberto'
    # período estendido: todos os instantes com coluna de tempo
    res2 = simulation_adapter.run_blocking(eps_project)
    out = tables.export_results(eps_project, res2, str(tmp_path / 'eps.csv'), all_times=True)
    assert len(out) == 2
    df = pd.read_csv(out[0], sep=';', decimal=',')
    assert df.columns[0] == 'Tempo (h)'
    assert len(df) == 25 * len(eps_project.network.nodes)
