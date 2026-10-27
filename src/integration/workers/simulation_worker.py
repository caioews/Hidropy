"""Trabalhador de SIMULAÇÃO — executado em subprocesso.

Uso:  python simulation_worker.py job.json

Usa o mesmo motor e a mesma chamada de main4.py:
    wntr.sim.EpanetSimulator(wn).run_sim(file_prefix=...)
Nada de cálculo hidráulico é reimplementado aqui: apenas leitura do .inp,
execução do EPANET (via WNTR) e conversão de unidades para a gravação em JSON.

O resultado é indexado pelos NOMES do .inp (nunca pela posição).
"""

import json
import math
import os
import sys
import traceback


def _clean(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _series(df, name, scale=1.0):
    if name not in df.columns:
        return None
    return [None if (c := _clean(x)) is None else c * scale for x in df[name].values]


def _write(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def _read_rpt(prefix):
    path = prefix + '.rpt'
    if not os.path.exists(path):
        return ''
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        return f.read()


def run(job):
    import warnings
    warnings.filterwarnings('ignore')
    import wntr

    inp = job['inp']
    prefix = os.path.join(job['workdir'], 'sim')
    print(f'Lendo a rede: {inp}', flush=True)
    wn = wntr.network.WaterNetworkModel(inp)
    print(f'  {wn.num_junctions} junções, {wn.num_reservoirs} reservatórios, {wn.num_tanks} '
          f'tanques, {wn.num_pipes} tubos, {wn.num_pumps} bombas, {wn.num_valves} válvulas',
          flush=True)
    dur = wn.options.time.duration
    print('Executando EPANET (wntr.sim.EpanetSimulator) - '
          + ('período estendido' if dur > 0 else 'regime permanente'), flush=True)

    try:
        res = wntr.sim.EpanetSimulator(wn).run_sim(file_prefix=prefix)
    except Exception as e:
        rpt = _read_rpt(prefix)
        return {'status': 'failed', 'error': f'O EPANET falhou: {e}', 'report': rpt,
                'traceback': traceback.format_exc()}

    rpt = _read_rpt(prefix)
    times = [float(t) for t in res.node['pressure'].index]
    print(f'Simulação concluída: {len(times)} instante(s).', flush=True)

    nodes = {}
    P, H, D = res.node['pressure'], res.node['head'], res.node['demand']
    for name in wn.node_name_list:
        d = {'pressure': _series(P, name), 'head': _series(H, name),
             'demand': _series(D, name, 1000.0)}          # m3/s -> L/s
        if name in wn.tank_name_list:
            d['level'] = _series(P, name)                   # pressão no tanque = nível
            t = wn.get_node(name)
            d['volume'] = [None if l is None else _clean(t.get_volume(l))
                           for l in d['level']]
        nodes[name] = d

    links = {}
    Q, V, HL = res.link['flowrate'], res.link['velocity'], res.link['headloss']
    ST = res.link.get('status')
    SET = res.link.get('setting')
    FF = res.link.get('friction_factor')     # fator de atrito calculado pelo EPANET
    for name in wn.link_name_list:
        link = wn.get_link(name)
        d = {'flow': _series(Q, name, 1000.0),               # m3/s -> L/s
             'velocity': _series(V, name)}
        if link.link_type == 'Pipe':
            # headloss do EpanetSimulator em tubos e m/m (ver [CORRECAO 4] do main4.py)
            d['unit_headloss'] = _series(HL, name, 1000.0)   # m/km
            d['headloss'] = _series(HL, name, float(link.length))   # m
        else:
            d['headloss'] = _series(HL, name)                # m (bomba: negativo = ganho)
        if ST is not None:
            d['status'] = _series(ST, name)
        if SET is not None:
            d['setting'] = _series(SET, name)
        if FF is not None and link.link_type == 'Pipe':
            d['friction_factor'] = _series(FF, name)
        links[name] = d

    # vazão de entrada/saída por nó (soma das vazões das ligações conectadas)
    for name in wn.node_name_list:
        inflow = [0.0] * len(times)
        outflow = [0.0] * len(times)
        for lname in wn.get_links_for_node(name):
            link = wn.get_link(lname)
            q = links[lname]['flow'] or [0.0] * len(times)
            for k, v in enumerate(q):
                if v is None:
                    continue
                into = (v > 0) == (link.end_node_name == name)
                if into:
                    inflow[k] += abs(v)
                else:
                    outflow[k] += abs(v)
        nodes[name]['inflow'] = inflow
        nodes[name]['outflow'] = outflow

    warn = [l.strip() for l in rpt.splitlines()
            if 'WARNING' in l.upper() or 'ERROR' in l.upper() or 'NEGATIVE' in l.upper()]
    return {'status': 'ok', 'engine': 'wntr.sim.EpanetSimulator',
            'wntr_version': getattr(wntr, '__version__', '?'),
            'times': times, 'nodes': nodes, 'links': links,
            'report': rpt, 'warnings': warn}


def main(argv):
    if len(argv) < 2:
        print('uso: simulation_worker.py job.json', file=sys.stderr)
        return 2
    with open(argv[1], 'r', encoding='utf-8') as f:
        job = json.load(f)
    try:
        out = run(job)
    except Exception as e:
        out = {'status': 'failed', 'error': f'{type(e).__name__}: {e}',
               'traceback': traceback.format_exc()}
    _write(job['result'], out)
    if out['status'] != 'ok':
        print('ERRO: ' + out['error'], file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
