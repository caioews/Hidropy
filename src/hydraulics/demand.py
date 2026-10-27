"""Consumos nodais pelo método linear (vazão por metro de rede).

    Q   = P · q · K1 · K2 / 86400          vazão total de distribuição (L/s)
    L   = Σ comprimentos dos trechos distribuidores (m)
    qm  = Q / L                            vazão linear (L/s por metro)
    Qn  = qm · Σ (L_j / 2)                 demanda do nó: metade de cada trecho distribuidor ligado

P: população (hab); q: consumo per capita (L/hab·dia); K1: coef. do dia de maior consumo;
K2: coef. da hora de maior consumo.

Regras:
  * só junções recebem demanda; a metade de um trecho cuja outra ponta é reservatório ou
    tanque vai inteira para a junção (a vazão total é conservada);
  * trechos com "Distribui vazão" desligado (adutoras, travessias) não entram em L;
  * bombas e válvulas não têm comprimento de distribuição;
  * usa o comprimento hidráulico de cada tubulação.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict

from .models import Junction, Pipe
from .project import Project


@dataclass
class DemandSettings:
    """Parâmetros do método linear (salvos no projeto)."""
    population_source: str = 'adotada'     # 'adotada' (estudo de projeção) | 'manual'
    population_year: int = 0               # 0 = ano de alcance do estudo adotado
    population_method: str = ''            # '' = método adotado no estudo
    manual_population: float = 0.0
    per_capita: float = 150.0              # L/hab·dia
    k1: float = 1.2
    k2: float = 1.5
    use_k1: bool = True
    use_k2: bool = True
    mode: str = 'substituir'               # 'substituir' | 'somar'

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        names = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in (d or {}).items() if k in names})


@dataclass
class LinearResult:
    population: float
    per_capita: float
    k1: float
    k2: float
    total_flow: float = 0.0          # L/s
    total_length: float = 0.0        # m
    linear_rate: float = 0.0         # L/s·m
    nodes: dict = field(default_factory=dict)   # uid -> {'length':, 'old':, 'new':}
    excluded: list = field(default_factory=list)   # uids de tubulações fora do cálculo
    warnings: list = field(default_factory=list)
    mode: str = 'substituir'

    @property
    def distributed_flow(self) -> float:
        return sum(d['added'] for d in self.nodes.values())


class DemandError(ValueError):
    pass


def resolve_population(project: Project, s: DemandSettings) -> tuple[float, str]:
    """(população, descrição da origem)."""
    from .population import METHODS
    if s.population_source == 'manual':
        if s.manual_population <= 0:
            raise DemandError('Informe uma população maior que zero.')
        return float(s.manual_population), 'informada manualmente'
    st = project.population_study()
    if st is None or st.ka is None:
        raise DemandError('Não há projeção populacional adotada no projeto. Faça a projeção em '
                          'Demandas → Projeção populacional ou informe a população manualmente.')
    year = s.population_year or st.end_year
    method = s.population_method or st.adopted_method
    pop = st.population(year, method)
    if pop <= 0:
        raise DemandError(f'A projeção resulta em população não positiva em {year}.')
    return pop, f"estudo '{st.name}', método {METHODS[method].lower()}, ano {year}"


def compute_linear(project: Project, s: DemandSettings, population: float) -> LinearResult:
    net = project.network
    if s.per_capita <= 0:
        raise DemandError('O consumo per capita deve ser maior que zero.')
    k1 = s.k1 if s.use_k1 else 1.0
    k2 = s.k2 if s.use_k2 else 1.0
    if k1 <= 0 or k2 <= 0:
        raise DemandError('Os coeficientes K1 e K2 devem ser maiores que zero.')
    res = LinearResult(population=population, per_capita=s.per_capita, k1=k1, k2=k2,
                       mode=s.mode)
    res.total_flow = population * s.per_capita * k1 * k2 / 86400.0

    junctions = {u: n for u, n in net.nodes.items() if isinstance(n, Junction)}
    influence = {u: 0.0 for u in junctions}
    for l in net.links.values():
        if not isinstance(l, Pipe):
            continue
        if not getattr(l, 'distributes', True):
            res.excluded.append(l.uid)
            continue
        L = net.hydraulic_length(l)
        ends = [u for u in (l.start, l.end) if u in junctions]
        if not ends or L <= 0:
            res.excluded.append(l.uid)
            if not ends:
                res.warnings.append(f"Trecho '{l.name}' liga apenas reservatórios/tanques: "
                                    'fora do cálculo.')
            continue
        res.total_length += L
        for u in ends:
            influence[u] += L / len(ends)       # meia extensão; inteira se a outra ponta não é junção
    if res.total_length <= 0:
        raise DemandError('Nenhum trecho distribuidor com comprimento válido na rede.')
    res.linear_rate = res.total_flow / res.total_length
    for u, n in junctions.items():
        add = res.linear_rate * influence[u]
        new = add if s.mode == 'substituir' else n.base_demand + add
        res.nodes[u] = {'length': influence[u], 'old': n.base_demand, 'added': add, 'new': new}
    sem = [junctions[u].name for u, L in influence.items() if L == 0]
    if sem:
        res.warnings.append(f'{len(sem)} junção(ões) sem trecho distribuidor ligado ficam com '
                            'demanda ' + ('zero' if s.mode == 'substituir' else 'inalterada') +
                            f": {', '.join(sorted(sem)[:15])}" + (' …' if len(sem) > 15 else ''))
    if s.use_k2 and any(n.demand_pattern for n in junctions.values()):
        res.warnings.append('Há junções com padrão temporal de demanda: com K2 aplicado, o pico '
                            'horário pode ser contado duas vezes numa simulação de período '
                            'estendido.')
    return res


def apply_changes(project: Project, res: LinearResult):
    from .editing import update_many
    return update_many(project, [(u, {'base_demand': d['new']}) for u, d in res.nodes.items()])
