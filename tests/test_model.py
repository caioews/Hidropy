"""Testes 1–7 e 11: projeto, persistência, conectividade, edição, desfazer/refazer, validação."""

import json
import math
import os

from src.hydraulics import connectivity, editing
from src.hydraulics.models import Junction, Reservoir, Pipe, Pattern, CadEntity
from src.hydraulics.project import Project
from src.hydraulics.project_io import save_project, load_project, project_to_dict
from src.hydraulics.validation import validate, has_errors


def _codes(issues):
    return {i.code for i in issues}


# 1. projeto vazio
def test_empty_project_roundtrip(tmp_path):
    p = Project()
    path = tmp_path / 'vazio.shcad'
    save_project(p, str(path))
    q = load_project(str(path))
    assert not q.network.nodes and not q.cad
    assert {l.name for l in q.layers.values()} >= {'Tubulações', 'Nós', 'Base topográfica'}


# 2 e 3. criar, salvar, reabrir e preservar os dados
def test_save_and_reopen_preserves_everything(tmp_path, simple_project):
    p = simple_project
    p.cad['x'] = CadEntity(uid='x', geom='text', points=[[1, 2]], text='Olá', layer='Textos')
    p.network.put(Pattern(name='PAD', multipliers=[0.5, 1.5]))
    p.sim_options.duration_h = 12
    p.opt_settings.num_geracoes = 7
    path = tmp_path / 'rede.shcad'
    save_project(p, str(path))
    save_project(p, str(path))                       # segunda gravação gera .bak
    assert os.path.exists(str(path) + '.bak')
    q = load_project(str(path))
    a, b = project_to_dict(p), project_to_dict(q)
    a['meta'].pop('modified'), b['meta'].pop('modified')
    assert a == b
    assert q.cad['x'].text == 'Olá'
    assert q.sim_options.duration_h == 12 and q.opt_settings.num_geracoes == 7
    # JSON legível em UTF-8
    with open(path, encoding='utf-8') as f:
        assert json.load(f)['format'] == 'SHCAD'


# 4 e 5. nós, tubulações e conexão hidráulica explícita
def test_nodes_pipes_and_connectivity():
    p = Project()
    net = p.network
    r = Reservoir(name='R', x=0, y=0, head=50)
    a = Junction(name='A', x=100, y=0, elevation=10, base_demand=1)
    b = Junction(name='B', x=200, y=0, elevation=10)
    iso = Junction(name='ISO', x=500, y=500)
    for n in (r, a, b, iso):
        net.put(n)
    net.put(Pipe(name='P1', start=r.uid, end=a.uid))
    net.put(Pipe(name='P2', start=a.uid, end=b.uid, vertices=[[150, 50]]))
    assert {l.name for l in net.links_of_node(a.uid)} == {'P1', 'P2'}
    assert connectivity.isolated_nodes(net) == [iso.uid]
    comps = connectivity.components(net)
    assert {r.uid, a.uid, b.uid} in comps
    p2 = net.links_of_node(b.uid)[0]
    assert math.isclose(net.geometric_length(p2), 2 * math.hypot(50, 50))
    # mover um nó atualiza a geometria da tubulação (comprimento automático)
    net.nodes[b.uid].x = 250
    assert net.geometric_length(p2) > 2 * math.hypot(50, 50)


def test_hydraulic_length_independent_of_geometry():
    p = Project()
    a, b = Junction(name='A'), Junction(name='B', x=30, y=40)
    p.network.put(a)
    p.network.put(b)
    pipe = Pipe(name='P', start=a.uid, end=b.uid, auto_length=False, length=120.0)
    p.network.put(pipe)
    assert p.network.geometric_length(pipe) == 50.0
    assert p.network.hydraulic_length(pipe) == 120.0
    pipe.auto_length = True
    assert p.network.hydraulic_length(pipe) == 50.0


# 6 e 7. edição de propriedades com desfazer / refazer
def test_edit_undo_redo(qapp, simple_project):
    from src.ui.controller import DocumentController
    ctrl = DocumentController(simple_project)
    pipe = ctrl.project.network.find_by_name('P2')
    ctrl.update_element(pipe.uid, diameter=200.0, material='PEAD')
    assert ctrl.project.network.links[pipe.uid].diameter == 200.0
    j = ctrl.project.network.find_by_name('J5')
    ctrl.apply(editing.move(ctrl.project, [j.uid], 10, -5), 'Mover')
    assert ctrl.project.network.nodes[j.uid].x == j.x + 10
    n_before = len(ctrl.project.network.links)
    ctrl.delete([j.uid])                     # exclui o nó e as 4 tubulações ligadas
    assert j.uid not in ctrl.project.network.nodes
    assert len(ctrl.project.network.links) == n_before - 4
    assert ctrl.dirty
    for _ in range(3):
        ctrl.undo_stack.undo()
    assert ctrl.project.network.links[pipe.uid].diameter == 150.0
    assert ctrl.project.network.nodes[j.uid].x == j.x
    assert len(ctrl.project.network.links) == n_before
    ctrl.undo_stack.redo()
    assert ctrl.project.network.links[pipe.uid].diameter == 200.0
    assert ctrl.project.network.links[pipe.uid].material == 'PEAD'


