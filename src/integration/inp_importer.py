"""Importa um arquivo EPANET .inp para o modelo do projeto (leitura via WNTR,
a mesma biblioteca usada por main4.py)."""

from __future__ import annotations

import re

from ..hydraulics.models import (Junction, Reservoir, Tank, Pipe, Pump, Valve, Curve,
                                 Pattern, Control)
from ..hydraulics.network import Network
from ..hydraulics.project import Project

_CTRL = re.compile(
    r'^\s*LINK\s+(\S+)\s+(\S+)\s+(?:(IF\s+NODE)\s+(\S+)\s+(ABOVE|BELOW)\s+(\S+)'
    r'|AT\s+(TIME|CLOCKTIME)\s+(.+?))\s*$', re.IGNORECASE)


def _raw_section(path: str, section: str) -> list[str]:
    lines, inside = [], False
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for raw in f:
            s = raw.split(';', 1)[0].strip()
            if s.startswith('['):
                inside = s.upper() == section
                continue
            if inside and s:
                lines.append(s)
    return lines


def _raw_controls(path: str) -> list[str]:
    return _raw_section(path, '[CONTROLS]')


def _raw_section_has_content(path: str, section: str) -> bool:
    return bool(_raw_section(path, section))


# vazão nas unidades do arquivo -> L/s
FLOW_TO_LPS = {'LPS': 1.0, 'LPM': 1.0 / 60.0, 'MLD': 1e6 / 86400.0, 'CMH': 1000.0 / 3600.0,
               'CMD': 1000.0 / 86400.0, 'CFS': 28.316846592, 'GPM': 0.0630901964,
               'MGD': 43.812636, 'IMGD': 52.616782, 'AFD': 14.276410}
US_UNITS = {'CFS', 'GPM', 'MGD', 'IMGD', 'AFD'}
CURVE_KINDS = ('PUMP', 'EFFICIENCY', 'VOLUME', 'HEADLOSS')


def _curve_comment_types(path: str) -> dict:
    """Tipo de cada curva pelo comentário que o EPANET grava antes dela (';PUMP: ...')."""
    types, current, inside = {}, None, False
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for raw in f:
            s = raw.strip()
            if s.startswith('['):
                inside = s.upper() == '[CURVES]'
                continue
            if not inside or not s:
                continue
            if s.startswith(';'):
                head = s[1:].split(':', 1)[0].strip().upper()
                if head in CURVE_KINDS:
                    current = head
                continue
            cid = s.split(';', 1)[0].split()[0]
            if current and cid not in types:
                types[cid] = current
                current = None           # o comentário vale só para a curva seguinte
    return types


def _curve_points(c, comment_type, units, warnings):
    """(tipo, pontos) no padrão do programa: vazão L/s, carga/perda/altura m, volume m³.

    Curvas usadas pela rede vêm do WNTR em SI (vazão em m³/s; o WNTR chama a curva de
    bomba de 'HEAD'). Curvas sem uso vêm nas unidades do arquivo (sem conversão).
    """
    wtype = str(c.curve_type).upper() if c.curve_type else ''
    if wtype:
        kind = 'PUMP' if wtype == 'HEAD' else wtype
        pts = []
        for x, y in c.points:
            if kind in ('PUMP', 'HEADLOSS', 'EFFICIENCY'):
                x = x * 1000.0                         # m³/s -> L/s
            pts.append([float(x), float(y)])
        return (kind if kind in CURVE_KINDS else 'PUMP'), pts
    kind = comment_type or 'PUMP'
    if not comment_type:
        warnings.append(f"Curva '{c.name}' sem uso e sem tipo no arquivo: assumida como curva "
                        'de bomba.')
    q = FLOW_TO_LPS.get(units, 1.0)
    L = 0.3048 if units in US_UNITS else 1.0
    pts = []
    for x, y in c.points:
        if kind == 'PUMP':
            x, y = x * q, y * L
        elif kind == 'EFFICIENCY':
            x = x * q
        elif kind == 'HEADLOSS':
            x, y = x * q, y * L
        elif kind == 'VOLUME':
            x, y = x * L, y * L ** 3
        pts.append([float(x), float(y)])
    return kind, pts


def _status(link) -> str:
    st = str(getattr(link, 'initial_status', 'Open'))
    st = st.split('.')[-1].capitalize()
    return 'Closed' if st == 'Closed' else 'Open'


