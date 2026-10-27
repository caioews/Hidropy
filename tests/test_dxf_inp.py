"""Testes 8–10: DXF (importação, preservação, exportação) e intercâmbio .inp."""

import math

import ezdxf

from src.cad.dxf_exporter import export_dxf
from src.cad.dxf_importer import inspect_dxf, import_dxf, DxfImportOptions
from src.integration.inp_importer import import_inp
from src.integration.input_exporter import write_inp, export_inp
from src.hydraulics.project import Project


# 8 e 9. importar DXF preservando coordenadas, camadas e unidades
def test_import_dxf_preserves_coordinates_and_layers(base_dxf):
    info = inspect_dxf(base_dxf)
    assert info.units == 'm'
    assert {'CURVAS_NIVEL', 'QUADRAS', 'EIXO_RUAS', 'TEXTOS'} <= set(info.layers)
    res = import_dxf(base_dxf, DxfImportOptions(layers={'CURVAS_NIVEL', 'EIXO_RUAS', 'QUADRAS'},
                                                reference_layers={'CURVAS_NIVEL'}))
    assert {e.layer for e in res.entities} == {'CURVAS_NIVEL', 'EIXO_RUAS', 'QUADRAS'}
    ref = {l.name: l for l in res.layers}
    assert ref['CURVAS_NIVEL'].reference and ref['CURVAS_NIVEL'].locked
    assert not ref['EIXO_RUAS'].locked
    # coordenadas idênticas às do arquivo
    doc = ezdxf.readfile(base_dxf)
    line = next(e for e in doc.modelspace() if e.dxftype() == 'LINE')
    imported = [e for e in res.entities if e.geom == 'line']
    assert any(math.isclose(e.points[0][0], line.dxf.start.x) and
               math.isclose(e.points[0][1], line.dxf.start.y) for e in imported)
    # cota Z das curvas de nível preservada
    assert any(e.z == 50.0 for e in res.entities if e.layer == 'CURVAS_NIVEL')
    kinds = {e.geom for e in res.entities}
    assert {'line', 'polyline', 'circle', 'arc'} <= kinds
    # linhas importadas NÃO viram tubulações
    assert all(e.COLLECTION == 'cad' for e in res.entities)


def test_import_dxf_scale_option(base_dxf):
    res = import_dxf(base_dxf, DxfImportOptions(layers={'EIXO_RUAS'}, scale=1000.0))
    raw = import_dxf(base_dxf, DxfImportOptions(layers={'EIXO_RUAS'}))
    assert math.isclose(res.entities[0].points[0][0], raw.entities[0].points[0][0] * 1000)


# 10. exportar desenho para DXF
def test_export_dxf_roundtrip(tmp_path, simple_project, base_dxf):
    p = simple_project
    res = import_dxf(base_dxf)
    for l in res.layers:
        p.ensure_layer(l.name, l.color)
    for e in res.entities:
        p.cad[e.uid] = e
    out = str(tmp_path / 'saida.dxf')
    export_dxf(p, out, symbol_size=2.0)
    doc = ezdxf.readfile(out)
    layers = {e.dxf.layer for e in doc.modelspace()}
    assert {'Tubulações', 'Nós', 'Reservatórios', 'CURVAS_NIVEL', 'QUADRAS'} <= layers
    pipes = [e for e in doc.modelspace() if e.dxftype() == 'LWPOLYLINE'
             and e.dxf.layer == 'Tubulações']
    assert len(pipes) == len(p.network.links)
    texts = [e.dxf.text for e in doc.modelspace() if e.dxftype() == 'TEXT']
    assert any(t.startswith('P1 DN250') for t in texts)
    # reimportação preserva coordenadas da rede
    j1 = p.network.find_by_name('J1')
    circles = [e for e in doc.modelspace() if e.dxftype() == 'CIRCLE' and e.dxf.layer == 'Nós']
    assert any(math.isclose(c.dxf.center.x, j1.x) and math.isclose(c.dxf.center.y, j1.y)
               for c in circles)


def test_inp_export_import_roundtrip(tmp_path, eps_project):
    p = eps_project
    path = str(tmp_path / 'r.inp')
    exp = write_inp(p, path)
    q = Project()
    net, warns = import_inp(path, q)
    assert {e.name for e in net.elements() if e.COLLECTION in ('node', 'link')} == \
        {e.name for e in p.network.elements() if e.COLLECTION in ('node', 'link')}
    assert len(net.controls) == 2 and len(net.curves) == 1 and len(net.patterns) == 1
    assert q.sim_options.duration_h == 24
    vrp = net.find_by_name('VRP1')
    assert vrp.valve_type == 'PRV' and math.isclose(vrp.setting, 30.0)
    pipe = net.find_by_name('RECALQUE')
    assert math.isclose(pipe.diameter, 150.0) and len(pipe.vertices) == 1
    # reexportando, o conteúdo hidráulico permanece o mesmo
    q.network = net
    q.sim_options = p.sim_options
    assert export_inp(q).text.count('\n') == exp.text.count('\n')


def test_inp_names_are_sanitized_and_mapped(simple_project):
    p = simple_project
    j = p.network.find_by_name('J3')
    j.name = 'nó com espaço'
    res = export_inp(p)
    assert 'nó_com_espaço' in res.name_map['nodes']
    assert res.name_map['nodes']['nó_com_espaço'] == j.uid


def test_export_dxf_includes_flow_arrows(tmp_path, simple_project):
    from src.integration import simulation_adapter
    from src.results import thematic_views as TV
    p = simple_project
    sim = simulation_adapter.run_blocking(p)
    signs = TV.flow_signs(sim, 0)
    out = str(tmp_path / 'setas.dxf')
    export_dxf(p, out, symbol_size=2.0, flow_signs=signs)
    doc = ezdxf.readfile(out)
    arrows = [e for e in doc.modelspace() if e.dxftype() == 'SOLID'
              and e.dxf.layer == 'Setas de escoamento']
    assert len(arrows) == sum(1 for v in signs.values() if v)
    # a seta de P1 (R1 -> J1, trecho final horizontal para leste) aponta para +X
    p1 = p.network.find_by_name('P1')
    from src.cad import geometry as G
    (mx, my), _ = G.point_at_fraction(p.network.link_points(p1), 0.5)
    a = min(arrows, key=lambda e: math.dist((e.dxf.vtx0.x, e.dxf.vtx0.y), (mx, my)))
    assert a.dxf.vtx0.x > mx


def test_export_dxf_existing_pipes_dashed_layer(tmp_path, simple_project):
    p = simple_project
    p.network.find_by_name('P2').fixed_in_optimization = True
    out = str(tmp_path / 'exist.dxf')
    export_dxf(p, out)
    doc = ezdxf.readfile(out)
    assert doc.layers.get('Tubulações existentes').dxf.linetype == 'DASHED'
    ex = [e for e in doc.modelspace() if e.dxf.layer == 'Tubulações existentes']
    assert len(ex) == 1
    normal = [e for e in doc.modelspace() if e.dxftype() == 'LWPOLYLINE'
              and e.dxf.layer == 'Tubulações']
    assert len(normal) == len(p.network.links) - 1
