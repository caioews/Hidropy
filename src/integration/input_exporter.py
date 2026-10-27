"""Exporta o modelo hidráulico para um arquivo EPANET .inp (o formato que main4.py lê).

Unidades: FLOW UNITS = LPS  =>  comprimentos/cotas em m, diâmetros em mm, vazões em L/s.

Devolve também o mapa de nomes (nome no .inp -> uid), usado para associar os
resultados devolvidos pelo motor aos elementos corretos.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from ..hydraulics.models import Junction, Reservoir, Tank, Pipe, Pump, Valve
from ..hydraulics.project import Project
from ..hydraulics.network import Network

_BAD = re.compile(r'[\s;"]+')


@dataclass
class ExportResult:
    text: str
    sha256: str
    name_map: dict = field(default_factory=dict)   # {'nodes': {nome: uid}, 'links': {...}}
    names: dict = field(default_factory=dict)      # uid -> nome no .inp


def _hours(h: float) -> str:
    total_min = int(round(float(h) * 60))
    return f'{total_min // 60}:{total_min % 60:02d}'


def _num(v, nd=6) -> str:
    if v is None:
        return '0'
    s = f'{float(v):.{nd}f}'.rstrip('0').rstrip('.')
    return s if s not in ('', '-0') else '0'


def _assign_names(net: Network) -> dict[str, str]:
    """uid -> nome válido e único no .inp (por categoria do EPANET)."""
    names: dict[str, str] = {}
    groups = {'node': list(net.nodes.values()), 'link': list(net.links.values()),
              'curve': list(net.curves.values()), 'pattern': list(net.patterns.values())}
    for elems in groups.values():
        used: set[str] = set()
        for e in elems:
            base = _BAD.sub('_', e.name.strip()) or e.uid
            base = base[:31]
            name = base
            k = 2
            while name in used:
                suf = f'_{k}'
                name = base[:31 - len(suf)] + suf
                k += 1
            used.add(name)
            names[e.uid] = name
    return names


def export_inp(project: Project, title: str = '') -> ExportResult:
    net = project.network
    opt = project.sim_options
    names = _assign_names(net)
    N = names.get
    out: list[str] = []
    w = out.append

    w('[TITLE]')
    w(' '.join((title or project.meta.get('title', 'SHCAD')).split())[:79])
    w('')

    junctions = [n for n in net.nodes.values() if isinstance(n, Junction)]
    reservoirs = [n for n in net.nodes.values() if isinstance(n, Reservoir)]
    tanks = [n for n in net.nodes.values() if isinstance(n, Tank)]
    pipes = [l for l in net.links.values() if isinstance(l, Pipe)]
    pumps = [l for l in net.links.values() if isinstance(l, Pump)]
    valves = [l for l in net.links.values() if isinstance(l, Valve)]

    w('[JUNCTIONS]')
    w(';ID\tElev\tDemand\tPattern')
    for j in junctions:
        pat = N(j.demand_pattern, '') if j.demand_pattern else ''
        w(f'{N(j.uid)}\t{_num(j.elevation)}\t{_num(j.base_demand)}\t{pat}\t;')
    w('')

    w('[RESERVOIRS]')
    w(';ID\tHead\tPattern')
    for r in reservoirs:
        pat = N(r.head_pattern, '') if r.head_pattern else ''
        w(f'{N(r.uid)}\t{_num(r.head)}\t{pat}\t;')
    w('')

    w('[TANKS]')
    w(';ID\tElevation\tInitLevel\tMinLevel\tMaxLevel\tDiameter\tMinVol\tVolCurve\tOverflow')
    for t in tanks:
        curve = N(t.volume_curve, '') if t.volume_curve else ''
        line = (f'{N(t.uid)}\t{_num(t.elevation)}\t{_num(t.init_level)}\t{_num(t.min_level)}\t'
                f'{_num(t.max_level)}\t{_num(t.diameter)}\t{_num(t.min_volume)}')
        if curve or t.overflow:
            line += f'\t{curve or "*"}'
        if t.overflow:
            line += '\tYES'
        w(line + '\t;')
    w('')

    w('[PIPES]')
    w(';ID\tNode1\tNode2\tLength\tDiameter\tRoughness\tMinorLoss\tStatus')
    for p in pipes:
        L = net.hydraulic_length(p)
        w(f'{N(p.uid)}\t{N(p.start)}\t{N(p.end)}\t{_num(L, 4)}\t{_num(p.diameter, 4)}\t'
          f'{_num(p.roughness, 4)}\t{_num(p.minor_loss, 4)}\t{p.status}\t;')
    w('')

    w('[PUMPS]')
    w(';ID\tNode1\tNode2\tParameters')
    for p in pumps:
        params = []
        if p.curve:
            params.append(f'HEAD {N(p.curve)}')
        elif p.power:
            params.append(f'POWER {_num(p.power)}')
        if p.speed is not None and abs(p.speed - 1.0) > 1e-12:
            params.append(f'SPEED {_num(p.speed)}')
        if p.pattern:
            params.append(f'PATTERN {N(p.pattern)}')
        w(f'{N(p.uid)}\t{N(p.start)}\t{N(p.end)}\t{" ".join(params)}\t;')
    w('')

    w('[VALVES]')
    w(';ID\tNode1\tNode2\tDiameter\tType\tSetting\tMinorLoss')
    for v in valves:
        setting = N(v.headloss_curve, '') if v.valve_type == 'GPV' else _num(v.setting)
        w(f'{N(v.uid)}\t{N(v.start)}\t{N(v.end)}\t{_num(v.diameter, 4)}\t{v.valve_type}\t'
          f'{setting}\t{_num(v.minor_loss)}\t;')
    w('')

    w('[DEMANDS]')
    w(';Junction\tDemand\tPattern\tCategory')
    for j in junctions:
        if j.demand_categories:
            # o EPANET substitui a demanda de [JUNCTIONS] pelas de [DEMANDS]
            pat = N(j.demand_pattern, '') if j.demand_pattern else ''
            w(f'{N(j.uid)}\t{_num(j.base_demand)}\t{pat}\t;principal')
            for cat in j.demand_categories:
                cpat = N(cat.get('pattern'), '') if cat.get('pattern') else ''
                w(f"{N(j.uid)}\t{_num(cat.get('base', 0))}\t{cpat}\t;{cat.get('name', '')}")
    w('')

    w('[STATUS]')
    w(';ID\tStatus/Setting')
    for p in pumps:
        if p.status == 'Closed':
            w(f'{N(p.uid)}\tClosed')
    for v in valves:
        if v.status in ('Open', 'Closed'):
            w(f'{N(v.uid)}\t{v.status}')
    w('')

    w('[EMITTERS]')
    w(';Junction\tCoefficient')
    for j in junctions:
        if j.emitter_coeff:
            w(f'{N(j.uid)}\t{_num(j.emitter_coeff)}')
    w('')

    w('[PATTERNS]')
    w(';ID\tMultipliers')
    for p in net.patterns.values():
        mult = [_num(m) for m in (p.multipliers or [1.0])]
        for i in range(0, len(mult), 6):
            w(f'{N(p.uid)}\t' + '\t'.join(mult[i:i + 6]))
    w('')

    w('[CURVES]')
    w(';ID\tX-Value\tY-Value')
    for c in net.curves.values():
        w(f';{c.curve_type}: {c.name}')
        for x, y in c.points:
            w(f'{N(c.uid)}\t{_num(x)}\t{_num(y)}')
    w('')

    w('[CONTROLS]')
    for c in net.controls.values():
        if c.link not in net.links:
            continue
        action = c.action.upper() if c.action.upper() in ('OPEN', 'CLOSED') else c.action
        if c.condition in ('IF NODE ABOVE', 'IF NODE BELOW'):
            cond = 'ABOVE' if c.condition.endswith('ABOVE') else 'BELOW'
            w(f'LINK {N(c.link)} {action} IF NODE {N(c.node)} {cond} {c.value}')
        else:
            w(f'LINK {N(c.link)} {action} {c.condition} {c.value}')
    w('')

    w('[TIMES]')
    w(f'Duration\t{_hours(opt.duration_h)}')
    w(f'Hydraulic Timestep\t{_hours(opt.hydraulic_step_h)}')
    w(f'Pattern Timestep\t{_hours(opt.pattern_step_h)}')
    w(f'Report Timestep\t{_hours(opt.report_step_h)}')
    w(f'Start ClockTime\t{_hours(opt.start_clocktime_h)}')
    w('')

    w('[OPTIONS]')
    w('Units\tLPS')
    w(f'Headloss\t{opt.headloss}')
    w(f'Trials\t{int(opt.trials)}')
    w(f'Accuracy\t{_num(opt.accuracy, 8)}')
    w(f'Demand Multiplier\t{_num(opt.demand_multiplier)}')
    w(f'Viscosity\t{_num(opt.viscosity)}')
    w(f'Specific Gravity\t{_num(opt.specific_gravity)}')
    if opt.default_pattern and opt.default_pattern in net.patterns:
        w(f'Pattern\t{N(opt.default_pattern)}')
    w('')

    w('[REPORT]')
    w('Status\tNo')
    w('Summary\tNo')
    w('')

    w('[COORDINATES]')
    w(';Node\tX-Coord\tY-Coord')
    for n in net.nodes.values():
        w(f'{N(n.uid)}\t{_num(n.x, 4)}\t{_num(n.y, 4)}')
    w('')

    w('[VERTICES]')
    w(';Link\tX-Coord\tY-Coord')
    for l in net.links.values():
        for v in l.vertices:
            w(f'{N(l.uid)}\t{_num(v[0], 4)}\t{_num(v[1], 4)}')
    w('')
    w('[END]')

    text = '\n'.join(out) + '\n'
    # o hash ignora o título: identifica apenas o conteúdo hidráulico
    body = '\n'.join(out[3:])
    name_map = {
        'nodes': {names[u]: u for u in net.nodes},
        'links': {names[u]: u for u in net.links},
    }
    return ExportResult(text=text, sha256=hashlib.sha256(body.encode('utf-8')).hexdigest(),
                        name_map=name_map, names=names)


def network_hash(project: Project) -> str:
    return export_inp(project).sha256


def write_inp(project: Project, path: str, title: str = '') -> ExportResult:
    res = export_inp(project, title)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(res.text)
    return res
