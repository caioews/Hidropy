"""Planta de execução (peças de conexão) e planta de cálculo."""

import math
import os

import ezdxf
import pytest

from conftest import ROOT
from src.cad import dxf_plans as DP
from src.cad import fittings as F
from src.hydraulics.models import Junction, Pipe, Reservoir
from src.hydraulics.project import Project

PRAIA = os.path.join(os.path.dirname(ROOT), 'RDA_Praia das Fontes.inp')

# braços (no bloco) das curvas: o braço 1 fica em -X e o braço 2 a 180° + (180° - deflexão)
CURVE_ARMS = {'UN1-CU5': 90.0, 'UN1-CU6': 45.0, 'UN1-CU7': 22.5, 'UN1-CU8': 11.25}


def net_with(arms, dns=None, center=(1000.0, 2000.0), length=50.0, extra=None):
    """Junção central ligada a junções nas direções dadas (graus)."""
    p = Project()
    c = Junction(name='C', x=center[0], y=center[1])
    p.network.put(c)
    for k, a in enumerate(arms):
        ux, uy = F.unit(a)
        j = Junction(name=f'J{k}', x=c.x + ux * length, y=c.y + uy * length)
        p.network.put(j)
        p.network.put(Pipe(name=f'P{k}', start=c.uid, end=j.uid,
                           diameter=(dns[k] if dns else 100.0)))
    return p, c


def central(p, opts=None):
    pts = F.analyze_network(p, opts or F.FittingOptions(caps=False), scale=1.0)
    return next(fp for fp in pts if fp.name == 'C')


def block_arm_dirs(piece):
    """Direções dos braços no desenho. Curvas: [bolsa (braço 1), braço 2 (ponta se BP)].
    Redução: [lado maior, lado menor]."""
    if piece.block.startswith('UN1-CU'):
        defl = CURVE_ARMS[piece.block.replace('-BP', '')]
        local = [180.0, 180.0 + 180.0 - defl]
    elif piece.block == F.TEE_BLOCK:
        local = [0.0, 180.0, 90.0]
    elif piece.block.startswith('UN1-RE5'):
        local = [180.0, 0.0]
    if piece.mirror:
        local = [-a for a in local]
    return [F.norm(a + piece.rotation) for a in local]


@pytest.mark.parametrize('defl, expected', [
    (2.0, []), (11.25, ["11°15'"]), (22.5, ["22°30'"]), (45.0, ['45°']), (90.0, ['90°']),
    (135.0, ['90°', '45°']), (67.5, ['45°', "22°30'"]), (4.7, []),
])
def test_commercial_curve_choice(defl, expected):
    curves, err = F.best_curves(defl, 3.0)
    assert sorted(c[2] for c in curves) == sorted(expected)


@pytest.mark.parametrize('d2', [90.0, 135.0, 157.5, 168.75])
def test_curve_aligned_with_pipes(d2):
    # interior 'd2' => deflexão 180 - d2
    p, c = net_with([200.0, 200.0 + d2])
    fp = central(p)
    assert len(fp.pieces) == 1 and fp.pieces[0].kind == 'curva'
    pc = fp.pieces[0]
    assert (pc.x, pc.y) == (c.x, c.y)                       # locada na junção
    arms = sorted(block_arm_dirs(pc))
    assert all(min(F.diff(a, b) for b in (200.0, 200.0 + d2)) < 1e-6 for a in arms)
    assert pc.label.startswith('CURVA') and 'PVC DN100' in pc.label


def test_sharp_turn_uses_two_curves():
    # ângulo interno de 45° => deflexão de 135° => curva 90° + curva 45°
    p, c = net_with([200.0, 245.0])
    fp = central(p)
    assert [x.label for x in fp.pieces] == ['CURVA 90° BB PVC DN100',     # junto aos tubos
                                            'CURVA 45° BP PVC DN100']     # encaixa na 1ª
    assert not fp.warnings


