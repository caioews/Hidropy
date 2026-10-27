"""Projeção populacional pelos métodos aritmético e geométrico.

Métodos clássicos de engenharia sanitária, a partir de dois censos (t0, P0) e (t1, P1):

    Aritmético:  Ka = (P1 - P0) / (t1 - t0)          P(t) = P0 + Ka · (t - t0)
    Geométrico:  Kg = (ln P1 - ln P0) / (t1 - t0)    P(t) = P0 · e^(Kg · (t - t0))
                 taxa anual equivalente  i = e^Kg - 1

O estudo salvo no projeto guarda os dados de entrada, os coeficientes, a tabela
projetada e o método adotado, para ser usado depois no cálculo das vazões nodais.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict

from .models import new_uid

METHODS = {'aritmetico': 'Aritmético', 'geometrico': 'Geométrico'}
BASES = {
    'extremos': 'Primeiro e último censo',
    'ultimos': 'Dois últimos censos',
}


class PopulationError(ValueError):
    pass


@dataclass
class PopulationStudy:
    uid: str = field(default_factory=new_uid)
    name: str = 'Projeção populacional'
    created: str = ''
    censuses: list = field(default_factory=list)      # [[ano, população], ...]
    base: str = 'extremos'                             # par de censos usado nos coeficientes
    start_year: int = 0                                # início do plano
    end_year: int = 0                                  # alcance do plano (horizonte)
    step: int = 1                                      # passo da tabela (anos)
    adopted_method: str = 'geometrico'
    # resultados (preenchidos por compute)
    ka: float | None = None                            # hab/ano
    kg: float | None = None                            # 1/ano
    table: list = field(default_factory=list)          # [{'ano':, 'aritmetico':, 'geometrico':}]
    notes: str = ''

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> 'PopulationStudy':
        names = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in (d or {}).items() if k in names})

    # ------------------------------------------------------------------ resultados
    def population(self, year: float, method: str | None = None) -> float:
        """População projetada para um ano qualquer pelo método indicado (ou adotado)."""
        method = method or self.adopted_method
        (t0, p0), _ = base_pair(self.censuses, self.base)
        if method == 'aritmetico':
            return p0 + self.ka * (year - t0)
        if method == 'geometrico':
            return p0 * math.exp(self.kg * (year - t0))
        raise PopulationError(f'Método desconhecido: {method}')

    @property
    def design_population(self) -> float | None:
        """População de projeto: método adotado no ano de alcance do plano."""
        if self.ka is None or self.kg is None:
            return None
        return self.population(self.end_year)

    @property
    def growth_rate(self) -> float | None:
        """Taxa geométrica anual equivalente (fração)."""
        return None if self.kg is None else math.exp(self.kg) - 1.0


def clean_censuses(censuses) -> list[list]:
    """Ordena por ano e valida: ≥ 2 censos, anos distintos, populações > 0."""
    rows = []
    for item in censuses:
        try:
            year, pop = float(item[0]), float(item[1])
        except (TypeError, ValueError, IndexError):
            raise PopulationError('Censo com ano ou população inválidos.')
        if pop <= 0:
            raise PopulationError(f'População do censo de {year:g} deve ser maior que zero.')
        rows.append([int(year) if year.is_integer() else year, pop])
    rows.sort(key=lambda r: r[0])
    if len(rows) < 2:
        raise PopulationError('Informe pelo menos dois censos.')
    years = [r[0] for r in rows]
    if len(set(years)) != len(years):
        raise PopulationError('Há anos de censo repetidos.')
    return rows


def base_pair(censuses, base: str):
    rows = clean_censuses(censuses)
    if base == 'ultimos':
        return tuple(rows[-2]), tuple(rows[-1])
    return tuple(rows[0]), tuple(rows[-1])


def coefficients(censuses, base: str) -> tuple[float, float]:
    (t0, p0), (t1, p1) = base_pair(censuses, base)
    ka = (p1 - p0) / (t1 - t0)
    kg = (math.log(p1) - math.log(p0)) / (t1 - t0)
    return ka, kg


def compute(study: PopulationStudy) -> PopulationStudy:
    """Calcula coeficientes e a tabela projetada (altera e devolve o próprio estudo)."""
    study.censuses = clean_censuses(study.censuses)
    if study.base not in BASES:
        raise PopulationError(f'Base de cálculo desconhecida: {study.base}')
    if study.adopted_method not in METHODS:
        raise PopulationError(f'Método desconhecido: {study.adopted_method}')
    start, end, step = int(study.start_year), int(study.end_year), int(study.step)
    if end < start:
        raise PopulationError('O ano de alcance deve ser igual ou posterior ao ano inicial.')
    if step < 1:
        raise PopulationError('O passo da tabela deve ser de pelo menos 1 ano.')
    study.ka, study.kg = coefficients(study.censuses, study.base)
    years = list(range(start, end + 1, step))
    if years[-1] != end:
        years.append(end)
    study.table = [{'ano': y,
                    'aritmetico': study.population(y, 'aritmetico'),
                    'geometrico': study.population(y, 'geometrico')} for y in years]
    if any(r['aritmetico'] <= 0 for r in study.table):
        study.notes = ('Atenção: o método aritmético resulta em população nula ou negativa '
                       'em parte do horizonte (população em declínio).')
    else:
        study.notes = ''
    return study
