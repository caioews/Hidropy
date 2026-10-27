"""Descrição das propriedades editáveis de cada tipo de elemento.

Usado pelo painel de propriedades e pelas tabelas de elementos (a interface
gera os editores a partir daqui; a validação dos valores também).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import PIPE_STATUS, VALVE_TYPES, VALVE_STATUS, CURVE_TYPES, CONTROL_CONDITIONS


@dataclass
class Prop:
    key: str
    label: str
    type: str = 'float'      # str, float, float_opt, int, bool, choice, ref_node, ref_link,
                             # ref_pattern, ref_curve, layer, demand_cats, computed
    unit: str = ''
    choices: list = field(default_factory=list)
    min: float | None = None
    max: float | None = None
    required: bool = True
    note: str = ''
    batch: bool = True       # pode ser editada em lote


COMMON = [Prop('name', 'Identificador', 'str', batch=False),
          Prop('layer', 'Camada', 'layer')]
TAIL = [Prop('notes', 'Observações', 'str', required=False)]
NODE_XY = [Prop('x', 'Coordenada X', 'float', 'm', batch=False),
           Prop('y', 'Coordenada Y', 'float', 'm', batch=False)]

SCHEMA: dict[str, list[Prop]] = {
    'junction': COMMON + NODE_XY + [
        Prop('elevation', 'Cota topográfica', 'float', 'm'),
        Prop('base_demand', 'Demanda-base', 'float', 'L/s'),
        Prop('demand_pattern', 'Padrão de demanda', 'ref_pattern', required=False),
        Prop('demand_categories', 'Categorias de demanda adicionais', 'demand_cats',
             required=False, note='formato: vazão:padrão:nome; ...'),
        Prop('emitter_coeff', 'Coeficiente do emissor', 'float', 'L/s/m^0,5', min=0),
    ] + TAIL,
    'reservoir': COMMON + NODE_XY + [
        Prop('head', 'Carga hidráulica (nível d\'água)', 'float', 'm'),
        Prop('head_pattern', 'Padrão de carga', 'ref_pattern', required=False),
        Prop('ground_elevation', 'Cota de referência do terreno', 'float_opt', 'm',
             required=False, note='informativo: não é enviado ao motor de cálculo'),
    ] + TAIL,
    'tank': COMMON + NODE_XY + [
        Prop('elevation', 'Cota do fundo', 'float', 'm'),
        Prop('init_level', 'Nível inicial', 'float', 'm', min=0),
        Prop('min_level', 'Nível mínimo', 'float', 'm', min=0),
        Prop('max_level', 'Nível máximo', 'float', 'm', min=0),
        Prop('diameter', 'Diâmetro do tanque', 'float', 'm', min=0),
        Prop('min_volume', 'Volume mínimo', 'float', 'm³', min=0),
        Prop('volume_curve', 'Curva de volume', 'ref_curve', required=False),
        Prop('overflow', 'Permite extravasamento', 'bool'),
    ] + TAIL,
    'pipe': COMMON + [
        Prop('start', 'Nó inicial', 'ref_node', batch=False),
        Prop('end', 'Nó final', 'ref_node', batch=False),
        Prop('geom_length', 'Comprimento geométrico (planta)', 'computed', 'm'),
        Prop('auto_length', 'Comprimento automático (= geométrico)', 'bool'),
        Prop('length', 'Comprimento hidráulico', 'float', 'm', min=0,
             note='usado quando o comprimento automático está desligado'),
        Prop('diameter', 'Diâmetro', 'float', 'mm', min=0),
        Prop('roughness', 'Rugosidade (C em H-W; mm em D-W)', 'float', '', min=0),
        Prop('minor_loss', 'Coef. de perda localizada', 'float', '', min=0),
        Prop('material', 'Material', 'str', required=False),
        Prop('status', 'Estado operacional', 'choice', choices=PIPE_STATUS),
        Prop('cost_per_m', 'Custo unitário (informativo)', 'float_opt', 'R$/m', required=False,
             note='o otimizador main4.py usa o custo do catálogo'),
        Prop('distributes', 'Distribui vazão (método linear)', 'bool',
             note='Desligue em adutoras e travessias sem ligações: o trecho não entra no '
                  'comprimento usado no cálculo das demandas nodais.'),
        Prop('fixed_in_optimization', 'Trecho existente (executado)', 'bool',
             note='Trecho já executado: a otimização mantém o diâmetro e não o inclui no '
                  'custo (TRECHOS_FIXOS do main4.py).'),
    ] + TAIL,
    'pump': COMMON + [
        Prop('start', 'Nó de sucção', 'ref_node', batch=False),
        Prop('end', 'Nó de recalque', 'ref_node', batch=False),
        Prop('curve', 'Curva característica', 'ref_curve', required=False),
        Prop('power', 'Potência (se sem curva)', 'float_opt', 'kW', required=False),
        Prop('speed', 'Velocidade relativa', 'float', '', min=0),
        Prop('pattern', 'Padrão de velocidade', 'ref_pattern', required=False),
        Prop('status', 'Estado inicial', 'choice', choices=['Open', 'Closed']),
    ] + TAIL,
    'valve': COMMON + [
        Prop('start', 'Nó de montante', 'ref_node', batch=False),
        Prop('end', 'Nó de jusante', 'ref_node', batch=False),
        Prop('valve_type', 'Tipo', 'choice', choices=list(VALVE_TYPES)),
        Prop('diameter', 'Diâmetro', 'float', 'mm', min=0),
        Prop('setting', 'Ajuste (pressão m / vazão L/s / coef.)', 'float', min=0),
        Prop('headloss_curve', 'Curva de perda (GPV)', 'ref_curve', required=False),
        Prop('minor_loss', 'Coef. de perda localizada', 'float', '', min=0),
        Prop('status', 'Estado fixo', 'choice', choices=VALVE_STATUS),
    ] + TAIL,
    'curve': [Prop('name', 'Identificador', 'str', batch=False),
              Prop('curve_type', 'Tipo', 'choice', choices=CURVE_TYPES)] + TAIL,
    'pattern': [Prop('name', 'Identificador', 'str', batch=False)] + TAIL,
    'control': [Prop('name', 'Identificador', 'str', batch=False),
                Prop('link', 'Ligação', 'ref_link'),
                Prop('action', 'Ação (OPEN/CLOSED/valor)', 'str'),
                Prop('condition', 'Condição', 'choice', choices=CONTROL_CONDITIONS),
                Prop('node', 'Nó da condição', 'ref_node', required=False),
                Prop('value', 'Valor (nível, pressão ou hora)', 'str')] + TAIL,
    'cad': [Prop('layer', 'Camada', 'layer'),
            Prop('geom', 'Geometria', 'computed'),
            Prop('text', 'Texto', 'str', required=False),
            Prop('height', 'Altura do texto', 'float', 'm', min=0),
            Prop('rotation', 'Rotação', 'float', '°'),
            Prop('radius', 'Raio', 'float', 'm', min=0),
            Prop('color', 'Cor (vazio = da camada)', 'str', required=False)] + TAIL,
}

CAD_PROPS_BY_GEOM = {
    'text': {'layer', 'geom', 'text', 'height', 'rotation', 'color', 'notes'},
    'circle': {'layer', 'geom', 'radius', 'color', 'notes'},
    'arc': {'layer', 'geom', 'radius', 'color', 'notes'},
}


def props_for(e) -> list[Prop]:
    props = SCHEMA.get(e.KIND, [])
    if e.KIND == 'cad':
        allowed = CAD_PROPS_BY_GEOM.get(e.geom, {'layer', 'geom', 'color', 'notes'})
        props = [p for p in props if p.key in allowed]
    return props


def format_demand_cats(cats, pattern_name) -> str:
    return '; '.join(f"{c.get('base', 0):g}:{pattern_name(c.get('pattern', ''))}:"
                     f"{c.get('name', '')}" for c in cats)


def parse_demand_cats(text: str, pattern_uid) -> list[dict]:
    out = []
    for part in text.split(';'):
        part = part.strip()
        if not part:
            continue
        bits = [b.strip() for b in part.split(':')]
        base = float(bits[0].replace(',', '.'))
        pat = pattern_uid(bits[1]) if len(bits) > 1 and bits[1] else ''
        if len(bits) > 1 and bits[1] and not pat:
            raise ValueError(f'Padrão inexistente: {bits[1]}')
        out.append({'base': base, 'pattern': pat, 'name': bits[2] if len(bits) > 2 else ''})
    return out


def parse_value(prop: Prop, text: str):
    """Converte e valida o texto digitado. Lança ValueError com mensagem clara."""
    t = text.strip()
    if prop.type in ('float', 'float_opt', 'int'):
        if not t:
            if prop.type == 'float_opt' or not prop.required:
                return None
            raise ValueError(f'{prop.label}: valor obrigatório.')
        try:
            v = float(t.replace(',', '.'))
        except ValueError:
            raise ValueError(f'{prop.label}: número inválido ({text}).')
        if prop.min is not None and v < prop.min:
            raise ValueError(f'{prop.label}: deve ser ≥ {prop.min:g}.')
        if prop.max is not None and v > prop.max:
            raise ValueError(f'{prop.label}: deve ser ≤ {prop.max:g}.')
        return int(v) if prop.type == 'int' else v
    if prop.type == 'str':
        if prop.key == 'name' and not t:
            raise ValueError('O identificador não pode ficar vazio.')
        return t
    return t