def test_straight_reduction_and_bp_ends():
    p, c = net_with([30.0, 210.0], dns=[150.0, 100.0])
    fp = central(p)
    assert [x.label for x in fp.pieces] == ['RED. BB PVC DN150x100']
    assert math.isclose(fp.pieces[0].rotation, 210.0)        # lado menor para o trecho DN100
    p, c = net_with([0.0, 90.0])
    fp = central(p, F.FittingOptions(curve_ends='BP', caps=False))
    assert fp.pieces[0].block == 'UN1-CU5-BP' and ' BP ' in fp.pieces[0].label


def test_tee_perpendicular_and_skewed_branch():
    p, c = net_with([10.0, 190.0, 100.0], dns=[150.0, 150.0, 50.0])
    fp = central(p)
    assert [x.label for x in fp.pieces] == ['TÊ BBB PVC DN150x50']
    arms = block_arm_dirs(fp.pieces[0])
    for want in (10.0, 190.0, 100.0):
        assert min(F.diff(a, want) for a in arms) < 1e-6
    # derivação a 45° da passagem => tê + curva de 45° encaixada no braço do tê
    p, c = net_with([0.0, 180.0, 45.0])
    fp = central(p)
    kinds = [x.kind for x in fp.pieces]
    assert kinds == ['te', 'curva'] and "45°" in fp.pieces[1].label
    d = math.dist((fp.pieces[1].x, fp.pieces[1].y), (c.x, c.y))
    assert math.isclose(d, (F.TEE_ARM + F.CURVES[1][3]) * 1.0, rel_tol=1e-6)


def test_tee_with_reductions_and_cross_and_cap():
    p, c = net_with([0.0, 180.0, 90.0], dns=[150.0, 100.0, 75.0])
    labels = [x.label for x in central(p).pieces]
    assert labels == ['TÊ BBB PVC DN150x75', 'RED. BP PVC DN150x100']   # ponta no tê
    p, c = net_with([0.0, 90.0, 180.0, 270.0], dns=[200.0, 100.0, 200.0, 100.0])
    assert [x.label for x in central(p).pieces] == ['CRUZETA BBBB PVC DN200x100']
    p, c = net_with([0.0])
    fp = central(p, F.FittingOptions(caps=True))
    assert [x.label for x in fp.pieces] == ['CAP PVC DN100']


def test_vertex_bend_and_reservoir_link():
    p = Project()
    a = Reservoir(name='R', x=0, y=0, head=50)
    b = Junction(name='B', x=100, y=100)
    p.network.put(a)
    p.network.put(b)
    p.network.put(Pipe(name='P1', start=a.uid, end=b.uid, vertices=[[100, 0]]))
    pts = F.analyze_network(p, F.FittingOptions(), scale=1.0)
    vx = [fp for fp in pts if fp.kind == 'vertex']
    assert len(vx) == 1 and vx[0].pieces[0].label == 'CURVA 90° BB PVC DN100'
    assert (vx[0].x, vx[0].y) == (100, 0)
    # a junção B é ponta de rede (só um trecho) => CAP
    jb = next(fp for fp in pts if fp.name == 'B')
    assert jb.pieces[0].kind == 'cap'
    assert F.analyze_network(p, F.FittingOptions(vertex_bends=False), 1.0)[0].kind == 'junction'


