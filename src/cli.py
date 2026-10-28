"""Interface de linha de comando do HidroPy (uso por scripts e agentes, ex.: Claude Code).

    python main.py cli <comando> <arquivo> [opções] [--json]
    HidroPy.exe cli <comando> <arquivo> [opções] [--json]

Com --json o stdout recebe UM objeto JSON (esquema no README, seção "Linha de comando");
mensagens de progresso e avisos vão sempre para o stderr. Códigos de saída: 0 sucesso,
1 falha do cálculo/validação, 2 erro de uso ou de arquivo.

Tudo reutiliza o mesmo caminho da interface gráfica: simulation_adapter /
optimization_adapter (main4.py executado sem alteração), validation, results.tables,
results.reports, cad.dxf_plans e project_io.

Gravação no .shcad: sob trava de arquivo (<arquivo>.lock) o projeto é RELIDO do disco,
a alteração é aplicada e o arquivo é salvo (com <arquivo>.bak). Assim várias otimizações
em paralelo podem gravar cenários no mesmo projeto sem perder dados. Antes de gravar,
confere-se que a rede do cenário no disco é a mesma que foi calculada (hash do .inp).
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import json
import math
import os
import shutil
import sys
import time

CLI_VERSION = 1

EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2


class CliError(Exception):
    def __init__(self, message: str, code: int = EXIT_USAGE):
        super().__init__(message)
        self.code = code


def eprint(*a):
    print(*a, file=sys.stderr, flush=True)


def _clean(v):
    """JSON estrito: NaN/inf viram null; tuplas viram listas."""
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if hasattr(v, 'item') and not isinstance(v, (str, bytes)):   # escalares numpy
        try:
            return _clean(v.item())
        except Exception:
            return str(v)
    return v


def _r(v, nd=3):
    return None if v is None else round(float(v), nd)


# =========================================================================== projeto
class Ctx:
    """Projeto carregado + de onde veio."""

    def __init__(self, project, path, source, warnings):
        self.project = project
        self.path = path                       # arquivo de entrada (absoluto)
        self.source = source                   # 'shcad' | 'inp'
        self.warnings = warnings
        self.original_active = project.active_scenario
        self.original_opt = project.opt_settings


def load_input(path: str, fix_inp: bool = False) -> Ctx:
    from .hydraulics.project import Project
    from .hydraulics.project_io import ProjectFormatError, load_project
    if not path:
        raise CliError('Informe o arquivo do projeto (.shcad) ou da rede (.inp).')
    path = os.path.abspath(path)
    if not os.path.exists(path):
        raise CliError(f'Arquivo não encontrado: {path}')
    ext = os.path.splitext(path)[1].lower()
    if ext == '.shcad':
        try:
            return Ctx(load_project(path), path, 'shcad', [])
        except ProjectFormatError as e:
            raise CliError(f'Projeto inválido: {e}') from e
    if ext == '.inp':
        from .integration.inp_check import InpError, check_inp, prepare
        from .integration.inp_importer import import_inp
        try:
            chk = check_inp(path)
        except InpError as e:
            raise CliError(f'Arquivo .inp inválido: {e}') from e
        if chk.issues and not fix_inp:
            raise CliError('O .inp tem problemas que impedem a leitura (use --corrigir-inp para '
                           'corrigir numa cópia; o original não é alterado):\n' + chk.summary())
        warns_pre = list(chk.warnings)
        if chk.converted:
            warns_pre.append(f'Codificação {chk.encoding_label} convertida para UTF-8.')
        warns_pre += [f'Corrigido (linha {i.line}): {i.message}' for i in chk.issues]
        p = Project()
        try:
            net, warns = import_inp(prepare(chk, apply_fixes=fix_inp), p)
        except Exception as e:
            raise CliError(f'Falha ao ler o .inp: {e}') from e
        warns = warns_pre + list(warns)
        p.network = net
        p.meta['title'] = os.path.splitext(os.path.basename(path))[0]
        p.meta['external_files'] = [path]
        for e in net.elements():
            if e.layer and p.layer_by_name(e.layer) is None:
                p.ensure_layer(e.layer)
        b = net.bounds()
        if b:
            p.display_origin = (round(b[0], -2), round(b[1], -2))
        return Ctx(p, path, 'inp', list(warns))
    raise CliError(f'Extensão não suportada: {ext} (use .shcad ou .inp).')


def find_scenario(project, ref: str):
    for s in project.scenarios:
        if s.uid == ref or s.name == ref:
            return s
    low = ref.strip().lower()
    for s in project.scenarios:
        if s.name.strip().lower() == low:
            return s
    names = ', '.join(f"'{s.name}'" for s in project.scenarios)
    raise CliError(f"Cenário '{ref}' não encontrado. Cenários: {names}.")


def select_scenario(ctx: Ctx, ref: str | None):
    if ref:
        ctx.project.switch_scenario(find_scenario(ctx.project, ref).uid)
    return ctx.project.scenario()


def network_hash(project) -> str:
    from .integration.input_exporter import network_hash as nh
    return nh(project)


def scenario_hash(project, uid: str) -> str:
    cur = project.active_scenario
    project.switch_scenario(uid)
    try:
        return network_hash(project)
    finally:
        project.switch_scenario(cur)


def is_current(project, result) -> bool:
    return bool(result) and result.get('inp_sha256') == network_hash(project)


def current_result(project, kind):
    r = project.latest_result(kind)
    return r if is_current(project, r) else None


@contextlib.contextmanager
def file_lock(target: str, timeout: float = 300.0):
    lock = target + '.lock'
    t0 = time.time()
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock) > 600:   # trava abandonada
                    os.remove(lock)
                    continue
            except OSError:
                continue
            if time.time() - t0 > timeout:
                raise CliError(f'Arquivo travado por outro processo: {lock}', EXIT_FAIL)
            time.sleep(0.2)
    try:
        yield
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass


def target_path(ctx: Ctx, saida: str | None) -> str:
    if saida:
        t = os.path.abspath(saida)
        if not t.lower().endswith('.shcad'):
            raise CliError('--saida do projeto deve terminar em .shcad.')
        return t
    if ctx.source == 'shcad':
        return ctx.path
    t = os.path.splitext(ctx.path)[0] + '.shcad'
    if os.path.exists(t):
        raise CliError(f'Já existe {t}. Como a entrada é .inp, informe --saida (ou converta '
                       'uma vez com "importar" e passe a usar o .shcad).')
    return t


def precheck_target(ctx: Ctx, saida: str | None) -> str:
    """Confere ANTES do cálculo se será possível gravar no destino."""
    target = target_path(ctx, saida)
    if ctx.source == 'inp' and os.path.exists(target):
        raise CliError(f'{target} já existe e a entrada é um .inp (os identificadores internos '
                       'não correspondem). Use o próprio .shcad como entrada. Nada foi gravado.',
                       EXIT_FAIL)
    return target


def commit(ctx: Ctx, saida: str | None, mutate, backup_copy: bool = False) -> dict:
    """Relê o projeto do disco (sob trava), aplica `mutate(projeto)` e salva.

    Se o arquivo de destino ainda não existe, grava o projeto em memória (restaurando o
    cenário ativo e a configuração de otimização originais)."""
    from .hydraulics.project_io import load_project, save_project
    target = precheck_target(ctx, saida)
    info = {'arquivo': target, 'backup': None}
    with file_lock(target):
        if os.path.exists(target):
            fresh = load_project(target)
        else:
            fresh = ctx.project
            fresh.switch_scenario(ctx.original_active)
            fresh.opt_settings = ctx.original_opt
        extra = mutate(fresh) or {}
        if backup_copy and os.path.exists(target):
            stamp = _dt.datetime.now().strftime('%Y%m%d_%H%M%S')
            bak = f'{os.path.splitext(target)[0]}.{stamp}.bak'
            shutil.copy2(target, bak)
            info['backup'] = bak
        save_project(fresh, target, backup=True)
        if info['backup'] is None and os.path.exists(target + '.bak'):
            info['backup'] = target + '.bak'
    info.update(extra)
    return info


def check_scenario_unchanged(fresh, scen_uid: str, expected_sha: str):
    try:
        fresh.scenario(scen_uid)
    except KeyError:
        raise CliError('O cenário calculado não existe mais no arquivo (o projeto foi '
                       'alterado por outro processo). Nada foi gravado.', EXIT_FAIL)
    if scenario_hash(fresh, scen_uid) != expected_sha:
        raise CliError('A rede do cenário no arquivo mudou desde o cálculo (editada na '
                       'interface ou por outro processo). Nada foi gravado; calcule de novo.',
                       EXIT_FAIL)


def store_result(fresh, result: dict, keep_last: int = 5):
    s = fresh.scenario(result['scenario'])
    s.results.append(result)
    same = [r for r in s.results if r.get('kind') == result.get('kind')]
    for old in same[:-keep_last]:
        s.results.remove(old)


# =========================================================================== resumos
def _limited(names, limit):
    names = sorted(names)
    return {'n': len(names), 'ids': names[:limit], 'truncado': len(names) > limit}


def sim_summary(project, res: dict, limit: int = 50) -> dict:
    from .results import thematic_views as TV
    net, o = project.network, project.sim_options
    out = {'status': res.get('status'), 'erro': res.get('error') or None,
           'resultado_uid': res.get('uid'), 'motor': res.get('engine'),
           'criado': res.get('created'), 'workdir': res.get('workdir')}
    if res.get('status') != 'ok':
        out['traceback'] = (res.get('traceback') or '')[-3000:] or None
        out['relatorio_epanet'] = (res.get('report') or '')[-3000:] or None
        return out
    pmin = pmax = vmax = None
    for uid, d in res.get('nodes', {}).items():
        n = net.nodes.get(uid)
        if n is None or n.KIND != 'junction':
            continue
        vals = [v for v in (d.get('pressure') or []) if v is not None]
        if not vals:
            continue
        if pmin is None or min(vals) < pmin[0]:
            pmin = (min(vals), n.name)
        if pmax is None or max(vals) > pmax[0]:
            pmax = (max(vals), n.name)
    for uid, d in res.get('links', {}).items():
        l = net.links.get(uid)
        if l is None or l.KIND != 'pipe':
            continue
        vals = [abs(v) for v in (d.get('velocity') or []) if v is not None]
        if vals and (vmax is None or max(vals) > vmax[0]):
            vmax = (max(vals), l.name)
    v = TV.violations(project, res)
    name = lambda u: (net.nodes.get(u) or net.links.get(u)).name   # noqa: E731
    fora = {key: _limited([name(u) for u in v[k]], limit) for key, k in (
        ('pressao_baixa', 'p_low'), ('pressao_alta', 'p_high'),
        ('velocidade_alta', 'v_high'), ('velocidade_baixa', 'v_low'),
        ('inversao_fluxo', 'reverse'))}
    times = res.get('times') or [0]
    out.update({
        'instantes': len(times), 'duracao_h': _r(times[-1] / 3600.0, 4),
        'pressao_min': {'valor': _r(pmin[0]), 'no': pmin[1]} if pmin else None,
        'pressao_max': {'valor': _r(pmax[0]), 'no': pmax[1]} if pmax else None,
        'velocidade_max': {'valor': _r(vmax[0]), 'trecho': vmax[1]} if vmax else None,
        'limites': {'pressao_min': o.pressure_min, 'pressao_max': o.pressure_max,
                    'velocidade_min': o.velocity_min, 'velocidade_max': o.velocity_max},
        'fora_dos_limites': fora,
        'atende_limites': not (v['p_low'] or v['p_high'] or v['v_high']),
        'avisos_epanet': (res.get('warnings') or [])[:20],
        'nao_mapeados': res.get('unmapped') or [],
    })
    return out


def opt_summary(project, res: dict, details: bool = False) -> dict:
    from .integration.optimization_adapter import diameter_changes
    out = {'status': res.get('status'), 'erro': res.get('error') or None,
           'resultado_uid': res.get('uid'), 'motor': res.get('engine'),
           'criado': res.get('created'), 'workdir': res.get('workdir'),
           'script_inalterado': res.get('script_unchanged')}
    if res.get('status') != 'ok':
        out['traceback'] = (res.get('traceback') or '')[-3000:] or None
        out['log_final'] = (res.get('log') or '')[-3000:] or None
        return out
    s = res.get('summary', {})
    net = project.network
    changes = diameter_changes(net, res)
    pipes = res.get('pipes', {})
    alter = []
    for uid, d in changes:
        l = net.links[uid]
        alter.append({'id': l.name, 'de_mm': l.diameter, 'para_mm': d,
                      'comprimento_m': _r(net.hydraulic_length(l), 2)})
    cfg = res.get('opt_settings') or {}
    out.update({
        'custo': _r(s.get('custo'), 2), 'custo_original': _r(s.get('custo_original'), 2),
        'viavel': s.get('viavel'), 'violacao': s.get('violacao'),
        'fitness': s.get('fitness'),
        'n_pressao_baixa': s.get('n_p_baixa'), 'n_pressao_alta': s.get('n_p_alta'),
        'n_velocidade_alta': s.get('n_v_alta'), 'n_perda_alta': s.get('n_j_alta'),
        'pressao_min': _r(s.get('p_min')), 'pressao_max': _r(s.get('p_max')),
        'velocidade_max': _r(s.get('v_max')), 'hora_critica': s.get('hora_critica'),
        'faixa_dn': s.get('faixa_dn'), 'avaliacoes_unicas': s.get('avaliacoes_unicas'),
        'trechos_projetados': sum(1 for d in pipes.values() if not d.get('fixed')),
        'trechos_existentes_preservados': sum(1 for d in pipes.values() if d.get('fixed')),
        'trechos_alterados': len(changes),
        'comprimento_alterado_m': _r(sum(a['comprimento_m'] or 0 for a in alter), 2),
        'configuracao': {k: cfg.get(k) for k in (
            'semente', 'tam_populacao', 'num_geracoes', 'pressao_min', 'pressao_max',
            'velocidade_max', 'dn_min_permitido', 'dn_max_permitido', 'margem_dn_acima')}
        if cfg else None,
    })
    if details:
        out['alteracoes'] = alter
    return out


def catalog_cost_per_m(project, diameter_mm):
    for dn, d_m, c in project.opt_settings.catalogo_completo:
        if abs(d_m * 1000.0 - diameter_mm) < 0.6:
            return c
    return None


def network_costs(project) -> dict:
    net = project.network
    proj = tot = 0.0
    missing = []
    for l in net.links.values():
        if l.KIND != 'pipe':
            continue
        c = catalog_cost_per_m(project, l.diameter)
        if c is None:
            missing.append(l.name)
            continue
        val = c * net.hydraulic_length(l)
        tot += val
        if not l.existing:
            proj += val
    return {'custo_projetado': _r(proj, 2), 'custo_total': _r(tot, 2),
            'fora_do_catalogo': _limited(missing, 20)}


# =========================================================================== progresso
def progress_printer(label: str, verbose: bool, every: float = 15.0):
    state = {'t': time.time(), 'last': ''}

    def on_output(line: str):
        if verbose:
            eprint(line)
            return
        if line.strip():
            state['last'] = line.strip()
        if time.time() - state['t'] >= every and state['last']:
            eprint(f'[{label}] {state["last"][:160]}')
            state['t'] = time.time()
    return on_output


def validation_gate(project, ignore: bool):
    from .hydraulics.validation import validate
    issues = validate(project)
    errs = [i for i in issues if i.is_error]
    if errs and not ignore:
        raise CliError('A rede tem erros de validação (rode "validar"): ' + '; '.join(
            f'{i.code}: {i.message}' for i in errs[:10]), EXIT_FAIL)
    return issues


# =========================================================================== comandos
def cmd_info(ctx: Ctx, a) -> tuple[dict, int]:
    p = ctx.project
    select_scenario(ctx, a.cenario)
    net = p.network
    counts = net.counts()
    pipes = [l for l in net.links.values() if l.KIND == 'pipe']
    diam: dict = {}
    for l in pipes:
        diam[f'{l.diameter:g}'] = diam.get(f'{l.diameter:g}', 0) + 1
    scen = []
    for s in p.scenarios:
        h = scenario_hash(p, s.uid)
        def last(kind):
            rs = [r for r in s.results if r.get('kind') == kind and r.get('status') == 'ok']
            if not rs:
                return None
            r = rs[-1]
            d = {'uid': r.get('uid'), 'criado': r.get('created'),
                 'atual': r.get('inp_sha256') == h}
            if kind == 'optimization':
                sm = r.get('summary', {})
                d.update({'custo': _r(sm.get('custo'), 2), 'viavel': sm.get('viavel')})
            return d
        scen.append({'uid': s.uid, 'nome': s.name, 'ativo': s.uid == p.active_scenario,
                     'descricao': s.description, 'criado': s.created, 'pai': s.parent or None,
                     'ultima_simulacao': last('simulation'),
                     'ultima_otimizacao': last('optimization')})
    st = p.population_study()
    pop = None
    if st is not None:
        try:
            dp = st.design_population
        except Exception:
            dp = None
        pop = {'nome': st.name, 'metodo': st.adopted_method, 'ano_final': st.end_year,
               'populacao_projeto': _r(dp, 0)}
    opt = p.opt_settings.to_dict()
    return {
        'tipo': ctx.source, 'titulo': p.meta.get('title', ''),
        'cenario': {'uid': p.active_scenario, 'nome': p.scenario().name},
        'cenarios': scen,
        'rede': {
            'juncoes': counts.get('junction', 0), 'reservatorios': counts.get('reservoir', 0),
            'tanques': counts.get('tank', 0), 'tubulacoes': counts.get('pipe', 0),
            'bombas': counts.get('pump', 0), 'valvulas': counts.get('valve', 0),
            'trechos_existentes': sum(1 for l in pipes if l.existing),
            'comprimento_total_m': _r(sum(net.hydraulic_length(l) for l in pipes), 2),
            'comprimento_existente_m': _r(sum(net.hydraulic_length(l) for l in pipes
                                              if l.existing), 2),
            'demanda_base_total_lps': _r(sum(n.base_demand for n in net.nodes.values()
                                             if n.KIND == 'junction'), 4),
            'diametros_mm': dict(sorted(diam.items(), key=lambda kv: float(kv[0]))),
        },
        'custos_catalogo': network_costs(p),
        'opcoes_simulacao': p.sim_options.to_dict(),
        'opcoes_otimizacao': opt,
        'populacao': pop,
        'avisos_importacao': ctx.warnings,
    }, EXIT_OK


def cmd_validar(ctx: Ctx, a) -> tuple[dict, int]:
    from .hydraulics.validation import validate
    p = ctx.project
    select_scenario(ctx, a.cenario)
    issues = validate(p)
    by: dict = {}
    for i in issues:
        e = by.setdefault(i.code, {'severidade': i.severity, 'n': 0})
        e['n'] += 1
    lst = []
    for i in issues[:a.max]:
        el = p.get(i.uid) if i.uid else None
        lst.append({'severidade': i.severity, 'codigo': i.code, 'mensagem': i.message,
                    'elemento': el.name if el is not None else None})
    n_err = sum(1 for i in issues if i.is_error)
    return {'cenario': p.scenario().name, 'valido': n_err == 0, 'erros': n_err,
            'advertencias': len(issues) - n_err, 'por_codigo': by, 'problemas': lst,
            'truncado': len(issues) > a.max}, (EXIT_OK if n_err == 0 else EXIT_FAIL)


def cmd_simular(ctx: Ctx, a) -> tuple[dict, int]:
    from .integration import simulation_adapter
    p = ctx.project
    scen = select_scenario(ctx, a.cenario)
    validation_gate(p, a.ignorar_validacao)
    if a.gravar:
        precheck_target(ctx, a.saida)
    eprint(f"Simulando o cenário '{scen.name}'…")
    t0 = time.time()
    res = simulation_adapter.run_blocking(p, a.timeout, progress_printer('simulação', a.verbose))
    out = {'cenario': scen.name, 'duracao_s': _r(time.time() - t0, 1)}
    out.update(sim_summary(p, res, a.max))
    out['gravado'] = None
    if res['status'] == 'ok' and a.gravar:
        def mutate(fresh):
            check_scenario_unchanged(fresh, res['scenario'], res['inp_sha256'])
            store_result(fresh, res)
        out['gravado'] = commit(ctx, a.saida, mutate)
        eprint(f"Resultado gravado em {out['gravado']['arquivo']}")
    return out, (EXIT_OK if res['status'] == 'ok' else EXIT_FAIL)


OPT_OVERRIDES = [
    # (opção, campo de OptimizationSettings, tipo, ajuda)
    ('geracoes', 'num_geracoes', int, 'NUM_GERACOES'),
    ('populacao', 'tam_populacao', int, 'TAM_POPULACAO'),
    ('semente', 'semente', int, 'SEMENTE'),
    ('pressao_min', 'pressao_min', float, 'PRESSAO_MIN (mca)'),
    ('pressao_max', 'pressao_max', float, 'PRESSAO_MAX (mca)'),
    ('pressao_min_absoluta', 'pressao_min_absoluta', float, 'PRESSAO_MIN_ABSOLUTA (mca)'),
    ('tolerancia_pressao', 'tolerancia_pressao', float, 'TOLERANCIA_PRESSAO (mca)'),
    ('vel_max', 'velocidade_max', float, 'VELOCIDADE_MAX (m/s)'),
    ('dn_min', 'dn_min_permitido', float, 'DN_MIN_PERMITIDO (DN mm; padrão automático)'),
    ('dn_max', 'dn_max_permitido', float, 'DN_MAX_PERMITIDO (DN mm; padrão automático)'),
    ('margem_dn', 'margem_dn_acima', int, 'MARGEM_DN_ACIMA (degraus de catálogo)'),
    ('prob_cruzamento', 'prob_cruzamento', float, 'PROB_CRUZAMENTO'),
    ('prob_mutacao', 'prob_mutacao', float, 'PROB_MUTACAO'),
    ('torneio', 'tam_torneio', int, 'TAM_TORNEIO'),
    ('parada_sem_melhora', 'parada_sem_melhora', int, 'PARADA_SEM_MELHORA (gerações)'),
    ('perda_max', 'perda_carga_max', float,
     'PERDA_CARGA_MAX (m/km); liga APLICAR_LIMITE_PERDA_UNITARIA'),
]


def load_catalog(path: str) -> list:
    """Catálogo JSON: [[DN, diâmetro_m, R$/m], ...] ou
    [{"dn": 100, "diametro_mm"|"diametro_m": ..., "custo": 62.0}, ...]."""
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise CliError(f'Catálogo ilegível ({path}): {e}') from e
    if isinstance(data, dict):
        data = data.get('catalogo') or data.get('catalog') or []
    out = []
    for row in data:
        if isinstance(row, dict):
            dn = row.get('dn')
            d_m = row.get('diametro_m')
            if d_m is None and row.get('diametro_mm') is not None:
                d_m = float(row['diametro_mm']) / 1000.0
            if d_m is None and dn is not None:
                d_m = float(dn) / 1000.0
            cost = row.get('custo', row.get('custo_m'))
        else:
            dn, d_m, cost = (list(row) + [None, None, None])[:3]
        if dn is None or d_m is None or cost is None:
            raise CliError(f'Linha de catálogo incompleta: {row}')
        out.append([int(dn) if float(dn).is_integer() else float(dn), float(d_m),
                    float(cost)])
    if len(out) < 2:
        raise CliError('O catálogo precisa de pelo menos 2 diâmetros.')
    out.sort(key=lambda r: r[1])
    return out


def apply_overrides(project, a) -> list[str]:
    import copy
    s = copy.deepcopy(project.opt_settings)
    changed = []
    for opt, attr, _typ, _h in OPT_OVERRIDES:
        v = getattr(a, opt)
        if v is not None:
            setattr(s, attr, v)
            changed.append(attr)
    if a.perda_max is not None:
        s.aplicar_limite_perda_unitaria = True
        changed.append('aplicar_limite_perda_unitaria')
    if a.catalogo:
        s.catalogo_completo = load_catalog(a.catalogo)
        changed.append('catalogo_completo')
    if s.num_geracoes < 1 or s.tam_populacao < 2:
        raise CliError('Use --geracoes ≥ 1 e --populacao ≥ 2.')
    if s.dn_min_permitido is not None and s.dn_max_permitido is not None \
            and s.dn_min_permitido > s.dn_max_permitido:
        raise CliError('--dn-min maior que --dn-max.')
    if s.pressao_min >= s.pressao_max:
        raise CliError('--pressao-min deve ser menor que --pressao-max.')
    project.opt_settings = s
    return changed


def cmd_otimizar(ctx: Ctx, a) -> tuple[dict, int]:
    from .integration import optimization_adapter as OA
    p = ctx.project
    scen = select_scenario(ctx, a.cenario)
    changed = apply_overrides(p, a)
    validation_gate(p, a.ignorar_validacao)
    if a.criar_cenario or a.gravar:
        precheck_target(ctx, a.saida)
        if a.criar_cenario and not a.substituir and os.path.exists(
                target_path(ctx, a.saida)) and any(
                x.name.strip().lower() == a.criar_cenario.strip().lower()
                for x in p.scenarios):
            raise CliError(f"Já existe o cenário '{a.criar_cenario.strip()}' (use --substituir "
                           'ou outro nome). Nada foi calculado.', EXIT_FAIL)
    s = p.opt_settings
    eprint(f"Otimizando o cenário '{scen.name}' (main4.py): {s.num_geracoes} gerações × "
           f"{s.tam_populacao} indivíduos, semente {s.semente}…")
    t0 = time.time()
    try:
        res = OA.run_blocking(p, a.timeout, progress_printer('otimização', a.verbose))
    except FileNotFoundError as e:
        raise CliError(str(e), EXIT_FAIL) from e
    res['opt_settings'] = s.to_dict()       # configuração usada (fica no histórico)
    out = {'cenario': scen.name, 'duracao_s': _r(time.time() - t0, 1),
           'parametros_alterados': changed}
    out.update(opt_summary(p, res, a.detalhes))
    out['gravado'] = None
    out['cenario_criado'] = None
    if res['status'] == 'ok' and a.criar_cenario:
        name = a.criar_cenario.strip()
        if not name:
            raise CliError('Nome de cenário vazio.')

        def mutate(fresh):
            check_scenario_unchanged(fresh, res['scenario'], res['inp_sha256'])
            same = [x for x in fresh.scenarios if x.name.strip().lower() == name.lower()]
            if same:
                if not a.substituir:
                    raise CliError(f"Já existe o cenário '{name}' (use --substituir ou outro "
                                   'nome). Nada foi gravado.', EXIT_FAIL)
                if any(x.uid == fresh.active_scenario for x in same):
                    raise CliError(f"'{name}' é o cenário ativo e não pode ser substituído.",
                                   EXIT_FAIL)
                for x in same:
                    fresh.delete_scenario(x.uid)
            keep = fresh.active_scenario
            fresh.switch_scenario(res['scenario'])
            desc = (f"Diâmetros do main4.py aplicados (CLI: semente {s.semente}, "
                    f"{s.num_geracoes} gerações, custo R$ {res['summary'].get('custo', 0):,.2f}, "
                    f"{'viável' if res['summary'].get('viavel') else 'NÃO viável'})")
            new = OA.create_optimized_scenario(fresh, res, name, desc)
            fresh.switch_scenario(new.uid if a.ativar else keep)
            n_changes = len(OA.diameter_changes(Network_of(fresh, res['scenario']), res))
            return {'cenario_uid': new.uid, 'cenario_nome': new.name, 'ativado': a.ativar,
                    'trechos_alterados': n_changes}
        info = commit(ctx, a.saida, mutate)
        out['cenario_criado'] = info
        eprint(f"Cenário '{name}' gravado em {info['arquivo']}")
    elif res['status'] == 'ok' and a.gravar:
        def mutate(fresh):
            check_scenario_unchanged(fresh, res['scenario'], res['inp_sha256'])
            store_result(fresh, res)
        out['gravado'] = commit(ctx, a.saida, mutate)
    return out, (EXIT_OK if res['status'] == 'ok' else EXIT_FAIL)


def Network_of(project, scen_uid):
    from .hydraulics.network import Network
    if scen_uid == project.active_scenario:
        return project.network
    return Network.from_dict(project.scenario(scen_uid).network)


def cmd_comparar(ctx: Ctx, a) -> tuple[dict, int]:
    from .integration import simulation_adapter
    p = ctx.project
    refs = a.cenarios or [s.uid for s in p.scenarios]
    targets = []
    for r in refs:
        s = find_scenario(p, r)
        if s.uid not in [t.uid for t in targets]:
            targets.append(s)
    ref = find_scenario(p, a.referencia) if a.referencia else p.scenario(ctx.original_active)
    ref_net = Network_of(p, ref.uid)
    rows, new_results = [], []
    for s in targets:
        p.switch_scenario(s.uid)
        net = p.network
        h = network_hash(p)
        sim = p.latest_result('simulation')
        sim = sim if sim and sim.get('inp_sha256') == h else None
        simulated_now = False
        if sim is None and a.simular:
            eprint(f"Simulando '{s.name}'…")
            res = simulation_adapter.run_blocking(p, a.timeout,
                                                  progress_printer('simulação', a.verbose))
            if res['status'] == 'ok':
                sim, simulated_now = res, True
                new_results.append(res)
            else:
                eprint(f"Falha na simulação de '{s.name}': {res.get('error')}")
        opt = p.latest_result('optimization')
        diff = sum(1 for uid, l in net.links.items() if l.KIND == 'pipe'
                   and uid in ref_net.links
                   and abs(getattr(ref_net.links[uid], 'diameter', 0) - l.diameter) > 1e-9)
        row = {'uid': s.uid, 'nome': s.name, 'ativo': s.uid == ctx.original_active,
               'descricao': s.description,
               'trechos_diferentes_da_referencia': diff}
        row.update(network_costs(p))
        if sim:
            ss = sim_summary(p, sim, a.max)
            row['simulacao'] = {
                'resultado_uid': sim['uid'], 'simulado_agora': simulated_now,
                'pressao_min': ss['pressao_min'], 'pressao_max': ss['pressao_max'],
                'velocidade_max': ss['velocidade_max'],
                'n_pressao_baixa': ss['fora_dos_limites']['pressao_baixa']['n'],
                'n_pressao_alta': ss['fora_dos_limites']['pressao_alta']['n'],
                'n_velocidade_alta': ss['fora_dos_limites']['velocidade_alta']['n'],
                'atende_limites': ss['atende_limites']}
        else:
            row['simulacao'] = None
        if opt:
            sm = opt.get('summary', {})
            row['otimizacao'] = {'resultado_uid': opt['uid'], 'custo': _r(sm.get('custo'), 2),
                                 'viavel': sm.get('viavel'), 'violacao': sm.get('violacao'),
                                 'atual': opt.get('inp_sha256') == h}
        else:
            row['otimizacao'] = None
        rows.append(row)
    p.switch_scenario(ctx.original_active)
    ok_rows = [r for r in rows if r['simulacao'] and r['simulacao']['atende_limites']
               and r['custo_projetado'] is not None and not r['fora_do_catalogo']['n']]
    best = min(ok_rows, key=lambda r: r['custo_projetado']) if ok_rows else None
    out = {'referencia': ref.name, 'limites': {
        'pressao_min': p.sim_options.pressure_min, 'pressao_max': p.sim_options.pressure_max,
        'velocidade_max': p.sim_options.velocity_max},
        'cenarios': rows,
        'melhor': {'nome': best['nome'], 'uid': best['uid'],
                   'custo_projetado': best['custo_projetado']} if best else None,
        'gravado': None}
    if new_results and a.gravar:
        def mutate(fresh):
            for r in new_results:
                check_scenario_unchanged(fresh, r['scenario'], r['inp_sha256'])
                store_result(fresh, r)
        out['gravado'] = commit(ctx, a.saida, mutate)
    return out, EXIT_OK


def cmd_aplicar(ctx: Ctx, a) -> tuple[dict, int]:
    from .integration import optimization_adapter as OA
    p = ctx.project
    scen = select_scenario(ctx, a.cenario)
    if a.resultado:          # procura em todos os cenários
        pool = [r for s in p.scenarios for r in s.results]
        where = 'no projeto'
    else:
        src = find_scenario(p, a.de_cenario) if a.de_cenario else scen
        pool = src.results if src.uid != p.active_scenario else p.results()
        where = f"no cenário '{src.name}'"
    opts = [r for r in pool if r.get('kind') == 'optimization' and r.get('status') == 'ok'
            and (not a.resultado or r.get('uid') == a.resultado)]
    if not opts:
        raise CliError(f"Nenhuma otimização bem-sucedida {'com esse uid ' if a.resultado else ''}"
                       f"{where}.", EXIT_FAIL)
    res = opts[-1]
    current = is_current(p, res)
    if not current and not a.forcar:
        raise CliError('A rede mudou desde esta otimização (resultado desatualizado). Rode a '
                       'otimização de novo ou use --forcar.', EXIT_FAIL)
    changes = OA.diameter_changes(p.network, res)
    scen_uid, sha = scen.uid, network_hash(p)

    def mutate(fresh):
        check_scenario_unchanged(fresh, scen_uid, sha)
        keep = fresh.active_scenario
        fresh.switch_scenario(scen_uid)
        items = OA.diameter_changes(fresh.network, res)
        for uid, d in items:
            fresh.network.links[uid].diameter = d
        fresh.switch_scenario(keep)
        return {'trechos_alterados': len(items)}
    info = commit(ctx, a.saida, mutate, backup_copy=True)
    net = p.network
    return {'cenario': scen.name, 'resultado_uid': res['uid'], 'resultado_atual': current,
            'custo': _r(res.get('summary', {}).get('custo'), 2),
            'alteracoes': [{'id': net.links[u].name, 'de_mm': net.links[u].diameter,
                            'para_mm': d} for u, d in changes] if a.detalhes else None,
            'gravado': info, 'trechos_alterados': info['trechos_alterados']}, EXIT_OK


def cmd_ativar(ctx: Ctx, a) -> tuple[dict, int]:
    if ctx.source != 'shcad':
        raise CliError('"ativar-cenario" exige um projeto .shcad.')
    if not a.cenario:
        raise CliError('Informe --cenario NOME.')
    uid = find_scenario(ctx.project, a.cenario).uid

    def mutate(fresh):
        fresh.switch_scenario(find_scenario(fresh, uid).uid)
    info = commit(ctx, a.saida, mutate)
    return {'cenario': find_scenario(ctx.project, uid).name, 'cenario_uid': uid,
            'gravado': info}, EXIT_OK


def _sim_for_export(ctx, a):
    from .integration import simulation_adapter
    p = ctx.project
    sim = current_result(p, 'simulation')
    if sim is None and getattr(a, 'simular', False):
        eprint('Simulando para obter resultados…')
        res = simulation_adapter.run_blocking(p, a.timeout,
                                              progress_printer('simulação', a.verbose))
        if res['status'] != 'ok':
            raise CliError(f"Falha na simulação: {res.get('error')}", EXIT_FAIL)
        sim = res
    return sim


def _out_path(a, exts):
    if not a.saida:
        raise CliError(f'Informe --saida ({" ou ".join(exts)}).')
    path = os.path.abspath(a.saida)
    if os.path.splitext(path)[1].lower() not in exts:
        raise CliError(f'--saida deve terminar em {" ou ".join(exts)}.')
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    return path


def cmd_exportar_dxf(ctx: Ctx, a) -> tuple[dict, int]:
    from .cad import dxf_plans as DP
    from .cad import fittings as F
    p = ctx.project
    scen = select_scenario(ctx, a.cenario)
    path = _out_path(a, ['.dxf'])
    st = p.settings
    h = a.altura_texto or st.dxf_text_height
    include_cad = not a.sem_cad and st.dxf_include_cad
    out = {'cenario': scen.name, 'saida': path, 'planta': a.planta}
    if a.planta == 'execucao':
        fo = F.FittingOptions(tolerance=st.fit_tolerance, curve_ends=st.fit_curve_ends,
                              vertex_bends=st.fit_vertex_bends, caps=st.fit_caps,
                              min_segment=st.fit_min_segment)
        lib = st.fittings_library
        if lib and not os.path.exists(lib):
            raise CliError(f'Biblioteca de conexões não encontrada: {lib}', EXIT_FAIL)
        opts = DP.ExecOptions(text_height=h, include_cad=include_cad,
                              pipe_labels=st.fit_pipe_labels, callouts=st.fit_callouts,
                              callout_style=st.fit_callout_style, table=st.fit_table,
                              library=lib, fittings=fo)
        _, points = DP.export_exec_plan(p, path, opts)
        q = F.quantities(points)
        out.update({'pecas': sum(q.values()), 'quantidades': q,
                    'pontos_com_pecas': sum(1 for fp in points if fp.pieces),
                    'pontos_com_observacoes': sum(1 for fp in points if fp.warnings)})
    else:
        sim = _sim_for_export(ctx, a)
        link_fields = list(st.dxf_calc_link_fields)
        node_fields = list(st.dxf_calc_node_fields)
        opts = DP.CalcOptions(text_height=h, include_cad=include_cad, link_fields=link_fields,
                              node_fields=node_fields, arrows=st.dxf_calc_arrows,
                              time_index=a.instante)
        DP.export_calc_plan(p, path, opts, sim)
        out.update({'resultados_usados': sim['uid'] if sim else None,
                    'campos_trechos': link_fields, 'campos_nos': node_fields})
        if sim is None:
            out['aviso'] = ('Sem simulação atual do cenário: a planta saiu sem resultados '
                            '(use --simular).')
    return out, EXIT_OK


def cmd_planilha(ctx: Ctx, a) -> tuple[dict, int]:
    from .results import tables
    p = ctx.project
    scen = select_scenario(ctx, a.cenario)
    path = _out_path(a, ['.xlsx', '.csv'])
    if a.tipo == 'resultados':
        sim = _sim_for_export(ctx, a)
        if sim is None:
            raise CliError('Sem simulação atual do cenário (use --simular).', EXIT_FAIL)
        dfs = {'Nos': tables.node_results_df(p, sim, a.instante, a.todos_instantes),
               'Trechos': tables.link_results_df(p, sim, a.instante, a.todos_instantes)}
    elif a.tipo == 'otimizacao':
        opt = p.latest_result('optimization')
        if opt is None:
            raise CliError(f"Nenhuma otimização no cenário '{scen.name}'.", EXIT_FAIL)
        dfs = {'Trechos': tables.optimization_df(p, opt),
               'Nos': tables.optimization_nodes_df(p, opt)}
    elif a.tipo == 'existentes':
        dfs = {'Existentes': tables.existing_pipes_df(p)}
    else:
        dfs = {}
        for kind, title in (('junction', 'Juncoes'), ('reservoir', 'Reservatorios'),
                            ('tank', 'Tanques'), ('pipe', 'Tubulacoes'), ('pump', 'Bombas'),
                            ('valve', 'Valvulas')):
            df = tables.elements_df(p, kind)
            if not df.empty:
                dfs[title] = df
    files = tables.export_many(dfs, path)
    return {'cenario': scen.name, 'tipo': a.tipo, 'arquivos': files,
            'linhas': {k: int(len(v)) for k, v in dfs.items()}}, EXIT_OK


def cmd_relatorio(ctx: Ctx, a) -> tuple[dict, int]:
    from types import SimpleNamespace
    from .results import reports
    p = ctx.project
    scen = select_scenario(ctx, a.cenario)
    path = _out_path(a, ['.html', '.pdf'])
    which = set(reports.REPORTS)
    if a.secoes:
        which = {x.strip() for x in a.secoes.split(',') if x.strip()}
        bad = which - set(reports.REPORTS)
        if bad:
            raise CliError(f'Seções desconhecidas: {sorted(bad)}. Válidas: '
                           f'{sorted(reports.REPORTS)}.')
    html = reports.build_report(SimpleNamespace(project=p), which, a.instante)
    if path.lower().endswith('.pdf'):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtGui import QGuiApplication
        _app = QGuiApplication.instance() or QGuiApplication(['hidropy-cli'])  # noqa: F841
        reports.save_pdf(html, path)
    else:
        reports.save_html(html, path)
    sim, opt = p.latest_result('simulation'), p.latest_result('optimization')
    return {'cenario': scen.name, 'saida': path, 'secoes': sorted(which),
            'simulacao_atual': is_current(p, sim) if sim else None,
            'otimizacao_atual': is_current(p, opt) if opt else None}, EXIT_OK


def cmd_importar(ctx: Ctx, a) -> tuple[dict, int]:
    from .hydraulics.project_io import save_project
    if ctx.source != 'inp':
        raise CliError('"importar" converte um .inp em .shcad.')
    p = ctx.project
    target = os.path.abspath(a.saida) if a.saida else os.path.splitext(ctx.path)[0] + '.shcad'
    if not target.lower().endswith('.shcad'):
        raise CliError('--saida deve terminar em .shcad.')
    if os.path.exists(target) and not a.sobrescrever:
        raise CliError(f'{target} já existe (use --sobrescrever).')
    if a.titulo:
        p.meta['title'] = a.titulo
    with file_lock(target):
        save_project(p, target, backup=True)
    c = p.network.counts()
    return {'saida': target, 'nos': len(p.network.nodes), 'ligacoes': len(p.network.links),
            'tubulacoes': c.get('pipe', 0), 'avisos_importacao': ctx.warnings}, EXIT_OK


COMMANDS = {
    'info': (cmd_info, 'Resumo do projeto/rede: contagens, cenários, opções, população.'),
    'validar': (cmd_validar, 'Validação: erros impeditivos × advertências, com códigos.'),
    'simular': (cmd_simular, 'Simulação EPANET (WNTR) do cenário; --gravar salva no projeto.'),
    'otimizar': (cmd_otimizar, 'Otimização de diâmetros pelo main4.py (DEAP + WNTR).'),
    'comparar': (cmd_comparar, 'Compara cenários: custo pelo catálogo, pressões, velocidades.'),
    'aplicar-otimizacao': (cmd_aplicar, 'Aplica a última otimização ao cenário (backup .bak).'),
    'ativar-cenario': (cmd_ativar, 'Torna ativo (no .shcad) o cenário --cenario NOME.'),
    'exportar-dxf': (cmd_exportar_dxf, 'Planta DXF de cálculo ou de execução.'),
    'planilha': (cmd_planilha, 'Planilha XLSX/CSV de resultados, otimização ou cadastro.'),
    'relatorio': (cmd_relatorio, 'Relatório HTML ou PDF.'),
    'importar': (cmd_importar, 'Converte um .inp em projeto .shcad.'),
}


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CliError(f'{message}\n\n{self.format_usage().strip()}')


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('arquivo', help='projeto .shcad ou rede .inp')
    common.add_argument('--json', action='store_true', help='resumo JSON no stdout')
    common.add_argument('--cenario', help='nome ou uid do cenário (padrão: o ativo)')
    common.add_argument('--timeout', type=float, default=None,
                        help='tempo limite do cálculo em segundos')
    common.add_argument('-v', '--verbose', action='store_true',
                        help='repassa todo o log do cálculo ao stderr')
    common.add_argument('--max', type=int, default=50,
                        help='máximo de itens listados (ids, problemas)')
    common.add_argument('--saida', help='arquivo de saída (.shcad, .dxf, .xlsx/.csv, '
                                        '.html/.pdf conforme o comando)')
    common.add_argument('--corrigir-inp', action='store_true',
                        help='corrige problemas do .inp (palavras traduzidas, vírgula decimal) '
                             'numa cópia antes de ler; o original não é alterado')
    common.add_argument('--ignorar-validacao', action='store_true',
                        help='calcula mesmo com erros de validação')

    ap = _Parser(prog='hidropy cli', description='HidroPy — linha de comando (uso agêntico).')
    sub = ap.add_subparsers(dest='comando', metavar='comando', parser_class=_Parser)
    sp = {}
    for name, (_fn, helptext) in COMMANDS.items():
        sp[name] = sub.add_parser(name, parents=[common], help=helptext, description=helptext)

    sp['simular'].add_argument('--gravar', action='store_true',
                               help='grava o resultado no cenário do .shcad')
    o = sp['otimizar']
    for opt, attr, typ, h in OPT_OVERRIDES:
        o.add_argument('--' + opt.replace('_', '-'), dest=opt, type=typ, default=None, help=h)
    o.add_argument('--catalogo', help='catálogo JSON [[DN, diâmetro_m, R$/m], ...]')
    o.add_argument('--criar-cenario', metavar='NOME',
                   help='grava um cenário com os diâmetros otimizados (existentes intactos)')
    o.add_argument('--substituir', action='store_true',
                   help='substitui cenário (não ativo) de mesmo nome')
    o.add_argument('--ativar', action='store_true', help='torna ativo o cenário criado')
    o.add_argument('--gravar', action='store_true',
                   help='sem --criar-cenario: grava o resultado no cenário otimizado')
    o.add_argument('--detalhes', action='store_true', help='lista os trechos alterados')

    c = sp['comparar']
    c.add_argument('--cenarios', nargs='+', metavar='CENARIO',
                   help='nomes/uids (padrão: todos)')
    c.add_argument('--referencia', help='cenário de referência para contar trechos diferentes')
    c.add_argument('--simular', action='store_true',
                   help='simula os cenários sem simulação atual')
    c.add_argument('--gravar', action='store_true', help='grava as simulações novas')

    ap_ = sp['aplicar-otimizacao']
    ap_.add_argument('--resultado', help='uid do resultado (procura em todos os cenários)')
    ap_.add_argument('--de-cenario', metavar='CENARIO',
                     help='usa a última otimização guardada nesse cenário (ex.: um cenário '
                          'criado por --criar-cenario)')
    ap_.add_argument('--forcar', action='store_true', help='aplica mesmo desatualizado')
    ap_.add_argument('--detalhes', action='store_true', help='lista os trechos alterados')

    d = sp['exportar-dxf']
    d.add_argument('--planta', choices=['calculo', 'execucao'], default='calculo')
    d.add_argument('--altura-texto', type=float, default=None)
    d.add_argument('--sem-cad', action='store_true', help='não inclui a geometria CAD')
    d.add_argument('--instante', type=int, default=0, help='índice do instante (período est.)')
    d.add_argument('--simular', action='store_true',
                   help='simula se não houver resultado atual')

    pl = sp['planilha']
    pl.add_argument('--tipo', choices=['resultados', 'otimizacao', 'cadastro', 'existentes'],
                    default='resultados')
    pl.add_argument('--instante', type=int, default=0)
    pl.add_argument('--todos-instantes', action='store_true')
    pl.add_argument('--simular', action='store_true',
                    help='simula se não houver resultado atual')

    r = sp['relatorio']
    r.add_argument('--secoes', help='lista separada por vírgulas: ' + ','.join(
        ['cadastro', 'resultados', 'otimizacao', 'restricoes', 'validacao', 'populacao']))
    r.add_argument('--instante', type=int, default=0)

    im = sp['importar']
    im.add_argument('--titulo')
    im.add_argument('--sobrescrever', action='store_true')
    return ap


def _human(payload, indent=0) -> str:
    pad = '  ' * indent
    lines = []
    for k, v in payload.items():
        if isinstance(v, dict):
            if not v:
                continue
            lines.append(f'{pad}{k}:')
            lines.append(_human(v, indent + 1))
        elif isinstance(v, list):
            if v and isinstance(v[0], dict):
                lines.append(f'{pad}{k}: ({len(v)})')
                for item in v[:30]:
                    lines.append(pad + '  - ' + ', '.join(
                        f'{a}={b}' for a, b in item.items() if not isinstance(b, (dict, list))))
            else:
                lines.append(f'{pad}{k}: {", ".join(map(str, v[:30]))}'
                             + (' …' if len(v) > 30 else ''))
        elif v is not None:
            lines.append(f'{pad}{k}: {v}')
    return '\n'.join(x for x in lines if x)


def _reconfigure_streams():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    _reconfigure_streams()
    want_json = '--json' in argv
    real_stdout = sys.stdout
    payload = {'cli_versao': CLI_VERSION, 'comando': argv[0] if argv else None, 'ok': False,
               'erro': None}
    code = EXIT_USAGE
    try:
        parser = build_parser()
        if not argv or argv[0] in ('-h', '--help', 'ajuda'):
            parser.print_help(sys.stderr if want_json else sys.stdout)
            return EXIT_OK if argv else EXIT_USAGE
        a = parser.parse_args(argv)
        fn = COMMANDS[a.comando][0]
        # bibliotecas que escrevem no stdout não podem corromper o JSON
        with contextlib.redirect_stdout(sys.stderr):
            ctx = load_input(a.arquivo, getattr(a, 'corrigir_inp', False))
            payload['arquivo'] = ctx.path
            data, code = fn(ctx, a)
        payload.update(data)
        payload['ok'] = code == EXIT_OK
    except CliError as e:
        payload['erro'] = str(e)
        code = e.code
    except KeyboardInterrupt:
        payload['erro'] = 'Interrompido.'
        code = EXIT_FAIL
    except Exception as e:      # falha inesperada: JSON mesmo assim
        import traceback
        payload['erro'] = f'{type(e).__name__}: {e}'
        payload['traceback'] = traceback.format_exc()[-4000:]
        code = EXIT_FAIL
    if payload['erro']:
        eprint('ERRO: ' + payload['erro'])
    if want_json:
        real_stdout.write(json.dumps(_clean(payload), ensure_ascii=False) + '\n')
    else:
        real_stdout.write(_human(_clean(payload)) + '\n')
    real_stdout.flush()
    return code


if __name__ == '__main__':
    sys.exit(main())
