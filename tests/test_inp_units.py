"""Conversão de unidades na importação de .inp (curvas e rugosidade)."""

import math

import pytest

from src.hydraulics.models import Curve, Junction, Pipe, Pump, Reservoir, Tank, Valve
from src.hydraulics.project import Project
from src.integration.inp_importer import import_inp
from src.integration.input_exporter import write_inp

INP = """[JUNCTIONS]
J1 10 5
J2 12 3
S 4 0
[RESERVOIRS]
R1 5
[TANKS]
T1 20 2 0 5 0 0 VC
[PIPES]
P1 J1 J2 100 150 {r1} 0 Open
P2 R1 S 10 200 {r2} 0 Open
P3 J2 T1 50 100 {r1} 0 Open
[PUMPS]
B1 S J1 HEAD CB
[VALVES]
V1 J1 J3 100 GPV CP 0
[JUNCTIONS]
J3 8 1
[CURVES]
;PUMP: bomba principal
CB 0 60
CB {q} 50
CB 40 30
;VOLUME: tanque
VC 0 0
VC 5 100
;HEADLOSS: válvula
CP 0 0
CP {q} 2
;PUMP: reserva sem uso
RESERVA 15 40
[OPTIONS]
Units {units}
Headloss {hl}
[END]
"""


def load(tmp_path, units='LPS', hl='D-W', q=20, r1=1.5, r2=0.0015):
    path = tmp_path / 'rede.inp'
    path.write_text(INP.format(units=units, hl=hl, q=q, r1=r1, r2=r2), encoding='utf-8')
    p = Project()
    net, warns = import_inp(str(path), p)
    p.network = net
    return p, warns


def curve(p, name):
    return next(c for c in p.network.curves.values() if c.name == name)


def test_pump_curve_flows_stay_in_lps(tmp_path):
    p, _ = load(tmp_path)
    cb = curve(p, 'CB')
    assert cb.curve_type == 'PUMP'
    assert [pt[0] for pt in cb.points] == pytest.approx([0, 20, 40])
    assert [pt[1] for pt in cb.points] == pytest.approx([60, 50, 30])
    assert curve(p, 'CP').points[1] == pytest.approx([20, 2])          # perda: vazão em L/s
    vc = curve(p, 'VC')
    assert vc.curve_type == 'VOLUME' and vc.points[1] == pytest.approx([5, 100])


def test_unused_curve_keeps_file_values_and_type(tmp_path):
    p, warns = load(tmp_path)
    res = curve(p, 'RESERVA')
    assert res.curve_type == 'PUMP' and res.points == [pytest.approx([15, 40])]
    assert not any('RESERVA' in w for w in warns)                       # tipo veio do arquivo


def test_darcy_weisbach_roughness_in_mm(tmp_path):
    p, _ = load(tmp_path, hl='D-W', r1=1.5, r2=0.0015)
    assert p.sim_options.headloss == 'D-W'
    rough = {l.name: l.roughness for l in p.network.links.values() if l.KIND == 'pipe'}
    assert rough['P1'] == pytest.approx(1.5) and rough['P2'] == pytest.approx(0.0015)


def test_hazen_williams_roughness_unchanged(tmp_path):
    p, _ = load(tmp_path, hl='H-W', r1=140, r2=120)
    rough = {l.name: l.roughness for l in p.network.links.values() if l.KIND == 'pipe'}
    assert rough['P1'] == pytest.approx(140) and rough['P2'] == pytest.approx(120)


def test_other_flow_units_converted_to_lps(tmp_path):
    p, _ = load(tmp_path, units='CMH', hl='H-W', q=72, r1=130, r2=130)   # 72 m³/h = 20 L/s
    assert curve(p, 'CB').points[1][0] == pytest.approx(20)
    assert curve(p, 'RESERVA').points[0][0] == pytest.approx(15 / 3.6)  # sem uso: CMH -> L/s


@pytest.mark.parametrize('hl, rough', [('D-W', 1.5), ('H-W', 140.0)])
def test_export_import_roundtrip(tmp_path, hl, rough):
    """Exportar e reimportar devolve os mesmos valores (curvas, rugosidade)."""
    p = Project()
    p.sim_options.headloss = hl
    net = p.network
    r = Reservoir(name='R', x=0, y=0, head=30)
    s = Junction(name='S', x=10, y=0, elevation=5)
    j = Junction(name='J', x=100, y=0, elevation=10, base_demand=8)
    t = Tank(name='T', x=200, y=0, elevation=30, init_level=2, max_level=5)
    for n in (r, s, j, t):
        net.put(n)
    cb = Curve(name='CB', curve_type='PUMP', points=[[0, 60], [20, 50], [40, 30]])
    vc = Curve(name='VC', curve_type='VOLUME', points=[[0, 0], [5, 120]])
    cp = Curve(name='CP', curve_type='HEADLOSS', points=[[0, 0], [10, 1.5]])
    for c in (cb, vc, cp):
        net.put(c)
    t.volume_curve = vc.uid
    net.put(Pipe(name='P0', start=r.uid, end=s.uid, diameter=200, roughness=rough))
    net.put(Pump(name='B', start=s.uid, end=j.uid, curve=cb.uid))
    k = Junction(name='K', x=150, y=0, elevation=10)
    net.put(k)
    net.put(Valve(name='V', start=j.uid, end=k.uid, valve_type='GPV', headloss_curve=cp.uid))
    net.put(Pipe(name='P1', start=k.uid, end=t.uid, diameter=150, roughness=rough))
    path = str(tmp_path / 'ida.inp')
    write_inp(p, path)
    q = Project()
    net2, _ = import_inp(path, q)
    by = {c.name: c for c in net2.curves.values()}
    for c in (cb, vc, cp):
        assert by[c.name].curve_type == c.curve_type
        got = [v for pt in by[c.name].points for v in pt]
        assert got == pytest.approx([v for pt in c.points for v in pt])
    for l in net2.links.values():
        if l.KIND == 'pipe':
            assert math.isclose(l.roughness, rough)
    assert q.sim_options.headloss == hl