def test_exec_plan_dxf(tmp_path):
    p, c = net_with([0.0, 180.0, 45.0], dns=[150.0, 150.0, 100.0])
    path = str(tmp_path / 'exec.dxf')
    _, pts = DP.export_exec_plan(p, path, DP.ExecOptions(text_height=2.5))
    doc = ezdxf.readfile(path)
    ins = [e for e in doc.modelspace().query('INSERT') if e.dxf.name.startswith('UN1-')]
    assert {e.dxf.name for e in ins} >= {'UN1-TE2', 'UN1-CU6-BP', 'UN1-CAP'}
    tee = next(e for e in ins if e.dxf.name == 'UN1-TE2')
    assert (tee.dxf.insert.x, tee.dxf.insert.y) == (c.x, c.y)
    assert tee.dxf.xscale == 2.5 and tee.dxf.layer == 'Conexões'
    texts = [m.plain_text() for m in doc.modelspace().query('MTEXT')]
    calls = [m.context.mtext.default_content for m in doc.modelspace().query('MULTILEADER')]
    call = next(t for t in calls if t.startswith('C\\P'))
    assert '1 TÊ BBB PVC DN150x100' in call and '1 CURVA 45° BP PVC DN100' in call
    table = next(t for t in texts if t.startswith('RELAÇÃO DE CONEXÕES'))
    assert '3  CAP PVC' not in table and 'CAP PVC DN150' in table
    assert all(e.dxf.layer == 'Chamadas de conexões'
               for e in doc.modelspace().query('MULTILEADER'))


def test_calc_plan_fields(tmp_path, simple_project):
    from src.integration import simulation_adapter
    p = simple_project
    sim = simulation_adapter.run_blocking(p)
    path = str(tmp_path / 'calc.dxf')
    DP.export_calc_plan(p, path, DP.CalcOptions(link_fields=['name', 'flow'],
                                                node_fields=['pressure'], text_height=2.0),
                        sim)
    doc = ezdxf.readfile(path)
    texts = [m.plain_text() for m in doc.modelspace().query('MTEXT')]
    p1 = p.network.find_by_name('P1')
    q = sim['links'][p1.uid]['flow'][0]
    assert 'P1' in texts and f'Q={q:.2f} L/s'.replace('.', ',') in texts
    assert any(t.startswith('P=') and 'mca' in t for t in texts)
    assert not any('DN' in t for t in texts)                 # diâmetro não selecionado
    assert not any(e.dxf.name.startswith('UN1-') for e in doc.modelspace().query('INSERT'))


@pytest.mark.skipif(not os.path.exists(PRAIA), reason='rede Praia das Fontes ausente')
def test_praia_das_fontes(tmp_path):
    from src.integration.inp_importer import import_inp
    from src.integration import simulation_adapter
    p = Project()
    net, _ = import_inp(PRAIA, p)
    p.network = net
    pts = F.analyze_network(p, F.FittingOptions(), scale=1.0)
    deg = {u: len(net.links_of_node(u)) for u, n in net.nodes.items() if n.KIND == 'junction'}
    q = F.quantities(pts)
    n_tee = sum(v for k, v in q.items() if k.startswith('TÊ'))
    n_cap = sum(v for k, v in q.items() if k.startswith('CAP'))
    assert n_tee == sum(1 for d in deg.values() if d == 3)
    assert n_cap == sum(1 for u, d in deg.items() if d == 1 and all(
        l.KIND == 'pipe' for l in net.links_of_node(u)))
    assert sum(1 for fp in pts if fp.kind == 'vertex') > 0
    # cada curva de junção de grau 2 fica alinhada aos trechos (dentro da tolerância/resíduo)
    for fp in pts:
        if fp.kind == 'junction' and len(fp.directions) == 2 and len(fp.pieces) == 1 \
                and fp.pieces[0].kind == 'curva':
            arms = block_arm_dirs(fp.pieces[0])
            res = abs(F.diff(fp.directions[0] + 180, fp.directions[1]) - fp.pieces[0].angle)
            errs = sorted(min(F.diff(arm, d) for d in fp.directions) for arm in arms)
            assert errs[0] < 1e-6 and errs[1] <= res + 1e-6   # um braço exato, outro no resíduo
    _, pts2 = DP.export_exec_plan(p, str(tmp_path / 'exec.dxf'), DP.ExecOptions(text_height=1.0))
    doc = ezdxf.readfile(str(tmp_path / 'exec.dxf'))
    n_ins = sum(1 for e in doc.modelspace().query('INSERT') if e.dxf.name.startswith('UN1-'))
    assert n_ins == sum(len(fp.pieces) for fp in pts2)
    sim = simulation_adapter.run_blocking(p)
    assert sim['status'] == 'ok'
    DP.export_calc_plan(p, str(tmp_path / 'calc.dxf'),
                        DP.CalcOptions(link_fields=list(DP.LINK_FIELDS),
                                       node_fields=list(DP.NODE_FIELDS)), sim)
    assert ezdxf.readfile(str(tmp_path / 'calc.dxf')).modelspace().query('MTEXT')


