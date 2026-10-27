"""Tabelas (pandas.DataFrame) de cadastro e de resultados, e exportação CSV/XLSX."""

from __future__ import annotations

import os

import pandas as pd

from ..hydraulics.models import KIND_LABELS
from ..hydraulics.schema import SCHEMA, format_demand_cats
from . import thematic_views as TV


def _name(project, uid):
    e = project.get(uid) if uid else None
    return e.name if e is not None else ''


def elements_df(project, kind: str) -> pd.DataFrame:
    net = project.network
    rows = []
    props = [p for p in SCHEMA.get(kind, []) if p.type != 'computed' or p.key == 'geom_length']
    elems = [e for e in (list(net.elements()) + list(project.cad.values())) if e.KIND == kind]
    for e in elems:
        row = {}
        for p in props:
            if p.key == 'geom_length':
                row[p.label] = round(net.geometric_length(e), 3)
                continue
            v = getattr(e, p.key, None)
            if p.type.startswith('ref_'):
                v = _name(project, v)
            elif p.type == 'demand_cats':
                v = format_demand_cats(v or [], lambda u: _name(project, u))
            row[p.label + (f' ({p.unit})' if p.unit else '')] = v
        rows.append(row)
    return pd.DataFrame(rows)


def _time_indices(sim, t, all_times):
    n = len(sim.get('times', [])) or 1
    return list(range(n)) if all_times else [min(t or 0, n - 1)]


def _hours(sim, k):
    times = sim.get('times', [])
    return round(times[k] / 3600.0, 4) if k < len(times) else 0.0


def node_results_df(project, sim, t: int = 0, all_times: bool = False) -> pd.DataFrame:
    """Resultados de nós: identificador, coordenadas, cota, demanda, pressão, carga."""
    if not sim:
        return pd.DataFrame()
    net = project.network
    rows = []
    for k in _time_indices(sim, t, all_times):
        for uid, n in net.nodes.items():
            d = sim.get('nodes', {}).get(uid)
            if d is None:
                continue
            if n.KIND == 'reservoir':
                cota = n.ground_elevation
            else:
                cota = getattr(n, 'elevation', None)
            row = {'Tempo (h)': _hours(sim, k)} if all_times else {}
            row.update({
                'ID': n.name, 'Tipo': KIND_LABELS[n.KIND],
                'X (m)': n.x, 'Y (m)': n.y, 'Cota (m)': cota,
                'Demanda (L/s)': TV.value_at(d.get('demand'), k),
                'Pressão (m)': TV.value_at(d.get('pressure'), k),
                'Carga hidráulica (m)': TV.value_at(d.get('head'), k),
            })
            rows.append(row)
    return pd.DataFrame(rows)


def _status_label(v):
    if v is None:
        return None
    return TV.STATUS_LABELS.get(int(round(v)), f'{v:g}')


def link_results_df(project, sim, t: int = 0, all_times: bool = False) -> pd.DataFrame:
    """Resultados de trechos: vazão, comprimento, diâmetro, rugosidade, material, velocidade,
    perda de carga, fator de atrito e estado operacional."""
    if not sim:
        return pd.DataFrame()
    net = project.network
    rows = []
    for k in _time_indices(sim, t, all_times):
        for uid, l in net.links.items():
            d = sim.get('links', {}).get(uid)
            if d is None:
                continue
            is_pipe = l.KIND == 'pipe'
            vel = TV.value_at(d.get('velocity'), k)
            row = {'Tempo (h)': _hours(sim, k)} if all_times else {}
            row.update({
                'ID': l.name, 'Tipo': KIND_LABELS[l.KIND],
                'Nó inicial': _name(project, l.start), 'Nó final': _name(project, l.end),
                'Vazão (L/s)': TV.value_at(d.get('flow'), k),
                'Comprimento (m)': round(net.hydraulic_length(l), 3) if is_pipe else None,
                'Diâmetro (mm)': getattr(l, 'diameter', None),
                'Rugosidade': l.roughness if is_pipe else None,
                'Material': l.material if is_pipe else '',
                'Velocidade (m/s)': abs(vel) if vel is not None else None,
                'Perda de carga unitária (m/km)': TV.value_at(d.get('unit_headloss'), k),
                'Perda de carga (m)': TV.value_at(d.get('headloss'), k),
                'Fator de atrito': TV.value_at(d.get('friction_factor'), k),
                'Estado operacional': _status_label(TV.value_at(d.get('status'), k)),
            })
            rows.append(row)
    return pd.DataFrame(rows)


