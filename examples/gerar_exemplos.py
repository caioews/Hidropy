"""Gera os arquivos de exemplo usados nos testes e na documentação.

    python examples/gerar_exemplos.py

Cria:
  rede_exemplo.shcad / rede_exemplo.inp ........ rede malhada por gravidade (regime permanente)
  rede_periodo_estendido.shcad ................. tanque, bomba, válvula, padrão 24 h e controles
  base_topografica.dxf ......................... desenho de referência (curvas de nível, quadras,
                                                 textos) em coordenadas UTM
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from src.hydraulics.models import (Junction, Reservoir, Tank, Pipe, Pump, Valve, Curve,  # noqa
                                   Pattern, Control)
from src.hydraulics.project import Project  # noqa
from src.hydraulics.project_io import save_project  # noqa
from src.integration.input_exporter import write_inp  # noqa

X0, Y0 = 350000.0, 7400000.0


def rede_exemplo() -> Project:
    p = Project()
    p.meta['title'] = 'Rede de exemplo - malha por gravidade'
    p.display_origin = (X0, Y0)
    net = p.network
    R = Reservoir(name='R1', x=X0 - 250, y=Y0 + 450, head=92.0, ground_elevation=88.0)
    net.put(R)
    elev = [[66, 64, 61], [63, 60, 57], [60, 56, 52]]
    dem = [[2.0, 3.0, 2.5], [3.5, 4.0, 3.0], [2.5, 3.0, 4.5]]
    J = {}
    for i in range(3):
        for j in range(3):
            n = Junction(name=f'J{i * 3 + j + 1}', x=X0 + 200 * j, y=Y0 + 300 - 150 * i,
                         elevation=elev[i][j], base_demand=dem[i][j])
            net.put(n)
            J[(i, j)] = n
    k = 1

    def pipe(a, b, d=150.0, verts=None):
        nonlocal k
        net.put(Pipe(name=f'P{k}', start=a.uid, end=b.uid, diameter=d, roughness=140.0,
                     vertices=verts or []))
        k += 1

    pipe(R, J[(0, 0)], 250.0, verts=[[X0 - 250, Y0 + 300]])
    for i in range(3):
        for j in range(3):
            if j < 2:
                pipe(J[(i, j)], J[(i, j + 1)])
            if i < 2:
                pipe(J[(i, j)], J[(i + 1, j)])
    return p


def rede_periodo_estendido() -> Project:
    p = Project()
    p.meta['title'] = 'Rede de exemplo - período estendido'
    p.display_origin = (X0, Y0)
    o = p.sim_options
    o.duration_h, o.hydraulic_step_h, o.pattern_step_h, o.report_step_h = 24, 1, 1, 1
    net = p.network
    pat = Pattern(name='CONSUMO', multipliers=[0.6, 0.5, 0.5, 0.5, 0.6, 0.8, 1.1, 1.4, 1.5, 1.4,
                                               1.3, 1.2, 1.2, 1.2, 1.1, 1.1, 1.2, 1.3, 1.4, 1.3,
                                               1.1, 0.9, 0.8, 0.7])
    net.put(pat)
    curve = Curve(name='CB1', curve_type='PUMP', points=[[0, 60], [20, 52], [40, 30]])
    net.put(curve)
    R = Reservoir(name='POCO', x=X0 - 400, y=Y0, head=20.0)
    S = Junction(name='SUCCAO', x=X0 - 300, y=Y0, elevation=18.0)
    T = Tank(name='RES_ELEV', x=X0, y=Y0 + 200, elevation=55.0, init_level=3.0,
             min_level=0.5, max_level=6.0, diameter=12.0)
    for n in (R, S, T):
        net.put(n)
    js = []
    for i, (dx, dy, z, q) in enumerate([(200, 150, 30, 3), (400, 150, 28, 4), (200, -50, 26, 3),
                                         (400, -50, 25, 5), (600, 50, 22, 2)], 1):
        j = Junction(name=f'N{i}', x=X0 + dx, y=Y0 + dy, elevation=z, base_demand=q,
                     demand_pattern=pat.uid)
        net.put(j)
        js.append(j)
    N1 = Junction(name='JUSANTE_B', x=X0 - 150, y=Y0, elevation=19.0)
    net.put(N1)
    pump = Pump(name='B1', start=S.uid, end=N1.uid, curve=curve.uid)
    net.put(Pipe(name='SUC', start=R.uid, end=S.uid, diameter=200, roughness=130))
    net.put(pump)
    net.put(Pipe(name='RECALQUE', start=N1.uid, end=T.uid, diameter=150, roughness=130,
                 vertices=[[X0 - 150, Y0 + 200]]))
    net.put(Pipe(name='SAIDA', start=T.uid, end=js[0].uid, diameter=200, roughness=130))
    pairs = [(0, 1), (0, 2), (1, 3), (2, 3), (3, 4), (1, 4)]
    for k, (a, b) in enumerate(pairs, 1):
        net.put(Pipe(name=f'D{k}', start=js[a].uid, end=js[b].uid, diameter=100, roughness=140))
    # válvula redutora na entrada da zona baixa
    Z = Junction(name='ZONA_BAIXA', x=X0 + 700, y=Y0 - 150, elevation=10.0, base_demand=1.5,
                 demand_pattern=pat.uid)
    net.put(Z)
    net.put(Valve(name='VRP1', start=js[4].uid, end=Z.uid, valve_type='PRV', diameter=75,
                  setting=30.0))
    net.put(Control(name='CTRL1', link=pump.uid, action='CLOSED', condition='IF NODE ABOVE',
                    node=T.uid, value='5.5'))
    net.put(Control(name='CTRL2', link=pump.uid, action='OPEN', condition='IF NODE BELOW',
                    node=T.uid, value='2'))
    return p


def base_dxf(path):
    import math
    import ezdxf
    doc = ezdxf.new('R2010', setup=True)
    doc.header['$INSUNITS'] = 6   # metros
    msp = doc.modelspace()
    doc.layers.add('CURVAS_NIVEL', color=33)
    doc.layers.add('QUADRAS', color=8)
    doc.layers.add('EIXO_RUAS', color=1)
    doc.layers.add('TEXTOS', color=7)
    for k, z in enumerate(range(50, 95, 5)):
        r = 120 + 70 * k
        pts = [(X0 - 300 + r * math.cos(a / 30 * math.pi / 2),
                Y0 + 500 - r * math.sin(a / 30 * math.pi / 2), z) for a in range(31)]
        pl = msp.add_polyline3d(pts, dxfattribs={'layer': 'CURVAS_NIVEL'})
        pl.dxf.color = 256
        msp.add_text(f'{z}', dxfattribs={'layer': 'CURVAS_NIVEL', 'height': 6}).set_placement(
            (pts[15][0], pts[15][1]))
    for i in range(2):
        for j in range(2):
            x, y = X0 + 25 + 200 * j, Y0 + 25 + 150 * (1 - i)
            msp.add_lwpolyline([(x, y), (x + 150, y), (x + 150, y + 100), (x, y + 100)],
                               close=True, dxfattribs={'layer': 'QUADRAS'})
    for i in range(3):
        msp.add_line((X0 - 50, Y0 + 300 - 150 * i), (X0 + 450, Y0 + 300 - 150 * i),
                     dxfattribs={'layer': 'EIXO_RUAS'})
        msp.add_line((X0 + 200 * i, Y0 - 50), (X0 + 200 * i, Y0 + 350),
                     dxfattribs={'layer': 'EIXO_RUAS'})
    msp.add_circle((X0 - 250, Y0 + 450), 15, dxfattribs={'layer': 'QUADRAS'})
    msp.add_arc((X0 + 400, Y0), 30, 0, 90, dxfattribs={'layer': 'QUADRAS'})
    msp.add_text('LOTEAMENTO EXEMPLO', dxfattribs={'layer': 'TEXTOS', 'height': 12}
                 ).set_placement((X0, Y0 + 380))
    doc.saveas(path)


if __name__ == '__main__':
    p1 = rede_exemplo()
    save_project(p1, os.path.join(HERE, 'rede_exemplo.shcad'), backup=False)
    write_inp(p1, os.path.join(HERE, 'rede_exemplo.inp'), p1.meta['title'])
    p2 = rede_periodo_estendido()
    save_project(p2, os.path.join(HERE, 'rede_periodo_estendido.shcad'), backup=False)
    write_inp(p2, os.path.join(HERE, 'rede_periodo_estendido.inp'), p2.meta['title'])
    base_dxf(os.path.join(HERE, 'base_topografica.dxf'))
    print('Exemplos gerados em', HERE)
