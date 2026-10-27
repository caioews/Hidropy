"""Associa os resultados devolvidos pelo motor (indexados por NOME do .inp) aos
identificadores persistentes (uid) dos elementos, usando o mapa gerado na exportação.

Nunca depende da posição dos elementos em listas.
"""

from __future__ import annotations

from ..hydraulics.models import new_uid
from ..hydraulics.project import now_iso


def _base(kind: str, raw: dict, job, log: str) -> dict:
    return {
        'uid': new_uid(), 'kind': kind, 'created': now_iso(),
        'status': raw.get('status', 'failed'), 'error': raw.get('error', ''),
        'inp_sha256': job.export.sha256, 'scenario': job.scenario,
        'engine': raw.get('engine', ''), 'log': log, 'workdir': job.workdir,
        'unmapped': [],
    }


def map_simulation(raw: dict, job, log: str = '') -> dict:
    res = _base('simulation', raw, job, log)
    res['report'] = raw.get('report', '')
    res['warnings'] = raw.get('warnings', [])
    if res['status'] != 'ok':
        res['traceback'] = raw.get('traceback', '')
        return res
    nmap = job.export.name_map
    res['times'] = raw.get('times', [])
    res['nodes'], res['links'] = {}, {}
    for name, data in raw.get('nodes', {}).items():
        uid = nmap['nodes'].get(name)
        if uid is None:
            res['unmapped'].append(name)
        else:
            res['nodes'][uid] = data
    for name, data in raw.get('links', {}).items():
        uid = nmap['links'].get(name)
        if uid is None:
            res['unmapped'].append(name)
        else:
            res['links'][uid] = data
    return res


def map_optimization(raw: dict, job, log: str = '') -> dict:
    res = _base('optimization', raw, job, log)
    res['script_unchanged'] = raw.get('script_unchanged')
    if res['status'] != 'ok':
        res['traceback'] = raw.get('traceback', '')
        return res
    nmap = job.export.name_map
    res['summary'] = raw.get('summary', {})
    res['script_sha256'] = raw.get('script_sha256', '')
    res['pipes'], res['junctions'] = {}, {}
    for name, data in raw.get('pipes', {}).items():
        uid = nmap['links'].get(name)
        if uid is None:
            res['unmapped'].append(name)
        else:
            res['pipes'][uid] = data
    for name, data in raw.get('junctions', {}).items():
        uid = nmap['nodes'].get(name)
        if uid is None:
            res['unmapped'].append(name)
        else:
            res['junctions'][uid] = data
    return res
