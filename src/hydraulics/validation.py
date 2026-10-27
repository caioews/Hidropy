"""Validação do modelo antes da execução. Separa erros impeditivos de advertências."""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import connectivity
from .models import KIND_LABELS
from .project import Project

ERROR = 'erro'
WARNING = 'advertência'

_INVALID_NAME = re.compile(r'[\s;"]')


@dataclass
class Issue:
    severity: str
    code: str
    message: str
    uid: str = ''

    @property
    def is_error(self) -> bool:
        return self.severity == ERROR


def _label(e) -> str:
    return f"{KIND_LABELS.get(e.KIND, e.KIND)} '{e.name}'"


def validate(project: Project) -> list[Issue]:
    net = project.network
    tol = project.settings.connect_tolerance
    issues: list[Issue] = []

    def err(code, msg, uid=''):
        issues.append(Issue(ERROR, code, msg, uid))

    def warn(code, msg, uid=''):
        issues.append(Issue(WARNING, code, msg, uid))

    # --- identificadores -----------------------------------------------------
    seen: dict[tuple[str, str], str] = {}
    for e in net.elements():
        if not e.name.strip():
            err('ID_VAZIO', f'{KIND_LABELS.get(e.KIND)} sem identificador.', e.uid)
            continue
        if len(e.name) > 31:
            err('ID_LONGO', f'{_label(e)}: identificador com mais de 31 caracteres '
                            '(limite do EPANET).', e.uid)
        if _INVALID_NAME.search(e.name):
            warn('ID_CARACTER', f'{_label(e)}: identificador com espaço ou caractere '
                                'inválido; será ajustado na exportação.', e.uid)
        # o EPANET exige IDs únicos por categoria (nós, ligações, curvas, padrões)
        key = (e.COLLECTION, e.name)
        if key in seen:
            err('ID_DUPLICADO', f'Identificador duplicado: {_label(e)}.', e.uid)
        else:
            seen[key] = e.uid

    if not net.nodes:
        err('REDE_VAZIA', 'A rede não possui nós.')
        return issues
    if not any(n.KIND in ('reservoir', 'tank') for n in net.nodes.values()):
        err('SEM_FONTE', 'A rede não possui reservatório nem tanque (fonte de carga).')
    if not any(n.KIND == 'junction' for n in net.nodes.values()):
        warn('SEM_JUNCAO', 'A rede não possui junções.')

    # --- nós -----------------------------------------------------------------
    for n in net.nodes.values():
        if n.KIND == 'junction':
            if n.elevation is None:
                err('COTA_AUSENTE', f'{_label(n)}: cota ausente.', n.uid)
            if n.base_demand < 0:
                warn('DEMANDA_NEG', f'{_label(n)}: demanda-base negativa (injeção).', n.uid)
            if n.demand_pattern and n.demand_pattern not in net.patterns:
                err('PADRAO_INEXISTENTE', f'{_label(n)}: padrão de demanda inexistente.', n.uid)
            for cat in n.demand_categories:
                if cat.get('pattern') and cat['pattern'] not in net.patterns:
                    err('PADRAO_INEXISTENTE',
                        f'{_label(n)}: categoria de demanda com padrão inexistente.', n.uid)
        elif n.KIND == 'reservoir':
            if n.head is None:
                err('CARGA_AUSENTE', f'{_label(n)}: carga hidráulica ausente.', n.uid)
            if n.head_pattern and n.head_pattern not in net.patterns:
                err('PADRAO_INEXISTENTE', f'{_label(n)}: padrão de carga inexistente.', n.uid)
        elif n.KIND == 'tank':
            if n.elevation is None:
                err('COTA_AUSENTE', f'{_label(n)}: cota do fundo ausente.', n.uid)
            if not (n.min_level <= n.init_level <= n.max_level):
                err('TANQUE_NIVEIS', f'{_label(n)}: exige nível mínimo ≤ inicial ≤ máximo.',
                    n.uid)
            if n.volume_curve:
                if n.volume_curve not in net.curves:
                    err('CURVA_INEXISTENTE', f'{_label(n)}: curva de volume inexistente.', n.uid)
            elif n.diameter <= 0:
                err('TANQUE_DIAM', f'{_label(n)}: diâmetro do tanque deve ser > 0.', n.uid)

    # --- ligações ------------------------------------------------------------
    for l in net.links.values():
        if l.start not in net.nodes or l.end not in net.nodes:
            err('LIGACAO_SEM_NO', f'{_label(l)}: nó inicial ou final inexistente.', l.uid)
            continue
        if l.start == l.end:
            err('LIGACAO_LACO', f'{_label(l)}: nó inicial igual ao final.', l.uid)
        if l.KIND == 'pipe':
            if not l.diameter or l.diameter <= 0:
                err('DIAMETRO_INVALIDO', f'{_label(l)}: diâmetro inválido.', l.uid)
            L = net.hydraulic_length(l)
            if not L or L <= 0:
                err('COMPRIMENTO_INVALIDO', f'{_label(l)}: comprimento nulo ou inválido.',
                    l.uid)
            elif not l.auto_length:
                g = net.geometric_length(l)
                if g > 0 and abs(L - g) / g > 0.5:
                    warn('COMPRIMENTO_DIVERGENTE',
                         f'{_label(l)}: comprimento hidráulico ({L:.2f} m) difere muito do '
                         f'geométrico ({g:.2f} m).', l.uid)
            if l.roughness is None or l.roughness <= 0:
                err('RUGOSIDADE_INVALIDA', f'{_label(l)}: rugosidade inválida.', l.uid)
            if l.status not in ('Open', 'Closed', 'CV'):
                err('STATUS_INVALIDO', f'{_label(l)}: estado inválido.', l.uid)
            if l.status == 'Closed':
                warn('TUBO_FECHADO', f'{_label(l)}: tubulação fechada.', l.uid)
            if l.existing and l.diameter and not any(
                    abs(c[1] * 1000.0 - l.diameter) < 0.5
                    for c in project.opt_settings.catalogo_completo):
                warn('EXISTENTE_FORA_CATALOGO',
                     f'{_label(l)}: trecho existente com diâmetro {l.diameter:g} mm fora do '
                     'catálogo de candidatos (será mantido como está na otimização).', l.uid)
        elif l.KIND == 'pump':
            if l.curve:
                c = net.curves.get(l.curve)
                if c is None:
                    err('CURVA_INEXISTENTE', f'{_label(l)}: curva característica inexistente.',
                        l.uid)
                elif c.curve_type != 'PUMP':
                    err('CURVA_TIPO', f'{_label(l)}: a curva associada não é do tipo PUMP.',
                        l.uid)
                elif len(c.points) not in (1, 3) and len(c.points) < 4:
                    err('CURVA_INCOMPLETA', f'{_label(l)}: curva de bomba precisa de 1, 3 ou '
                                            'mais pontos.', l.uid)
            elif not l.power or l.power <= 0:
                err('BOMBA_SEM_CURVA', f'{_label(l)}: informe curva característica ou potência.',
                    l.uid)
            if l.pattern and l.pattern not in net.patterns:
                err('PADRAO_INEXISTENTE', f'{_label(l)}: padrão de velocidade inexistente.',
                    l.uid)
            if l.speed is None or l.speed < 0:
                err('VELOC_RELATIVA', f'{_label(l)}: velocidade relativa inválida.', l.uid)
        elif l.KIND == 'valve':
            if l.valve_type not in ('PRV', 'PSV', 'PBV', 'FCV', 'TCV', 'GPV'):
                err('VALVULA_TIPO', f'{_label(l)}: tipo de válvula inválido.', l.uid)
            if not l.diameter or l.diameter <= 0:
                err('DIAMETRO_INVALIDO', f'{_label(l)}: diâmetro inválido.', l.uid)
            if l.valve_type == 'GPV':
                if l.headloss_curve not in net.curves:
                    err('CURVA_INEXISTENTE', f'{_label(l)}: GPV exige curva de perda.', l.uid)
            elif l.setting is None or l.setting < 0:
                err('VALVULA_AJUSTE', f'{_label(l)}: ajuste (setting) inválido.', l.uid)
            for nid in (l.start, l.end):
                if net.nodes[nid].KIND in ('reservoir', 'tank') and l.valve_type in (
                        'PRV', 'PSV'):
                    err('VALVULA_FONTE', f'{_label(l)}: PRV/PSV não pode ligar-se diretamente '
                                         'a reservatório ou tanque (regra do EPANET).', l.uid)

    # --- curvas, padrões, controles -------------------------------------------
    for c in net.curves.values():
        if not c.points:
            err('CURVA_VAZIA', f'{_label(c)}: curva sem pontos.', c.uid)
        xs = [p[0] for p in c.points]
        if xs != sorted(xs):
            err('CURVA_ORDEM', f'{_label(c)}: valores de X devem ser crescentes.', c.uid)
    for p in net.patterns.values():
        if not p.multipliers:
            err('PADRAO_VAZIO', f'{_label(p)}: padrão sem multiplicadores.', p.uid)
    for c in net.controls.values():
        if c.link not in net.links:
            err('CONTROLE_LIGACAO', f'{_label(c)}: ligação inexistente.', c.uid)
        if c.condition.startswith('IF NODE') and c.node not in net.nodes:
            err('CONTROLE_NO', f'{_label(c)}: nó de condição inexistente.', c.uid)
        if c.action.upper() not in ('OPEN', 'CLOSED'):
            try:
                float(c.action)
            except ValueError:
                err('CONTROLE_ACAO', f'{_label(c)}: ação deve ser OPEN, CLOSED ou número.',
                    c.uid)
    if project.sim_options.default_pattern and \
            project.sim_options.default_pattern not in net.patterns:
        err('PADRAO_INEXISTENTE', 'Padrão padrão das opções de simulação inexistente.')

    # --- conectividade --------------------------------------------------------
    for uid in connectivity.isolated_nodes(net):
        n = net.nodes[uid]
        err('NO_DESCONECTADO', f'{_label(n)}: nó sem nenhuma ligação.', uid)
    isolated = set(connectivity.isolated_nodes(net))
    for uid in connectivity.nodes_without_source(net):
        if uid not in isolated:
            warn('SEM_FONTE_COMPONENTE',
                 f'{_label(net.nodes[uid])}: componente sem reservatório/tanque.', uid)
    for a, b in connectivity.coincident_nodes(net, tol):
        warn('NOS_COINCIDENTES', f"Nós '{net.nodes[a].name}' e '{net.nodes[b].name}' "
                                 f"coincidentes (< {tol} m) sem serem o mesmo nó.", b)
    for nid, lid in connectivity.nodes_on_links_not_connected(net, tol):
        warn('CONEXAO_VISUAL', f"{_label(net.nodes[nid])} toca visualmente "
                               f"{_label(net.links[lid])} sem conexão hidráulica cadastrada.",
             nid)
    return issues


def has_errors(issues: list[Issue]) -> bool:
    return any(i.is_error for i in issues)