def import_inp(path: str, project: Project | None = None) -> tuple[Network, list[str]]:
    """Lê o .inp e devolve (rede, avisos). Se `project` for dado, atualiza opções de tempo."""
    import wntr  # import tardio (pesado)

    wn = wntr.network.WaterNetworkModel(path)
    net = Network()
    warnings: list[str] = []
    uid_of: dict[str, str] = {}

    for name, pat in wn.patterns():
        p = Pattern(name=name, multipliers=[float(m) for m in pat.multipliers])
        net.put(p)
        uid_of['pat:' + name] = p.uid

    units = str(wn.options.hydraulic.inpfile_units).upper()
    comment_types = _curve_comment_types(path)
    for name, c in wn.curves():
        ctype, pts = _curve_points(c, comment_types.get(name), units, warnings)
        cv = Curve(name=name, curve_type=ctype, points=pts)
        net.put(cv)
        uid_of['curve:' + name] = cv.uid

    def pat_uid(n):
        return uid_of.get('pat:' + n, '') if n else ''

    def curve_uid(n):
        return uid_of.get('curve:' + n, '') if n else ''

    for name, j in wn.junctions():
        x, y = j.coordinates
        dl = list(j.demand_timeseries_list)
        base = dl[0].base_value * 1000.0 if dl else 0.0
        pat = dl[0].pattern_name if dl else ''
        cats = [{'base': d.base_value * 1000.0, 'pattern': pat_uid(d.pattern_name),
                 'name': d.category or ''} for d in dl[1:]]
        node = Junction(name=name, x=float(x), y=float(y), elevation=float(j.elevation),
                        base_demand=base, demand_pattern=pat_uid(pat), demand_categories=cats,
                        emitter_coeff=float(j.emitter_coefficient or 0.0) * 1000.0)
        net.put(node)
        uid_of['node:' + name] = node.uid

    for name, r in wn.reservoirs():
        x, y = r.coordinates
        node = Reservoir(name=name, x=float(x), y=float(y), head=float(r.base_head),
                         head_pattern=pat_uid(r.head_pattern_name))
        net.put(node)
        uid_of['node:' + name] = node.uid

    for name, t in wn.tanks():
        x, y = t.coordinates
        node = Tank(name=name, x=float(x), y=float(y), elevation=float(t.elevation),
                    init_level=float(t.init_level), min_level=float(t.min_level),
                    max_level=float(t.max_level), diameter=float(t.diameter),
                    min_volume=float(t.min_vol or 0.0), volume_curve=curve_uid(t.vol_curve_name),
                    overflow=bool(getattr(t, 'overflow', False)))
        net.put(node)
        uid_of['node:' + name] = node.uid

    headloss = str(wn.options.hydraulic.headloss).upper()

    def _roughness(v):
        # D-W: o WNTR devolve em metros; o programa (como o EPANET em LPS) usa milímetros.
        # H-W e C-M são adimensionais.
        return float(v) * 1000.0 if headloss == 'D-W' else float(v)

    def ends(link):
        return uid_of['node:' + link.start_node_name], uid_of['node:' + link.end_node_name]

    for name, p in wn.pipes():
        a, b = ends(p)
        status = 'CV' if p.check_valve else _status(p)
        pipe = Pipe(name=name, start=a, end=b, vertices=[list(v) for v in p.vertices],
                    length=float(p.length), auto_length=False, diameter=float(p.diameter) * 1000.0,
                    roughness=_roughness(p.roughness), minor_loss=float(p.minor_loss),
                    status=status)
        net.put(pipe)
        uid_of['link:' + name] = pipe.uid

    for name, p in wn.pumps():
        a, b = ends(p)
        kw = dict(name=name, start=a, end=b, vertices=[list(v) for v in p.vertices],
                  speed=float(p.base_speed or 1.0), pattern=pat_uid(p.speed_pattern_name),
                  status=_status(p))
        if p.pump_type == 'POWER':
            kw['power'] = float(p.power) / 1000.0
        else:
            kw['curve'] = curve_uid(p.pump_curve_name)
        pump = Pump(**kw)
        net.put(pump)
        uid_of['link:' + name] = pump.uid

    for name, v in wn.valves():
        a, b = ends(v)
        vt = str(v.valve_type).upper()
        st = str(v.initial_status).split('.')[-1].capitalize()
        valve = Valve(name=name, start=a, end=b, vertices=[list(x) for x in v.vertices],
                      valve_type=vt, diameter=float(v.diameter) * 1000.0,
                      minor_loss=float(v.minor_loss),
                      status=st if st in ('Open', 'Closed') else 'None')
        if vt == 'GPV':
            valve.headloss_curve = curve_uid(getattr(v, 'headloss_curve_name', ''))
        else:
            s = float(v.initial_setting or 0.0)
            valve.setting = s * 1000.0 if vt == 'FCV' else s
        net.put(valve)
        uid_of['link:' + name] = valve.uid

    # controles simples, lidos do texto original para preservar a forma
    for k, line in enumerate(_raw_controls(path), 1):
        m = _CTRL.match(line)
        if not m or ('link:' + m.group(1)) not in uid_of:
            warnings.append(f'Controle não importado: {line}')
            continue
        c = Control(name=f'CTRL{k}', link=uid_of['link:' + m.group(1)], action=m.group(2).upper())
        if m.group(3):
            c.condition = 'IF NODE ' + m.group(5).upper()
            c.node = uid_of.get('node:' + m.group(4), '')
            c.value = m.group(6)
        else:
            c.condition = 'AT ' + m.group(7).upper()
            c.value = m.group(8).strip()
        net.put(c)

    if _raw_section_has_content(path, '[RULES]'):
        warnings.append('Regras ([RULES]) não são suportadas e foram ignoradas.')

    if project is not None:
        o = project.sim_options
        t = wn.options.time
        o.duration_h = t.duration / 3600.0
        o.hydraulic_step_h = t.hydraulic_timestep / 3600.0
        o.pattern_step_h = t.pattern_timestep / 3600.0
        o.report_step_h = t.report_timestep / 3600.0
        o.start_clocktime_h = t.start_clocktime / 3600.0
        h = wn.options.hydraulic
        o.headloss = h.headloss
        o.trials = int(h.trials)
        o.accuracy = float(h.accuracy)
        o.demand_multiplier = float(h.demand_multiplier)
        if h.pattern and ('pat:' + str(h.pattern)) in uid_of:
            o.default_pattern = uid_of['pat:' + str(h.pattern)]
        if str(h.inpfile_units).upper() != 'LPS':
            warnings.append(f'Unidades de vazão originais: {h.inpfile_units}. '
                            'Os valores foram convertidos para L/s, m e mm.')
    return net, warnings
