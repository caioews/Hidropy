"""Projeto: geometria CAD + camadas + cenários (cada um com sua rede) + resultados."""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

from .models import (CadEntity, Layer, DEFAULT_LAYERS, ProjectSettings, SimulationOptions,
                     OptimizationSettings, Element, element_from_dict, new_uid)
from .network import Network


def now_iso() -> str:
    return _dt.datetime.now().isoformat(timespec='seconds')


@dataclass
class Scenario:
    uid: str = field(default_factory=new_uid)
    name: str = 'Rede original'
    description: str = ''
    created: str = field(default_factory=now_iso)
    parent: str = ''                       # uid do cenário de origem
    network: dict = field(default_factory=dict)   # snapshot (cenários inativos)
    results: list = field(default_factory=list)   # resultados (dicts) desta rede

    def to_dict(self):
        return {'uid': self.uid, 'name': self.name, 'description': self.description,
                'created': self.created, 'parent': self.parent, 'network': self.network,
                'results': self.results}


class Project:
    FORMAT_VERSION = 1

    def __init__(self):
        self.meta = {'title': 'Projeto sem título', 'created': now_iso(), 'modified': now_iso(),
                     'author': '', 'external_files': []}
        self.settings = ProjectSettings()
        self.sim_options = SimulationOptions()
        self.opt_settings = OptimizationSettings()
        self.layers: dict[str, Layer] = {}
        self.cad: dict[str, CadEntity] = {}
        self.network = Network()
        base = Scenario()
        self.scenarios: list[Scenario] = [base]
        self.active_scenario = base.uid
        self.display_origin = (0.0, 0.0)
        self.path: str | None = None
        # estudos de projeção populacional; o adotado alimenta o cálculo das vazões nodais
        self.population_studies: list = []
        self.adopted_population: str = ''
        from .demand import DemandSettings
        self.demand_settings = DemandSettings()
        for name, color in DEFAULT_LAYERS:
            self.add_layer(Layer(name=name, color=color))

    # ------------------------------------------------------------- camadas
    def add_layer(self, layer: Layer) -> Layer:
        self.layers[layer.uid] = layer
        return layer

    def layer_by_name(self, name: str) -> Layer | None:
        for l in self.layers.values():
            if l.name == name:
                return l
        return None

    def ensure_layer(self, name: str, color: str = '#c8c8c8', **kw) -> Layer:
        l = self.layer_by_name(name)
        if l is None:
            l = self.add_layer(Layer(name=name, color=color, **kw))
        return l

    def layer_visible(self, name: str) -> bool:
        l = self.layer_by_name(name)
        if l is None:
            return True
        if l.reference and not self.settings.show_reference_layers:
            return False
        return l.visible

    def layer_locked(self, name: str) -> bool:
        l = self.layer_by_name(name)
        return bool(l and l.locked)

    # ------------------------------------------------------------- elementos
    def get(self, uid: str) -> Element | None:
        e = self.network.get(uid)
        if e is None:
            e = self.cad.get(uid)
        return e

    def put(self, elem: Element):
        if elem.COLLECTION == 'cad':
            self.cad[elem.uid] = elem
        else:
            self.network.put(elem)

    def remove(self, uid: str) -> Element | None:
        e = self.network.remove(uid)
        if e is None:
            e = self.cad.pop(uid, None)
        return e

    def get_dict(self, uid: str) -> dict | None:
        e = self.get(uid)
        return e.to_dict() if e is not None else None

    def put_dict(self, d: dict) -> Element:
        e = element_from_dict(d)
        self.put(e)
        return e

    # ------------------------------------------------------------- cenários
    def scenario(self, uid: str | None = None) -> Scenario:
        uid = uid or self.active_scenario
        for s in self.scenarios:
            if s.uid == uid:
                return s
        raise KeyError(uid)

    def sync_active_scenario(self):
        self.scenario().network = self.network.to_dict()

    def create_scenario(self, name: str, description: str = '',
                        network: Network | None = None) -> Scenario:
        """Cria um cenário por cópia controlada da rede ativa (ou da rede fornecida)."""
        src = network if network is not None else self.network
        s = Scenario(name=name, description=description, parent=self.active_scenario,
                     network=src.to_dict())
        self.scenarios.append(s)
        return s

    def switch_scenario(self, uid: str):
        if uid == self.active_scenario:
            return
        self.sync_active_scenario()
        target = self.scenario(uid)
        self.network = Network.from_dict(target.network)
        self.active_scenario = uid

    def delete_scenario(self, uid: str):
        if uid == self.active_scenario:
            raise ValueError('Não é possível excluir o cenário ativo.')
        self.scenarios = [s for s in self.scenarios if s.uid != uid]

    # ------------------------------------------------------------- resultados
    def results(self, kind: str | None = None) -> list[dict]:
        res = self.scenario().results
        return [r for r in res if kind is None or r.get('kind') == kind]

    def latest_result(self, kind: str) -> dict | None:
        res = [r for r in self.results(kind) if r.get('status') == 'ok']
        return res[-1] if res else None

    def add_result(self, result: dict, keep_last: int = 5):
        res = self.scenario().results
        res.append(result)
        same = [r for r in res if r.get('kind') == result.get('kind')]
        for old in same[:-keep_last]:
            res.remove(old)

    # ------------------------------------------------------------- população
    def population_study(self, uid: str | None = None):
        uid = uid or self.adopted_population
        return next((s for s in self.population_studies if s.uid == uid), None)

    def save_population_study(self, study, adopt: bool = True):
        """Inclui ou substitui (mesmo uid) um estudo; por padrão passa a ser o adotado."""
        self.population_studies = [s for s in self.population_studies if s.uid != study.uid]
        self.population_studies.append(study)
        if adopt or not self.adopted_population:
            self.adopted_population = study.uid

    def delete_population_study(self, uid: str):
        self.population_studies = [s for s in self.population_studies if s.uid != uid]
        if self.adopted_population == uid:
            self.adopted_population = (self.population_studies[-1].uid
                                       if self.population_studies else '')

    # ------------------------------------------------------------- extensão
    def bounds(self):
        xs, ys = [], []
        b = self.network.bounds()
        if b:
            xs += [b[0], b[2]]
            ys += [b[1], b[3]]
        for e in self.cad.values():
            for p in e.points:
                xs.append(p[0])
                ys.append(p[1])
                if e.geom in ('circle', 'arc'):
                    xs += [p[0] - e.radius, p[0] + e.radius]
                    ys += [p[1] - e.radius, p[1] + e.radius]
        if not xs:
            return None
        return min(xs), min(ys), max(xs), max(ys)