def test_auto_length_follows_node_move(qapp, simple_project):
    from src.ui.controller import DocumentController
    ctrl = DocumentController(simple_project)
    net = ctrl.project.network
    p = net.find_by_name('P2')
    j2 = net.nodes[p.end]
    ctrl.apply(editing.move(ctrl.project, [j2.uid], 100, 0), 'Mover')
    assert math.isclose(net.links[p.uid].length, net.geometric_length(net.links[p.uid]))


# 11. validação antes da execução
def test_validation_detects_problems(simple_project):
    p = simple_project
    assert not has_errors(validate(p))
    net = p.network
    pipe = net.find_by_name('P3')
    pipe.diameter = 0
    net.find_by_name('J2').name = 'J1'                         # duplicado
    net.find_by_name('J9').demand_pattern = 'nao_existe'
    iso = Junction(name='SOLTO', x=1, y=1)
    net.put(iso)
    on_pipe = Junction(name='SOBRE_TUBO', x=350100.0, y=7400300.0)  # sobre P2 sem conexão
    net.put(on_pipe)
    net.put(Pipe(name='PX', start=on_pipe.uid, end=iso.uid))
    issues = validate(p)
    codes = _codes(issues)
    assert {'DIAMETRO_INVALIDO', 'ID_DUPLICADO', 'PADRAO_INEXISTENTE',
            'CONEXAO_VISUAL', 'SEM_FONTE_COMPONENTE'} <= codes
    assert has_errors(issues)
    assert any(not i.is_error for i in issues)      # advertências separadas dos erros


def test_validation_no_source_and_isolated():
    p = Project()
    p.network.put(Junction(name='A'))
    codes = _codes(validate(p))
    assert {'SEM_FONTE', 'NO_DESCONECTADO'} <= codes


def test_split_pipe_keeps_model_consistent(simple_project):
    p = simple_project
    net = p.network
    pipe = net.find_by_name('P2')
    a, b = net.nodes[pipe.start], net.nodes[pipe.end]
    changes, j = editing.split_pipe(p, pipe.uid, (a.x + b.x) / 2, a.y + 1)
    for uid, before, after in changes:
        p.put_dict(after)
    net.invalidate()
    assert net.links[pipe.uid].end == j.uid
    new = [l for l in net.links.values() if l.start == j.uid]
    assert len(new) == 1 and new[0].end == b.uid
    assert math.isclose(j.elevation, (a.elevation + b.elevation) / 2)
    assert not has_errors(validate(p))


def test_transform_copy_paste(simple_project):
    p = simple_project
    net = p.network
    sel = [n.uid for n in net.nodes.values()] + [l.uid for l in net.links.values()]
    clip = editing.copy_selection(p, sel)
    changes = editing.paste(p, clip, 1000, 0)
    assert len(changes) == len(sel)
    for uid, _, after in changes:
        p.put_dict(after)
    names = [e.name for e in net.elements()]
    assert len(names) == len(set(names))
    # rotação de 90° e espelhamento preservam distâncias
    j1 = net.find_by_name('J1')
    for uid, _, after in editing.rotate(p, [j1.uid], j1.x - 10, j1.y, 90):
        p.put_dict(after)
    j1b = net.nodes[j1.uid]
    assert math.isclose(j1b.x, j1.x - 10, abs_tol=1e-6)
    assert math.isclose(j1b.y, j1.y + 10, abs_tol=1e-6)
    for uid, _, after in editing.mirror(p, [j1.uid], j1b.x + 5, 0, j1b.x + 5, 1):
        p.put_dict(after)
    assert math.isclose(net.nodes[j1.uid].x, j1b.x + 10, abs_tol=1e-6)


def test_cad_to_pipes_with_confirmation_data():
    p = Project()
    p.network.put(Junction(name='EXIST', x=100, y=0))
    for pts in ([[0, 0], [100.01, 0]], [[100, 0], [100, 50], [150, 50]]):
        e = CadEntity(geom='polyline', points=pts)
        p.cad[e.uid] = e
    plan = editing.cad_to_pipes(p, list(p.cad), tol=0.05, per_segment=False)
    assert plan.n_pipes == 2
    assert plan.n_reused_nodes == 1        # extremidades em (100,0) usam o nó existente
    assert plan.n_new_nodes == 2           # (0,0) e (150,50)
    for uid, _, after in plan.changes:
        p.put_dict(after)
    assert len(p.network.links_of_node(p.network.find_by_name('EXIST').uid)) == 2
    assert len(p.cad) == 2                 # desenho original preservado


def test_existing_pipes_validation_and_conversion(simple_project):
    p = simple_project
    pipe = p.network.find_by_name('P2')
    for uid, _, after in editing.set_existing(p, [pipe.uid, p.network.find_by_name('J1').uid],
                                              True):
        p.put_dict(after)
    assert pipe.uid in p.network.links and p.network.links[pipe.uid].existing
    assert 'EXISTENTE_FORA_CATALOGO' not in _codes(validate(p))
    p.network.links[pipe.uid].diameter = 160.0        # fora do catálogo: só advertência
    issues = [i for i in validate(p) if i.code == 'EXISTENTE_FORA_CATALOGO']
    assert issues and not issues[0].is_error
    q = Project()
    e = CadEntity(geom='line', points=[[0, 0], [10, 0]])
    q.cad[e.uid] = e
    plan = editing.cad_to_pipes(q, [e.uid], tol=0.01, existing=True)
    pipes = [a for _, _, a in plan.changes if a['kind'] == 'pipe']
    assert pipes and all(a['fixed_in_optimization'] for a in pipes)
