"""Plantas DXF: planta de CÁLCULO (resultados selecionáveis) e planta de EXECUÇÃO
(peças de conexão em cada junção e vértice, com chamadas e quadro de quantidades).

A escala dos blocos de conexão é a mesma da altura de texto escolhida: os blocos da
biblioteca foram desenhados para texto de altura 1,0.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..results import thematic_views as TV
from . import fittings as F
from .dxf_exporter import build_network_doc
from .fitting_library import import_blocks

LINK_FIELDS = {
    'name': 'Identificador', 'dn': 'Diâmetro (DN)', 'length': 'Comprimento',
    'material': 'Material', 'roughness': 'Rugosidade', 'flow': 'Vazão',
    'velocity': 'Velocidade', 'unit_headloss': 'Perda de carga unitária',
    'headloss': 'Perda de carga', 'friction': 'Fator de atrito', 'status': 'Estado',
}
NODE_FIELDS = {
    'name': 'Identificador', 'elevation': 'Cota', 'demand': 'Demanda', 'pressure': 'Pressão',
    'head': 'Carga hidráulica',
}
RESULT_LINK = {'flow', 'velocity', 'unit_headloss', 'headloss', 'friction', 'status'}
RESULT_NODE = {'demand', 'pressure', 'head'}

L_LINK, L_NODE = 'Rótulos de trechos', 'Rótulos de nós'
L_FIT, L_CALL, L_TABLE = 'Conexões', 'Chamadas de conexões', 'Quadro de conexões'


@dataclass
class CalcOptions:
    text_height: float = 2.0
    link_fields: list = field(default_factory=lambda: ['name', 'dn', 'length', 'flow',
                                                       'velocity', 'unit_headloss'])
    node_fields: list = field(default_factory=lambda: ['name', 'elevation', 'pressure'])
    arrows: bool = True
    include_cad: bool = True
    time_index: int = 0


@dataclass
class ExecOptions:
    text_height: float = 2.0
    include_cad: bool = True
    pipe_labels: bool = True
    callouts: bool = True
    callout_style: str = 'mleader'        # 'mleader' | 'leader' | 'linhas'
    table: bool = True
    library: str = ''
    fittings: F.FittingOptions = field(default_factory=F.FittingOptions)


def num(v, nd=2) -> str:
    """Número com vírgula decimal (padrão brasileiro de desenho)."""
    return f'{v:.{nd}f}'.replace('.', ',')


def _readable(angle: float) -> float:
    a = angle % 360.0
    return a - 180.0 if 90.0 < a <= 270.0 else a


def _layer(doc, name, color=7, rgb=None):
    if name not in doc.layers:
        lay = doc.layers.add(name, color=color)
        if rgb:
            lay.rgb = rgb
    return name


def _mtext(msp, text, at, h, layer, attach, rotation=0.0):
    m = msp.add_mtext(text, dxfattribs={'layer': layer, 'char_height': h,
                                        'rotation': rotation})
    m.set_location(at, attachment_point=attach)
    return m


def _label_point(pts):
    """Ponto médio e ângulo do maior segmento (onde o rótulo cabe melhor)."""
    i = max(range(len(pts) - 1), key=lambda k: math.dist(pts[k], pts[k + 1]))
    a, b = pts[i], pts[i + 1]
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), math.degrees(math.atan2(b[1] - a[1],
                                                                            b[0] - a[0]))


# =========================================================================== planta de cálculo
def link_texts(project, link, sim, t, fields) -> tuple[str, str]:
    """(linha de identificação, linha de resultados) de um trecho."""
    net = project.network
    top, bottom = [], []
    d = (sim or {}).get('links', {}).get(link.uid, {})
    is_pipe = link.KIND == 'pipe'
    for f in fields:
        if f == 'name':
            top.append(link.name)
        elif f == 'dn' and hasattr(link, 'diameter'):
            top.append(f'DN{F.nominal_dn(link.diameter, project)}')
        elif f == 'length' and is_pipe:
            top.append(f'L={num(net.hydraulic_length(link))} m')
        elif f == 'material' and is_pipe:
            top.append((link.material or '').upper())
        elif f == 'roughness' and is_pipe:
            top.append(f'C={num(link.roughness, 0)}')
        elif f in RESULT_LINK and d:
            key = {'friction': 'friction_factor'}.get(f, f)
            v = TV.value_at(d.get(key), t)
            if v is None:
                continue
            if f == 'flow':
                bottom.append(f'Q={num(v)} L/s')
            elif f == 'velocity':
                bottom.append(f'V={num(abs(v))} m/s')
            elif f == 'unit_headloss':
                bottom.append(f'J={num(v)} m/km')
            elif f == 'headloss':
                bottom.append(f'hf={num(v, 3)} m')
            elif f == 'friction':
                bottom.append(f'f={num(v, 4)}')
            elif f == 'status':
                bottom.append(TV.STATUS_LABELS.get(int(round(v)), '').upper())
    return ' - '.join(top), ' - '.join(bottom)


def node_lines(project, node, sim, t, fields) -> list[str]:
    d = (sim or {}).get('nodes', {}).get(node.uid, {})
    out = []
    for f in fields:
        if f == 'name':
            out.append(node.name)
        elif f == 'elevation':
            z = getattr(node, 'elevation', None)
            if node.KIND == 'reservoir':
                out.append(f'NA={num(node.head)} m')
            elif z is not None:
                out.append(f'CT={num(z)} m')
        elif f in RESULT_NODE and d:
            v = TV.value_at(d.get(f), t)
            if v is None:
                continue
            if f == 'demand' and node.KIND == 'junction':
                out.append(f'Qd={num(v, 3)} L/s')
            elif f == 'pressure' and node.KIND == 'junction':
                out.append(f'P={num(v)} mca')
            elif f == 'pressure' and node.KIND == 'tank':
                out.append(f'N={num(v)} m')
            elif f == 'head':
                out.append(f'CP={num(v)} m')
    return out


def export_calc_plan(project, path, opts: CalcOptions, sim=None):
    h = opts.text_height
    signs = TV.flow_signs(sim, opts.time_index) if (sim and opts.arrows) else None
    doc = build_network_doc(project, symbol_size=h, include_cad=opts.include_cad,
                            include_labels=False, flow_signs=signs)
    msp = doc.modelspace()
    _layer(doc, L_LINK, 4)
    _layer(doc, L_NODE, 3)
    net = project.network
    for l in net.links.values():
        if not project.layer_visible(l.layer):
            continue
        pts = net.link_points(l)
        if len(pts) < 2:
            continue
        top, bottom = link_texts(project, l, sim, opts.time_index, opts.link_fields)
        (mx, my), ang = _label_point(pts)
        rot = _readable(ang)
        nx, ny = F.unit(rot + 90.0)
        if top:
            _mtext(msp, top, (mx + nx * 0.4 * h, my + ny * 0.4 * h), h * 0.8, L_LINK, 8, rot)
        if bottom:
            _mtext(msp, bottom, (mx - nx * 0.4 * h, my - ny * 0.4 * h), h * 0.8, L_LINK, 2, rot)
    for n in net.nodes.values():
        if not project.layer_visible(n.layer):
            continue
        lines = node_lines(project, n, sim, opts.time_index, opts.node_fields)
        if lines:
            _mtext(msp, '\\P'.join(lines), (n.x + h * 0.9, n.y + h * 0.9), h * 0.8, L_NODE, 7)
    if sim:
        times = sim.get('times', [0])
        ti = min(opts.time_index, len(times) - 1)
        b = project.bounds()
        if b:
            _mtext(msp, f'PLANTA DE CÁLCULO - resultados do instante {num(times[ti] / 3600)} h',
                   (b[0], b[1] - 4 * h), h * 1.2, L_NODE, 1)
    doc.saveas(path)
    return path


# =========================================================================== planta de execução
def export_exec_plan(project, path, opts: ExecOptions, points=None):
    """Exporta a planta de execução. `points` = análise já feita (fittings.analyze_network)."""
    h = opts.text_height
    if points is None:
        points = F.analyze_network(project, opts.fittings, scale=h)
    doc = build_network_doc(project, symbol_size=h, include_cad=opts.include_cad,
                            include_labels=False, junction_symbols=False)
    msp = doc.modelspace()
    import_blocks(doc, opts.library)
    _layer(doc, L_FIT, 1)
    _layer(doc, L_CALL, 2)
    _layer(doc, L_TABLE, 7)
    _layer(doc, L_LINK, 4)
    net = project.network
    if opts.pipe_labels:
        for l in net.links.values():
            if l.KIND != 'pipe' or not project.layer_visible(l.layer):
                continue
            pts = net.link_points(l)
            if len(pts) < 2:
                continue
            (mx, my), ang = _label_point(pts)
            rot = _readable(ang)
            nx, ny = F.unit(rot + 90.0)
            txt = (f'{l.name} - {(l.material or "PVC").upper()} '
                   f'DN{F.nominal_dn(l.diameter, project)} - L={num(net.hydraulic_length(l))} m'
                   + (' (EXISTENTE)' if l.existing else ''))
            _mtext(msp, txt, (mx + nx * 0.4 * h, my + ny * 0.4 * h), h * 0.8, L_LINK, 8, rot)
    for fp in points:
        for pc in fp.pieces:
            msp.add_blockref(pc.block, (pc.x, pc.y), dxfattribs={
                'layer': L_FIT, 'rotation': pc.rotation, 'xscale': h,
                'yscale': -h if pc.mirror else h, 'zscale': h})
        if opts.callouts and (fp.pieces or fp.warnings):
            _callout(msp, fp, h, opts.callout_style)
    if opts.table:
        _quantity_table(msp, project, points, h)
    doc.saveas(path)
    return path, points


def callout_lines(fp) -> list[str]:
    counts: dict[str, int] = {}
    for pc in fp.pieces:
        counts[pc.label] = counts.get(pc.label, 0) + 1
    lines = [f'{n} {lab}' for lab, n in counts.items()]
    if not lines:
        lines = ['VERIFICAR']
    return lines


CALLOUT_STYLES = {
    'mleader': 'Multileader (MLEADER) — texto e linha num único objeto',
    'leader': 'Leader + MText (LEADER clássico associado ao texto)',
    'linhas': 'Polilinha + MText (objetos independentes)',
}


def callout_text(fp) -> str:
    title = fp.name + (' (vértice)' if fp.kind == 'vertex' and 'vértice' not in fp.name else '')
    text = f'{title}\\P' + '\\P'.join(callout_lines(fp))
    if fp.short:
        text += '\\P' + '\\P'.join('* ' + w for w in fp.short)
    return text


def _callout(msp, fp, h, style='mleader'):
    """Linha de chamada do ponto (junção/vértice) até o texto com as peças."""
    ang = F.callout_direction(fp.directions)
    ux, uy = F.unit(ang)
    p0 = (fp.x + ux * h * 0.9, fp.y + uy * h * 0.9)       # ponta da seta
    p1 = (fp.x + ux * h * 7.0, fp.y + uy * h * 7.0)       # cotovelo
    side = 1.0 if ux >= 0 else -1.0
    p2 = (p1[0] + side * h * 2.0, p1[1])                  # fim do patamar
    text = callout_text(fp)
    th = h * 0.7
    if style == 'mleader':
        from ezdxf.math import Vec2
        from ezdxf.render import mleader
        ml = msp.add_multileader_mtext('Standard', dxfattribs={'layer': L_CALL})
        ml.set_content(text, char_height=th,
                       alignment=mleader.TextAlignment.left if side > 0 else
                       mleader.TextAlignment.right)
        ml.set_arrow_properties(size=h * 0.45)
        ml.set_connection_properties(landing_gap=h * 0.3, dogleg_length=h * 2.0)
        ml.add_leader_line(mleader.ConnectionSide.left if side > 0 else
                           mleader.ConnectionSide.right, [Vec2(p0), Vec2(p1)])
        ml.build(insert=Vec2(p2[0] + side * h * 0.3, p2[1] + th * 0.5))
        return
    if style == 'leader':
        mt = _mtext(msp, text, (p2[0] + side * h * 0.4, p2[1]), th, L_CALL,
                    4 if side > 0 else 6)
        ld = msp.add_leader([p0, p1, p2], dimstyle='EZDXF',
                            override={'dimasz': h * 0.45, 'dimgap': h * 0.3},
                            dxfattribs={'layer': L_CALL})
        ld.dxf.annotation_type = 0                       # anotação = MTEXT
        ld.dxf.annotation_handle = mt.dxf.handle
        ld.dxf.has_hookline = 1
        ld.dxf.hookline_direction = 0 if side > 0 else 1
        ld.dxf.text_height = th
        return
    msp.add_lwpolyline([p0, p1, p2], dxfattribs={'layer': L_CALL})
    msp.add_circle(p0, h * 0.18, dxfattribs={'layer': L_CALL})
    _mtext(msp, text, (p2[0] + side * h * 0.4, p2[1]), th, L_CALL, 4 if side > 0 else 6)


def _quantity_table(msp, project, points, h):
    q = F.quantities(points)
    b = project.bounds()
    if not b:
        return
    x, y = b[2] + 15 * h, b[3]
    lines = ['RELAÇÃO DE CONEXÕES', ''] + [f'{n:>4}  {lab}' for lab, n in q.items()]
    n_warn = sum(1 for fp in points if fp.warnings)
    if n_warn:
        lines += ['', f'{n_warn} ponto(s) com observações: ver chamadas marcadas com *']
    _mtext(msp, '\\P'.join(lines), (x, y), h, L_TABLE, 7)


def summary_rows(points) -> list[tuple[str, str, str]]:
    """Linhas para a revisão na interface: (local, peças, avisos)."""
    out = []
    for fp in points:
        if not fp.pieces and not fp.warnings:
            continue
        out.append((fp.name, '; '.join(callout_lines(fp)) if fp.pieces else '—',
                    ' '.join(fp.warnings)))
    return out

