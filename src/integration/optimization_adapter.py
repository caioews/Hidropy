"""Adaptador de otimização: integra o main4.py existente (algoritmo genético, DEAP + WNTR).

Não há um segundo otimizador: o trabalhador executa o próprio main4.py com as
constantes de configuração substituídas (ver workers/optimization_worker.py).
"""

from __future__ import annotations

import os

from ..hydraulics.project import Project, now_iso
from . import runner
from .input_exporter import write_inp
from .results_importer import map_optimization


def script_path(project: Project) -> str:
    return os.path.abspath(project.settings.script_path or runner.DEFAULT_SCRIPT)


def constants_for(project: Project, export) -> dict:
    consts = project.opt_settings.script_constants()
    fixed = [export.names[p.uid] for p in project.network.links.values()
             if p.KIND == 'pipe' and p.fixed_in_optimization]
    consts['TRECHOS_FIXOS'] = fixed
    return consts


def prepare(project: Project) -> runner.RunJob:
    script = script_path(project)
    if not os.path.exists(script):
        raise FileNotFoundError(f'Script de otimização não encontrado: {script}')
    workdir = runner.new_workdir('otimizacao')
    inp = os.path.join(workdir, 'rede.inp')
    export = write_inp(project, inp, title=project.meta.get('title', ''))
    job = runner.RunJob(kind='optimize', workdir=workdir, inp_path=inp,
                        job_path=os.path.join(workdir, 'job.json'),
                        result_path=os.path.join(workdir, 'result.json'), export=export,
                        created=now_iso(), scenario=project.active_scenario)
    runner.write_job(job.job_path, {'script': script, 'inp': inp, 'workdir': workdir,
                                    'result': job.result_path,
                                    'constants': constants_for(project, export)})
    job.command = runner.worker_command('optimize', job.job_path,
                                        project.settings.python_interpreter)
    job.env = runner.worker_env()
    return job


def collect(job: runner.RunJob, log: str = '') -> dict:
    return map_optimization(runner.read_result(job), job, log)


def run_blocking(project: Project, timeout: float | None = 3600, on_output=None) -> dict:
    job = prepare(project)
    code, log = runner.run_blocking(job, timeout, on_output)
    res = collect(job, log)
    if code != 0 and res['status'] == 'ok':
        res['status'] = 'failed'
        res['error'] = f'Processo terminou com código {code}.'
    return res


def optimized_diameters(result: dict) -> dict[str, float]:
    """uid -> diâmetro otimizado (mm), apenas trechos dimensionados."""
    return {uid: d['opt_diam_mm'] for uid, d in result.get('pipes', {}).items()
            if not d.get('fixed')}


def diameter_changes(net, result: dict) -> list[tuple[str, float]]:
    """(uid, diâmetro otimizado) dos trechos projetados cujo diâmetro muda.

    Trechos existentes (executados) nunca entram, mesmo que o resultado os traga.
    """
    items = []
    for uid, d in optimized_diameters(result).items():
        l = net.links.get(uid)
        if l is not None and l.KIND == 'pipe' and not l.existing \
                and abs(l.diameter - d) > 1e-9:
            items.append((uid, d))
    return items


def create_optimized_scenario(project: Project, result: dict, name: str,
                              description: str = 'Diâmetros do main4.py aplicados'):
    """Novo cenário: cópia da rede ativa com os diâmetros otimizados (trechos existentes
    intactos) e o resultado da otimização anexado. Não muda o cenário ativo."""
    net = project.network.copy()
    for uid, d in diameter_changes(net, result):
        net.links[uid].diameter = d
    s = project.create_scenario(name, description, network=net)
    s.results.append(result)
    return s
