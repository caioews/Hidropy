"""Modelos de dados do projeto (independentes da interface gráfica).

Unidades internas (as mesmas do EPANET com FLOW UNITS = LPS):
    coordenadas, cotas, comprimentos, cargas ... m
    diâmetros .................................. mm
    vazões e demandas .......................... L/s
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field, fields, asdict
from typing import Any, ClassVar


def new_uid() -> str:
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Elemento base
# ---------------------------------------------------------------------------

@dataclass
class Element:
    """Base de todos os elementos persistentes do projeto."""

    COLLECTION: ClassVar[str] = ''
    KIND: ClassVar[str] = ''
    DEFAULT_LAYER: ClassVar[str] = ''

    uid: str = field(default_factory=new_uid)
    name: str = ''
    layer: str = ''
    notes: str = ''

    def __post_init__(self):
        if not self.layer:
            self.layer = self.DEFAULT_LAYER

    @property
    def kind(self) -> str:
        return self.KIND

    def to_dict(self) -> dict:
        d = asdict(self)
        d['kind'] = self.KIND
        return d

    def clone(self) -> 'Element':
        return copy.deepcopy(self)


# ---------------------------------------------------------------------------
# Nós
# ---------------------------------------------------------------------------

@dataclass
class Node(Element):
    COLLECTION: ClassVar[str] = 'node'
    x: float = 0.0
    y: float = 0.0


@dataclass
class Junction(Node):
    KIND: ClassVar[str] = 'junction'
    DEFAULT_LAYER: ClassVar[str] = 'Nós'
    elevation: float = 0.0
    base_demand: float = 0.0          # L/s
    demand_pattern: str = ''          # uid de Pattern
    demand_categories: list = field(default_factory=list)  # [{'base':, 'pattern':, 'name':}]
    emitter_coeff: float = 0.0


@dataclass
class Reservoir(Node):
    KIND: ClassVar[str] = 'reservoir'
    DEFAULT_LAYER: ClassVar[str] = 'Reservatórios'
    head: float = 0.0                 # carga hidráulica total (m)
    head_pattern: str = ''
    ground_elevation: float | None = None   # informativo (não vai ao EPANET)


@dataclass
class Tank(Node):
    KIND: ClassVar[str] = 'tank'
    DEFAULT_LAYER: ClassVar[str] = 'Tanques'
    elevation: float = 0.0            # cota do fundo
    init_level: float = 1.0
    min_level: float = 0.0
    max_level: float = 3.0
    diameter: float = 10.0            # m (diâmetro do tanque!)
    min_volume: float = 0.0
    volume_curve: str = ''            # uid de Curve (VOLUME)
    overflow: bool = False


# ---------------------------------------------------------------------------
# Ligações
# ---------------------------------------------------------------------------

@dataclass
class Link(Element):
    COLLECTION: ClassVar[str] = 'link'
    start: str = ''                   # uid do nó inicial
    end: str = ''                     # uid do nó final
    vertices: list = field(default_factory=list)   # [[x, y], ...]


PIPE_STATUS = ['Open', 'Closed', 'CV']


@dataclass
class Pipe(Link):
    KIND: ClassVar[str] = 'pipe'
    DEFAULT_LAYER: ClassVar[str] = 'Tubulações'
    length: float = 0.0               # comprimento hidráulico (m)
    auto_length: bool = True          # True => length = comprimento geométrico
    diameter: float = 100.0           # mm
    roughness: float = 130.0          # C de Hazen-Williams (ou conforme fórmula)
    minor_loss: float = 0.0
    material: str = 'PVC'
    status: str = 'Open'
    cost_per_m: float | None = None   # informativo; o otimizador usa o catálogo
    fixed_in_optimization: bool = False   # trecho existente (executado) => TRECHOS_FIXOS
    distributes: bool = True              # entra no comprimento do método linear de demandas

    @property
    def existing(self) -> bool:
        """Trecho já executado: o otimizador (main4.py) não altera o diâmetro."""
        return bool(self.fixed_in_optimization)


@dataclass
class Pump(Link):
    KIND: ClassVar[str] = 'pump'
    DEFAULT_LAYER: ClassVar[str] = 'Bombas'
    curve: str = ''                   # uid de Curve (PUMP)
    power: float | None = None        # kW (bomba de potência constante)
    speed: float = 1.0
    pattern: str = ''
    status: str = 'Open'


VALVE_TYPES = {
    'PRV': 'Redutora de pressão (PRV)',
    'PSV': 'Sustentadora de pressão (PSV)',
    'PBV': 'Quebra-pressão (PBV)',
    'FCV': 'Controle de vazão (FCV)',
    'TCV': 'Controle de perda / borboleta (TCV)',
    'GPV': 'Perda genérica por curva (GPV)',
}
VALVE_STATUS = ['None', 'Open', 'Closed']


@dataclass
class Valve(Link):
    KIND: ClassVar[str] = 'valve'
    DEFAULT_LAYER: ClassVar[str] = 'Válvulas'
    valve_type: str = 'PRV'
    diameter: float = 100.0           # mm
    setting: float = 0.0              # m (PRV/PSV/PBV), L/s (FCV), coef. (TCV)
    headloss_curve: str = ''          # uid de Curve (GPV)
    minor_loss: float = 0.0
    status: str = 'None'


# ---------------------------------------------------------------------------
# Dados auxiliares do modelo hidráulico
# ---------------------------------------------------------------------------

CURVE_TYPES = ['PUMP', 'EFFICIENCY', 'VOLUME', 'HEADLOSS']


@dataclass
class Curve(Element):
    COLLECTION: ClassVar[str] = 'curve'
    KIND: ClassVar[str] = 'curve'
    curve_type: str = 'PUMP'
    points: list = field(default_factory=list)   # [[x, y]]; bomba: [vazão L/s, carga m]


@dataclass
class Pattern(Element):
    COLLECTION: ClassVar[str] = 'pattern'
    KIND: ClassVar[str] = 'pattern'
    multipliers: list = field(default_factory=lambda: [1.0])


CONTROL_CONDITIONS = ['AT TIME', 'AT CLOCKTIME', 'IF NODE ABOVE', 'IF NODE BELOW']


@dataclass
class Control(Element):
    """Controle simples do EPANET ([CONTROLS])."""
    COLLECTION: ClassVar[str] = 'control'
    KIND: ClassVar[str] = 'control'
    link: str = ''                    # uid
    action: str = 'OPEN'              # OPEN, CLOSED ou valor numérico de ajuste
    condition: str = 'AT TIME'
    node: str = ''                    # uid (só para IF NODE)
    value: str = '0'                  # nível/pressão, ou hora ("6", "6:30", "6:00 AM")


# ---------------------------------------------------------------------------
# Geometria CAD
# ---------------------------------------------------------------------------

CAD_TYPES = ['line', 'polyline', 'circle', 'arc', 'text', 'dimension', 'point']


@dataclass
class CadEntity(Element):
    COLLECTION: ClassVar[str] = 'cad'
    KIND: ClassVar[str] = 'cad'
    DEFAULT_LAYER: ClassVar[str] = '0'
    geom: str = 'line'
    points: list = field(default_factory=list)   # line: 2 pts; polyline: n; arc/circle: [centro]
    closed: bool = False
    radius: float = 0.0
    start_angle: float = 0.0          # graus (arco, sentido anti-horário)
    end_angle: float = 360.0
    text: str = ''
    height: float = 1.0               # altura do texto (m)
    rotation: float = 0.0             # graus
    offset: float = 2.0               # deslocamento da linha de cota (m)
    color: str = ''                   # '' => cor da camada
    z: float = 0.0                    # elevação original do DXF (preservada)


@dataclass
class Layer:
    uid: str = field(default_factory=new_uid)
    name: str = '0'
    color: str = '#c8c8c8'
    visible: bool = True
    locked: bool = False
    line_width: float = 1.0           # px
    reference: bool = False           # camada de referência (DXF importado)
    source: str = 'sistema'           # 'sistema', 'dxf', 'usuario'

    def to_dict(self):
        return asdict(self)


DEFAULT_LAYERS = [
    ('Rede de água', '#1f77b4'),
    ('Tubulações', '#2a6fdb'),
    ('Nós', '#0b3d91'),
    ('Reservatórios', '#2ca02c'),
    ('Tanques', '#17becf'),
    ('Bombas', '#d62728'),
    ('Válvulas', '#9467bd'),
    ('Base topográfica', '#9a9a9a'),
    ('Curvas de nível', '#b5a27a'),
    ('Edificações', '#8c564b'),
    ('Textos', '#444444'),
    ('Cotas', '#e377c2'),
    ('Resultados hidráulicos', '#ff7f0e'),
    ('0', '#c8c8c8'),
]


# ---------------------------------------------------------------------------
# Opções
# ---------------------------------------------------------------------------

@dataclass
class SimulationOptions:
    """Opções enviadas às seções [TIMES] e [OPTIONS] do .inp."""
    duration_h: float = 0.0
    hydraulic_step_h: float = 1.0
    pattern_step_h: float = 1.0
    report_step_h: float = 1.0
    start_clocktime_h: float = 0.0
    headloss: str = 'H-W'             # H-W, D-W, C-M
    trials: int = 200
    accuracy: float = 0.001
    demand_multiplier: float = 1.0
    viscosity: float = 1.0
    specific_gravity: float = 1.0
    default_pattern: str = ''         # uid
    # limites usados na verificação de restrições e nos mapas temáticos
    pressure_min: float = 10.0
    pressure_max: float = 50.0
    velocity_min: float = 0.0
    velocity_max: float = 3.0

    def to_dict(self):
        return asdict(self)


# Catálogo padrão — cópia de CATALOGO_COMPLETO do main4.py (DN mm, diâmetro m, R$/m)
DEFAULT_CATALOG = [
    [50, 0.050, 25.00], [75, 0.075, 40.00], [100, 0.100, 62.00],
    [150, 0.150, 125.00], [200, 0.200, 205.00], [250, 0.250, 310.00],
    [300, 0.300, 440.00], [350, 0.350, 550.00], [400, 0.400, 700.00],
    [450, 0.450, 860.00], [500, 0.500, 1000.00], [600, 0.600, 1330.00],
    [700, 0.700, 1690.00], [800, 0.800, 2090.00], [900, 0.900, 2500.00],
    [1000, 1.000, 2950.00],
]


@dataclass
class OptimizationSettings:
    """Cada campo corresponde a uma constante real de main4.py (mesmo nome em MAIUSCULAS)."""
    semente: int = 42
    tam_populacao: int = 120
    num_geracoes: int = 150
    prob_cruzamento: float = 0.7
    prob_mutacao: float = 0.3
    prob_mut_gene: float | None = None
    tam_torneio: int = 3
    parada_sem_melhora: int = 40
    catalogo_completo: list = field(default_factory=lambda: copy.deepcopy(DEFAULT_CATALOG))
    dn_min_permitido: float | None = None
    dn_max_permitido: float | None = None
    margem_dn_acima: int = 2
    pressao_min: float = 10.0
    pressao_max: float = 50.0
    tolerancia_pressao: float = 0.01
    perda_admitida_excecao: float = 1.0
    pressao_min_absoluta: float = 6.0
    velocidade_max: float = 3.0
    aplicar_limite_perda_unitaria: bool = False
    perda_carga_max: float = 10.0

    def to_dict(self):
        return asdict(self)

    def script_constants(self) -> dict:
        """Mapeia para os nomes das constantes de main4.py."""
        return {f.name.upper(): copy.deepcopy(getattr(self, f.name)) for f in fields(self)}


@dataclass
class ProjectSettings:
    grid_spacing: float = 10.0
    grid_visible: bool = True
    snap_grid: bool = False
    snap_nodes: bool = True
    snap_endpoints: bool = True
    snap_midpoints: bool = True
    snap_intersections: bool = True
    snap_tolerance_px: float = 10.0
    connect_tolerance: float = 0.05   # m: distância para considerar pontos coincidentes
    auto_create_junction: bool = True
    show_node_labels: bool = False
    show_link_labels: bool = False
    show_diameters: bool = False
    show_pressures: bool = False
    show_flows: bool = False
    show_velocities: bool = False
    show_flow_arrows: bool = False
    show_symbols: bool = True
    show_reference_layers: bool = True
    python_interpreter: str = ''      # vazio => mesmo interpretador da interface
    script_path: str = ''             # vazio => main4.py ao lado de main.py
    length_unit: str = 'm'
    dxf_source_units: str = ''
    # exportação das plantas DXF
    dxf_plan: str = 'calc'                 # 'calc' | 'exec'
    dxf_text_height: float = 2.0           # m — também a escala dos blocos de conexão
    dxf_include_cad: bool = True
    dxf_calc_link_fields: list = field(default_factory=lambda: [
        'name', 'dn', 'length', 'flow', 'velocity', 'unit_headloss'])
    dxf_calc_node_fields: list = field(default_factory=lambda: ['name', 'elevation',
                                                                'pressure'])
    dxf_calc_arrows: bool = True
    fit_tolerance: float = 3.0             # deflexão absorvida pela junta (graus)
    fit_min_segment: float = 0.5           # m: vértices mais próximos são unidos
    fit_curve_ends: str = 'auto'          # 'auto' | 'BB' | 'BP'
    fit_vertex_bends: bool = True
    fit_caps: bool = True
    fit_callouts: bool = True
    fit_callout_style: str = 'mleader'     # 'mleader' | 'leader' | 'linhas'
    fit_table: bool = True
    fit_pipe_labels: bool = True
    fittings_library: str = ''             # vazio = biblioteca do programa

    def to_dict(self):
        return asdict(self)


# ---------------------------------------------------------------------------
# Fábrica a partir de dicionários
# ---------------------------------------------------------------------------

ELEMENT_CLASSES: dict[str, type[Element]] = {
    c.KIND: c for c in (Junction, Reservoir, Tank, Pipe, Pump, Valve,
                        Curve, Pattern, Control, CadEntity)
}

NODE_KINDS = ('junction', 'reservoir', 'tank')
LINK_KINDS = ('pipe', 'pump', 'valve')

KIND_LABELS = {
    'junction': 'Junção', 'reservoir': 'Reservatório', 'tank': 'Tanque',
    'pipe': 'Tubulação', 'pump': 'Bomba', 'valve': 'Válvula',
    'curve': 'Curva', 'pattern': 'Padrão', 'control': 'Controle', 'cad': 'Entidade CAD',
}

NAME_PREFIX = {
    'junction': 'J', 'reservoir': 'R', 'tank': 'T', 'pipe': 'P', 'pump': 'B',
    'valve': 'V', 'curve': 'C', 'pattern': 'PAD', 'control': 'CTRL', 'cad': 'E',
}


def _dataclass_from_dict(cls, d: dict):
    names = {f.name for f in fields(cls)}
    return cls(**{k: copy.deepcopy(v) for k, v in d.items() if k in names})


def element_from_dict(d: dict) -> Element:
    cls = ELEMENT_CLASSES.get(d.get('kind'))
    if cls is None:
        raise ValueError(f"Tipo de elemento desconhecido: {d.get('kind')!r}")
    return _dataclass_from_dict(cls, d)


def layer_from_dict(d: dict) -> Layer:
    return _dataclass_from_dict(Layer, d)


def options_from_dict(cls, d: dict | None):
    return _dataclass_from_dict(cls, d or {})


def value_from_settings(obj: Any) -> dict:
    return asdict(obj)
