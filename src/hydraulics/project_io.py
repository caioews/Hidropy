"""Leitura e gravação do formato de projeto .shcad (JSON UTF-8)."""

from __future__ import annotations

import json
import os
import shutil

from .models import (CadEntity, ProjectSettings, SimulationOptions, OptimizationSettings,
                     element_from_dict, layer_from_dict, options_from_dict)
from .network import Network
from .population import PopulationStudy
from .demand import DemandSettings
from .project import Project, Scenario, now_iso

EXTENSION = '.shcad'


class ProjectFormatError(Exception):
    pass


def project_to_dict(project: Project) -> dict:
    project.sync_active_scenario()
    project.meta['modified'] = now_iso()
    return {
        'format': 'SHCAD',
        'version': Project.FORMAT_VERSION,
        'meta': project.meta,
        'settings': project.settings.to_dict(),
        'sim_options': project.sim_options.to_dict(),
        'opt_settings': project.opt_settings.to_dict(),
        'display_origin': list(project.display_origin),
        'layers': [l.to_dict() for l in project.layers.values()],
        'cad': [e.to_dict() for e in project.cad.values()],
        'scenarios': [s.to_dict() for s in project.scenarios],
        'active_scenario': project.active_scenario,
        'population': {'studies': [s.to_dict() for s in project.population_studies],
                       'adopted': project.adopted_population},
        'demand_settings': project.demand_settings.to_dict(),
    }


def project_from_dict(d: dict) -> Project:
    if d.get('format') != 'SHCAD':
        raise ProjectFormatError('O arquivo não é um projeto SHCAD.')
    if int(d.get('version', 0)) > Project.FORMAT_VERSION:
        raise ProjectFormatError(
            f"Projeto criado em versão mais nova do formato ({d.get('version')}).")
    p = Project()
    p.meta.update(d.get('meta', {}))
    p.settings = options_from_dict(ProjectSettings, d.get('settings'))
    p.sim_options = options_from_dict(SimulationOptions, d.get('sim_options'))
    p.opt_settings = options_from_dict(OptimizationSettings, d.get('opt_settings'))
    p.display_origin = tuple(d.get('display_origin', (0.0, 0.0)))
    p.layers = {}
    for ld in d.get('layers', []):
        l = layer_from_dict(ld)
        p.layers[l.uid] = l
    p.cad = {}
    for ed in d.get('cad', []):
        e = element_from_dict(ed)
        if isinstance(e, CadEntity):
            p.cad[e.uid] = e
    p.scenarios = []
    for sd in d.get('scenarios', []):
        p.scenarios.append(Scenario(**{k: sd.get(k) for k in
                                       ('uid', 'name', 'description', 'created', 'parent',
                                        'network', 'results') if k in sd}))
    if not p.scenarios:
        p.scenarios = [Scenario()]
    p.active_scenario = d.get('active_scenario') or p.scenarios[0].uid
    if p.active_scenario not in {s.uid for s in p.scenarios}:
        p.active_scenario = p.scenarios[0].uid
    p.network = Network.from_dict(p.scenario().network)
    pop = d.get('population') or {}
    p.population_studies = [PopulationStudy.from_dict(x) for x in pop.get('studies', [])]
    p.adopted_population = pop.get('adopted', '')
    p.demand_settings = DemandSettings.from_dict(d.get('demand_settings'))
    # garante que toda camada referenciada exista
    for e in list(p.cad.values()) + list(p.network.elements()):
        if e.layer and p.layer_by_name(e.layer) is None:
            p.ensure_layer(e.layer)
    return p


def save_project(project: Project, path: str, backup: bool = True):
    """Grava de forma atômica; mantém cópia de segurança <arquivo>.bak."""
    path = os.path.abspath(path)
    data = project_to_dict(project)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    if backup and os.path.exists(path):
        shutil.copy2(path, path + '.bak')
    os.replace(tmp, path)
    project.path = path


def load_project(path: str) -> Project:
    path = os.path.abspath(path)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ProjectFormatError(f'Arquivo corrompido: {e}') from e
    p = project_from_dict(data)
    p.path = path
    return p