def export_results(project, sim, path: str, t: int = 0, all_times: bool = False):
    """Planilha de resultados: aba Nós e aba Trechos (CSV gera dois arquivos)."""
    return export_many({'Nos': node_results_df(project, sim, t, all_times),
                        'Trechos': link_results_df(project, sim, t, all_times)}, path)


def optimization_df(project, opt) -> pd.DataFrame:
    rows = []
    if not opt:
        return pd.DataFrame()
    vmax = project.opt_settings.velocidade_max
    for uid, d in opt.get('pipes', {}).items():
        l = project.network.links.get(uid)
        rows.append({
            'ID': l.name if l else '?',
            'Situação': 'existente — mantido' if d.get('fixed') else 'projetado',
            'Diâmetro original (mm)': d.get('orig_diam_mm'),
            'Diâmetro otimizado (mm)': d.get('opt_diam_mm'),
            'Alterado': '' if abs((d.get('opt_diam_mm') or 0) - (d.get('orig_diam_mm') or 0))
            < 1e-6 else 'sim',
            'Comprimento (m)': d.get('length'),
            'Material': getattr(l, 'material', '') if l else '',
            'Custo original (R$)': d.get('cost_orig'),
            'Custo otimizado (R$)': d.get('cost_opt'),
            'Velocidade máx. original (m/s)': d.get('v_max_orig'),
            'Velocidade máx. otimizada (m/s)': d.get('v_max'),
            'Perda unitária otimizada (m/km)': d.get('j_max'),
            'Restrição de velocidade': '' if d.get('fixed') or d.get('v_max') is None else (
                'atende' if d['v_max'] <= vmax else 'NÃO atende'),
        })
    return pd.DataFrame(rows)


def existing_summary(project) -> tuple[int, float]:
    """(quantidade, extensão em m) dos trechos existentes (executados)."""
    net = project.network
    pipes = [l for l in net.links.values() if l.KIND == 'pipe' and l.existing]
    return len(pipes), sum(net.hydraulic_length(l) for l in pipes)


def existing_pipes_df(project) -> pd.DataFrame:
    net = project.network
    return pd.DataFrame([{'ID': l.name, 'Diâmetro (mm)': l.diameter,
                          'Comprimento (m)': round(net.hydraulic_length(l), 3),
                          'Material': l.material, 'Rugosidade': l.roughness}
                         for l in net.links.values() if l.KIND == 'pipe' and l.existing])


def optimization_nodes_df(project, opt) -> pd.DataFrame:
    rows = []
    if not opt:
        return pd.DataFrame()
    for uid, d in opt.get('junctions', {}).items():
        n = project.network.nodes.get(uid)
        rows.append({'ID': n.name if n else '?',
                     'Pressão mín. original (m)': d.get('p_min_orig'),
                     'Pressão mín. otimizada (m)': d.get('p_min'),
                     'Pressão máx. otimizada (m)': d.get('p_max'),
                     'Alvo do script (m)': d.get('alvo'),
                     'Teto físico (m)': d.get('teto'),
                     'Restrição de pressão': 'atende' if d.get('ok_pressure') else 'NÃO atende'})
    return pd.DataFrame(rows)


def export_df(df: pd.DataFrame, path: str, sheet: str = 'Dados'):
    ext = os.path.splitext(path)[1].lower()
    if ext == '.xlsx':
        df.to_excel(path, index=False, sheet_name=sheet[:31])
    else:
        df.to_csv(path, index=False, sep=';', decimal=',', encoding='utf-8-sig')


def export_many(dfs: dict, path: str):
    """Várias tabelas: XLSX com uma aba por tabela; CSV gera um arquivo por tabela."""
    ext = os.path.splitext(path)[1].lower()
    if ext == '.xlsx':
        with pd.ExcelWriter(path) as w:
            for name, df in dfs.items():
                df.to_excel(w, index=False, sheet_name=name[:31])
        return [path]
    base = os.path.splitext(path)[0]
    out = []
    for name, df in dfs.items():
        p = f'{base}_{name}.csv'
        df.to_csv(p, index=False, sep=';', decimal=',', encoding='utf-8-sig')
        out.append(p)
    return out
