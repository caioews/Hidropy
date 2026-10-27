"""Trabalhador de OTIMIZAÇÃO — executa o main4.py existente em subprocesso.

Uso:  python optimization_worker.py job.json

Estratégia (ver ANALISE_DO_PROJETO.md, seção 3.1):
  1. Lê o código-fonte de main4.py SEM modificá-lo no disco.
  2. Substitui, via AST, apenas os VALORES das atribuições de topo das constantes de
     configuração (ARQUIVO_REDE, NUM_GERACOES, ...). Constante ausente => erro.
  3. Executa o módulo com __name__ != '__main__' e chama main() do próprio script.
  4. Lê o .inp gerado pelo script (ARQUIVO_SAIDA) e chama detalhar()/rodar_epanet()
     do próprio script para obter os indicadores, que são gravados indexados por nome.
"""

import ast
import hashlib
import json
import math
import os
import sys
import traceback


def _sha256(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def _clean(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _write(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


class ConstantOverrider(ast.NodeTransformer):
    """Troca o valor de atribuições de topo `NOME = ...` pelas sobrescritas dadas."""

    def __init__(self, overrides):
        self.overrides = overrides
        self.found = set()

    def visit_Module(self, node):
        for stmt in node.body:
            if (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name)
                    and stmt.targets[0].id in self.overrides):
                name = stmt.targets[0].id
                stmt.value = ast.parse(repr(self.overrides[name]), mode='eval').body
                self.found.add(name)
        return node


def load_patched(script_path, overrides):
    with open(script_path, 'r', encoding='utf-8') as f:
        src = f.read()
    tree = ast.parse(src, filename=script_path)
    tr = ConstantOverrider(overrides)
    tree = tr.visit(tree)
    missing = sorted(set(overrides) - tr.found)
    if missing:
        raise RuntimeError('As seguintes constantes não existem em '
                           f'{os.path.basename(script_path)}: {missing}. '
                           'A interface de integração não corresponde ao script.')
    ast.fix_missing_locations(tree)
    return compile(tree, script_path, 'exec')


def run(job):
    script = job['script']
    workdir = job['workdir']
    consts = dict(job['constants'])
    consts['ARQUIVO_REDE'] = job['inp']
    consts['ARQUIVO_SAIDA'] = os.path.join(workdir, 'rede_otimizada.inp')
    # o JSON transforma tuplas em listas; o script usa índices, então listas servem
    consts['CATALOGO_COMPLETO'] = [tuple(c) for c in consts['CATALOGO_COMPLETO']]

    hash_before = _sha256(script)
    code = load_patched(script, consts)

    sys.path.insert(0, os.path.dirname(script))
    os.chdir(workdir)
    ns = {'__name__': 'main4_integrado', '__file__': script}
    print(f'Executando {os.path.basename(script)} (constantes sobrescritas: '
          f'{", ".join(sorted(consts))})', flush=True)
    exec(code, ns)          # executa a parte de topo do script (inventário, alvos, faixa)
    ns['main']()            # laço evolutivo do próprio script
    sys.stdout.flush()

    out_inp = consts['ARQUIVO_SAIDA']
    if not os.path.exists(out_inp):
        return {'status': 'failed',
                'error': 'O script terminou sem gerar a rede otimizada (o teste de '
                         'viabilidade do main4.py falhou; veja o log).',
                'script_unchanged': _sha256(script) == hash_before}

    import wntr
    wn_opt = wntr.network.WaterNetworkModel(out_inp)
    wn_orig = wntr.network.WaterNetworkModel(job['inp'])

    TUBOS = list(ns['TUBOS'])
    JUNCOES = list(ns['JUNCOES'])
    DIAM_M = list(ns['DIAM_M'])
    DN_MM = list(ns['DN_MM'])
    CUSTO_M = list(ns['CUSTO_M'])
    fixos = list(ns['TRECHOS_FIXOS'])

    idx = []
    for t in TUBOS:
        d = wn_opt.get_link(t).diameter
        idx.append(min(range(len(DIAM_M)), key=lambda k: abs(DIAM_M[k] - d)))
    det = ns['detalhar'](idx)       # avaliação do próprio script
    if not det.get('ok'):
        return {'status': 'failed', 'error': f"detalhar() falhou: {det.get('erro')}"}

    orig_d = {t: wn_orig.get_link(t).diameter for t in TUBOS}
    try:
        ref = ns['rodar_epanet'](orig_d)   # rede original pelo mesmo método do script
    except Exception as e:
        ref = None
        print(f'Aviso: não foi possível avaliar a rede original: {e}', flush=True)

    catalog = consts['CATALOGO_COMPLETO']

    def catalog_cost(d_m):
        for dn, dm, c in catalog:
            if abs(dm - d_m) < 5e-4:
                return c
        return None

    vmax_lim = consts['VELOCIDADE_MAX']
    pipes = {}
    custo_orig = 0.0
    custo_orig_ok = True
    for i, t in enumerate(TUBOS):
        L = float(wn_orig.get_link(t).length)
        c_orig = catalog_cost(orig_d[t])
        if c_orig is None:
            custo_orig_ok = False
        else:
            custo_orig += c_orig * L
        pipes[t] = {
            'fixed': False, 'length': L,
            'orig_diam_mm': orig_d[t] * 1000.0, 'opt_diam_mm': DIAM_M[idx[i]] * 1000.0,
            'dn': DN_MM[idx[i]], 'cost_per_m': CUSTO_M[idx[i]],
            'cost_opt': CUSTO_M[idx[i]] * L,
            'cost_orig': None if c_orig is None else c_orig * L,
            'v_max': _clean(det['v_max'][i]), 'j_max': _clean(det['j_max'][i]),
            'q_max': _clean(det['q_max'][i] * 1000.0),
            'v_max_orig': _clean(ref['v_max'][i]) if ref else None,
            'j_max_orig': _clean(ref['j_max'][i]) if ref else None,
            'ok_velocity': bool(det['v_max'][i] <= vmax_lim),
        }
    for t in fixos:
        d = wn_orig.get_link(t).diameter * 1000.0
        pipes[t] = {'fixed': True, 'length': float(wn_orig.get_link(t).length),
                    'orig_diam_mm': d, 'opt_diam_mm': d}

    alvo = list(ns['ALVO_PRESSAO'])
    teto = list(ns['TETO_PRESSAO'])
    tol = consts['TOLERANCIA_PRESSAO']
    pmax_lim = consts['PRESSAO_MAX']
    junctions = {}
    for i, j in enumerate(JUNCOES):
        junctions[j] = {
            'p_min': _clean(det['p_min'][i]), 'p_max': _clean(det['p_max'][i]),
            'alvo': _clean(alvo[i]), 'teto': _clean(teto[i]),
            'p_min_orig': _clean(ref['p_min'][i]) if ref else None,
            'p_max_orig': _clean(ref['p_max'][i]) if ref else None,
            'ok_pressure': bool(det['p_min'][i] >= alvo[i] - tol
                                and det['p_max'][i] <= pmax_lim + tol),
        }

    summary = {
        'custo': det['custo'], 'viavel': bool(det['viavel']),
        'violacao': det['violacao'], 'fitness': det['fitness'],
        'n_p_baixa': det['n_p_baixa'], 'n_p_alta': det['n_p_alta'],
        'n_v_alta': det['n_v_alta'], 'n_j_alta': det['n_j_alta'],
        'hora_critica': det['hora_critica'] if ns.get('PERIODO_ESTENDIDO') else None,
        'p_min': _clean(min(det['p_min'])), 'p_max': _clean(max(det['p_max'])),
        'v_max': _clean(max(det['v_max'])),
        'faixa_dn': DN_MM, 'custo_ref': ns.get('CUSTO_REF'),
        'comprimento_total': ns.get('COMPRIMENTO_TOTAL'),
        'avaliacoes_unicas': len(ns.get('_cache', {})),
        'custo_original': custo_orig if custo_orig_ok else None,
        'periodo_estendido': bool(ns.get('PERIODO_ESTENDIDO')),
    }
    hash_after = _sha256(script)
    return {'status': 'ok', 'engine': os.path.basename(script), 'script_sha256': hash_before,
            'script_unchanged': hash_before == hash_after,
            'pipes': pipes, 'junctions': junctions, 'summary': summary,
            'optimized_inp': out_inp}


def main(argv):
    if len(argv) < 2:
        print('uso: optimization_worker.py job.json', file=sys.stderr)
        return 2
    with open(argv[1], 'r', encoding='utf-8') as f:
        job = json.load(f)
    try:
        out = run(job)
    except SystemExit as e:
        out = {'status': 'failed', 'error': f'O script encerrou (SystemExit {e.code}).'}
    except Exception as e:
        out = {'status': 'failed', 'error': f'{type(e).__name__}: {e}',
               'traceback': traceback.format_exc()}
    _write(job['result'], out)
    if out['status'] != 'ok':
        print('ERRO: ' + out['error'], file=sys.stderr, flush=True)
        return 1
    print('Otimização concluída.', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