def test_export_dialog(qapp, simple_project, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    from src.ui.controller import DocumentController
    from src.ui.dialogs.dxf_export_dialog import DxfExportDialog
    ctrl = DocumentController(simple_project)
    dlg = DxfExportDialog(ctrl)
    assert not dlg.link_cb['flow'].isEnabled()             # sem simulação
    dlg.rb_exec.setChecked(True)
    dlg.ends.setCurrentIndex(dlg.ends.findData('BP'))
    dlg.analyze()
    assert dlg.review.rowCount() > 0 and 'TÊ' in dlg.qty.toPlainText()
    out = str(tmp_path / 'dlg.dxf')
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', staticmethod(lambda *a, **k: (out, '')))
    monkeypatch.setattr(QMessageBox, 'information', staticmethod(lambda *a, **k: None))
    dlg.export()
    assert os.path.exists(out)
    assert ctrl.project.settings.dxf_plan == 'exec' and ctrl.project.settings.fit_curve_ends == 'BP'
    names = {e.dxf.name for e in ezdxf.readfile(out).modelspace().query('INSERT')}
    assert any(n.endswith('-BP') for n in names)


def test_coincident_vertex_does_not_create_false_bends():
    """Vértice a milímetros do nó (caso da junção 824 da Praia das Fontes): a dobra real de
    ~91° vira uma única curva de 90°, sem curvas falsas na junção e no vértice."""
    p = Project()
    c = Junction(name='C', x=0.0, y=0.0)
    a = Junction(name='A', x=80.0, y=-16.0)                  # trecho para leste
    b = Junction(name='B', x=-3.0, y=-17.0)                  # trecho para o sul
    for n in (c, a, b):
        p.network.put(n)
    p.network.put(Pipe(name='E', start=c.uid, end=a.uid))
    # primeiro vértice a 4 mm do nó, apontando para trás (ruído de digitalização)
    p.network.put(Pipe(name='S', start=c.uid, end=b.uid, vertices=[[-0.0039, -0.001]]))
    pts = F.analyze_network(p, F.FittingOptions(caps=False), scale=1.0)
    labels = {fp.name: [x.label for x in fp.pieces] for fp in pts}
    assert labels['C'] == ['CURVA 90° BB PVC DN100']
    assert not any(fp.kind == 'vertex' for fp in pts)


def test_clean_points_keeps_ends_and_real_vertices():
    pts = [(0, 0), (0.001, 0), (10, 0), (10, 0.2), (10, 10), (10, 10.3)]
    kept = F.clean_points(pts, 0.5)
    assert [q for q, _ in kept] == [(0, 0), (10, 0), (10, 10.3)]
    assert kept[1][1] == 2                                   # índice original preservado
    assert [q for q, _ in F.clean_points(pts, 0.0)] == pts[:1] + pts[1:]


@pytest.mark.parametrize('style, types', [
    ('mleader', {'MULTILEADER'}), ('leader', {'LEADER', 'MTEXT'}),
    ('linhas', {'LWPOLYLINE', 'CIRCLE', 'MTEXT'})])
def test_callout_styles(tmp_path, style, types):
    p, c = net_with([0.0, 180.0, 45.0], dns=[150.0, 150.0, 100.0])
    path = str(tmp_path / f'{style}.dxf')
    DP.export_exec_plan(p, path, DP.ExecOptions(text_height=2.0, callout_style=style))
    doc = ezdxf.readfile(path)
    calls = [e for e in doc.modelspace() if e.dxf.layer == 'Chamadas de conexões']
    assert {e.dxftype() for e in calls} == types
    assert len(doc.audit().errors) == 0
    if style == 'mleader':
        txts = [e.context.mtext.default_content for e in calls]
        assert any(t.startswith('C\\P1 TÊ BBB PVC DN150x100') for t in txts)
    if style == 'leader':
        ld = next(e for e in calls if e.dxftype() == 'LEADER')
        mt = doc.entitydb[ld.dxf.annotation_handle]
        assert mt.dxftype() == 'MTEXT' and 'TÊ' in mt.text



def _toward(piece, target):
    return F.angle_of((piece.x, piece.y), target)


@pytest.mark.parametrize('branch', [45.0, 135.0])
def test_curve_on_tee_branch_is_spigot_toward_tee(branch):
    """Curva encaixada na bolsa do tê: PONTA voltada para o tê, bolsa para o tubo."""
    p, c = net_with([0.0, 180.0, branch])
    fp = central(p, F.FittingOptions(caps=False, curve_ends='auto'))
    tee, curve = fp.pieces[0], fp.pieces[1]
    assert tee.label.startswith('TÊ BBB') and curve.label.startswith('CURVA 45° BP')
    assert curve.block == 'UN1-CU6-BP'
    sock, spig = block_arm_dirs(curve)
    assert F.diff(spig, _toward(curve, (c.x, c.y))) < 1e-6          # ponta -> tê
    assert F.diff(sock, branch) < 1e-6                               # bolsa -> tubo


def test_second_curve_of_pair_is_spigot_toward_first():
    p, c = net_with([200.0, 245.0])                                  # 90° + 45°
    fp = central(p)
    first, second = fp.pieces
    assert first.ends == 'BB' and (first.x, first.y) == (c.x, c.y)   # junto aos dois tubos
    assert second.ends == 'BP'
    sock, spig = block_arm_dirs(second)
    assert F.diff(spig, _toward(second, (first.x, first.y))) < 1e-6
    assert min(F.diff(sock, d) for d in (200.0, 245.0)) < 1e-6


def test_reductions_spigot_only_when_attached_to_piece():
    p, c = net_with([30.0, 210.0], dns=[150.0, 100.0])               # só redução, entre tubos
    assert [x.label for x in central(p).pieces] == ['RED. BB PVC DN150x100']
    p, c = net_with([0.0, 180.0, 90.0], dns=[150.0, 100.0, 150.0])
    red = central(p).pieces[1]
    assert red.label == 'RED. BP PVC DN150x100' and red.block == 'UN1-RE5-BP'
    big, small = block_arm_dirs(red)
    assert F.diff(big, _toward(red, (c.x, c.y))) < 1e-6             # ponta (maior) -> tê


@pytest.mark.parametrize('mode, ends', [('BB', {'BB'}), ('BP', {'BP'})])
def test_fixed_end_modes(mode, ends):
    p, c = net_with([0.0, 180.0, 45.0], dns=[150.0, 100.0, 150.0])
    fp = central(p, F.FittingOptions(caps=False, curve_ends=mode))
    assert {x.ends for x in fp.pieces if x.kind == 'curva'} == ends
    assert next(x for x in fp.pieces if x.kind == 'reducao').ends == 'BB'


def test_mirrored_blocks_exported_with_negative_y_scale(tmp_path):
    pts_ok = 0
    for branch in (45.0, 135.0):
        p, c = net_with([0.0, 180.0, branch])
        path = str(tmp_path / f'm{int(branch)}.dxf')
        _, pts = DP.export_exec_plan(p, path, DP.ExecOptions(text_height=2.0))
        curve = next(pc for fp in pts for pc in fp.pieces if pc.kind == 'curva')
        ins = next(e for e in ezdxf.readfile(path).modelspace().query('INSERT')
                   if e.dxf.name == curve.block)
        assert (ins.dxf.yscale < 0) == curve.mirror and ins.dxf.xscale == 2.0
        pts_ok += curve.mirror
    assert pts_ok == 1                     # um dos dois lados exige o bloco espelhado
