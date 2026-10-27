"""Mapas temáticos: extrai valores CALCULADOS dos resultados e os classifica em cores.

Nenhum valor é inventado: se o resultado não contém a variável, o elemento fica
sem cor temática (cinza) e a legenda informa a ausência de dados.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

RAMP = ['#2c7bb6', '#00a6ca', '#00ccbc', '#90eb9d', '#f9d057', '#f29e2e', '#d7191c']

NODE_VARS = {
    '': 'Nenhum',
    'pressure': 'Pressão (m)',
    'head': 'Carga hidráulica (m)',
    'demand': 'Demanda (L/s)',
    'level': 'Nível do tanque (m)',
    'elevation': 'Cota (m) [dado de entrada]',
    'opt_p_min': 'Otimização: pressão mínima (m)',
}
LINK_VARS = {
    '': 'Nenhum',
    'flow': 'Vazão (L/s)',
    'velocity': 'Velocidade (m/s)',
    'unit_headloss': 'Perda de carga unitária (m/km)',
    'headloss': 'Perda de carga (m)',
    'status': 'Estado',
    'diameter': 'Diâmetro cadastrado (mm)',
    'opt_diameter': 'Otimização: diâmetro otimizado (mm)',
    'diam_change': 'Otimização: alteração de diâmetro',
    'existing': 'Situação: existente × projetado',
    'opt_v_max': 'Otimização: velocidade máxima (m/s)',
}
UNITS = {'pressure': 'm', 'head': 'm', 'demand': 'L/s', 'level': 'm', 'elevation': 'm',
         'opt_p_min': 'm', 'flow': 'L/s', 'velocity': 'm/s', 'unit_headloss': 'm/km',
         'headloss': 'm', 'diameter': 'mm', 'opt_diameter': 'mm', 'opt_v_max': 'm/s'}
SIM_NODE = {'pressure', 'head', 'demand', 'level'}
SIM_LINK = {'flow', 'velocity', 'unit_headloss', 'headloss', 'status'}
OPT_VARS = {'opt_p_min', 'opt_diameter', 'diam_change', 'opt_v_max'}
CHANGE_COLORS = {-1: '#2c7bb6', 0: '#9a9a9a', 1: '#d7191c'}
CHANGE_LABELS = {-1: 'Diâmetro reduzido', 0: 'Sem alteração', 1: 'Diâmetro aumentado'}
STATUS_COLORS = {0: '#d7191c', 1: '#1a9641', 2: '#f29e2e'}
STATUS_LABELS = {0: 'Fechado', 1: 'Aberto', 2: 'Ativo'}
EXISTING_COLORS = {1: '#5a5a5a', 0: '#2a6fdb'}
EXISTING_LABELS = {1: 'Existente (executado) — diâmetro mantido', 0: 'Projetado'}


@dataclass
class ThemeConfig:
    node_var: str = ''
    link_var: str = ''
    time_index: int = 0
    node_breaks: list | None = None    # None = automático (intervalos iguais)
    link_breaks: list | None = None
    highlight_limits: bool = True
    classes: int = 5


@dataclass
class Legend:
    title: str
    entries: list = field(default_factory=list)   # [(cor, texto)]
    note: str = ''


def value_at(series, t):
    if not series:
        return None
    if t >= len(series):
        t = len(series) - 1
    v = series[t]
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else v


def node_values(project, var, sim, opt, t) -> dict:
    net = project.network
    if var == 'elevation':
        return {u: getattr(n, 'elevation', getattr(n, 'head', None))
                for u, n in net.nodes.items()}
    if var in SIM_NODE:
        if not sim:
            return {}
        out = {}
        for u, d in sim.get('nodes', {}).items():
            n = net.nodes.get(u)
            # pressão em reservatório/tanque não é atendimento (EPANET reporta 0 / nível)
            if var == 'pressure' and n is not None and n.KIND != 'junction':
                continue
            v = value_at(d.get(var), t)
            if v is not None:
                out[u] = v
        return out
    if var == 'opt_p_min':
        if not opt:
            return {}
        return {u: d['p_min'] for u, d in opt.get('junctions', {}).items()
                if d.get('p_min') is not None}
    return {}


def link_values(project, var, sim, opt, t) -> dict:
    net = project.network
    if var == 'diameter':
        return {u: l.diameter for u, l in net.links.items() if hasattr(l, 'diameter')}
    if var == 'existing':
        return {u: int(l.existing) for u, l in net.links.items() if l.KIND == 'pipe'}
    if var in SIM_LINK:
        if not sim:
            return {}
        out = {}
        for u, d in sim.get('links', {}).items():
            v = value_at(d.get(var), t)
            if v is not None:
                out[u] = abs(v) if var in ('flow', 'velocity', 'unit_headloss') else v
        return out
    if not opt:
        return {}
    pipes = opt.get('pipes', {})
    if var == 'opt_diameter':
        return {u: d['opt_diam_mm'] for u, d in pipes.items()}
    if var == 'opt_v_max':
        return {u: d['v_max'] for u, d in pipes.items() if d.get('v_max') is not None}
    if var == 'diam_change':
        out = {}
        for u, d in pipes.items():
            delta = d['opt_diam_mm'] - d['orig_diam_mm']
            out[u] = 0 if abs(delta) < 1e-6 else (1 if delta > 0 else -1)
        return out
    return {}


def flow_signs(sim, t) -> dict:
    if not sim:
        return {}
    out = {}
    for u, d in sim.get('links', {}).items():
        v = value_at(d.get('flow'), t)
        if v is not None:
            out[u] = 0 if abs(v) < 1e-9 else (1 if v > 0 else -1)
    return out


def auto_breaks(values, classes=5) -> list:
    vals = [v for v in values if v is not None]
    if not vals:
        return []
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-12:
        return [lo]
    return [lo + (hi - lo) * k / classes for k in range(1, classes)]


def _ramp(n):
    if n <= 1:
        return [RAMP[0]]
    return [RAMP[round(k * (len(RAMP) - 1) / (n - 1))] for k in range(n)]


def classify(v, breaks) -> int:
    for i, b in enumerate(breaks):
        if v < b:
            return i
    return len(breaks)


class ColorScale:
    def __init__(self, var: str, values: dict, breaks: list | None, classes: int = 5):
        self.var = var
        self.values = values
        self.categorical = var in ('diam_change', 'status', 'existing')
        if self.categorical:
            self.breaks = []
            self.colors = []
        else:
            self.breaks = list(breaks) if breaks else auto_breaks(values.values(), classes)
            self.colors = _ramp(len(self.breaks) + 1)

    def color(self, uid) -> str | None:
        v = self.values.get(uid)
        if v is None:
            return None
        if self.var == 'diam_change':
            return CHANGE_COLORS.get(int(v))
        if self.var == 'existing':
            return EXISTING_COLORS.get(int(v))
        if self.var == 'status':
            return STATUS_COLORS.get(int(round(v)), '#9a9a9a')
        return self.colors[classify(v, self.breaks)]

    def legend(self, title: str, stale: bool = False) -> Legend:
        lg = Legend(title)
        if not self.values:
            lg.note = 'Sem dados calculados para esta variável.'
            return lg
        if self.var == 'existing':
            n = sum(1 for v in self.values.values() if v)
            lg.entries = [(EXISTING_COLORS[1], EXISTING_LABELS[1]),
                          (EXISTING_COLORS[0], EXISTING_LABELS[0])]
            lg.note = f'{n} existente(s), {len(self.values) - n} projetado(s)'
            return lg
        if self.var == 'diam_change':
            lg.entries = [(CHANGE_COLORS[k], CHANGE_LABELS[k]) for k in (-1, 0, 1)]
            return lg
        if self.var == 'status':
            lg.entries = [(STATUS_COLORS[k], STATUS_LABELS[k]) for k in (0, 1, 2)]
            return lg
        vals = list(self.values.values())
        lo, hi = min(vals), max(vals)
        edges = [lo] + self.breaks + [hi]
        for i, c in enumerate(self.colors):
            a, b = edges[i], edges[i + 1]
            lg.entries.append((c, f'{a:.2f} – {b:.2f}'))
        lg.note = f'mín {lo:.2f}  máx {hi:.2f} {UNITS.get(self.var, "")}'
        return lg


def violations(project, sim, t=None) -> dict:
    """Elementos fora dos limites das opções de simulação (envoltória se t=None)."""
    o = project.sim_options
    out = {'p_low': [], 'p_high': [], 'v_high': [], 'v_low': [], 'reverse': []}
    if not sim:
        return out
    net = project.network

    def rng(series):
        vals = [v for v in (series or []) if v is not None]
        if t is not None:
            v = value_at(series, t)
            vals = [v] if v is not None else []
        return vals

    for u, d in sim.get('nodes', {}).items():
        n = net.nodes.get(u)
        if n is None or n.KIND != 'junction':
            continue
        vals = rng(d.get('pressure'))
        if vals and min(vals) < o.pressure_min:
            out['p_low'].append(u)
        if vals and max(vals) > o.pressure_max:
            out['p_high'].append(u)
    for u, d in sim.get('links', {}).items():
        l = net.links.get(u)
        if l is None or l.KIND != 'pipe':
            continue
        vals = [abs(v) for v in rng(d.get('velocity'))]
        if vals and max(vals) > o.velocity_max:
            out['v_high'].append(u)
        if vals and o.velocity_min > 0 and max(vals) < o.velocity_min:
            out['v_low'].append(u)
        q = [v for v in (d.get('flow') or []) if v is not None]
        if q and min(q) < -1e-9 and max(q) > 1e-9:
            out['reverse'].append(u)
    return out
