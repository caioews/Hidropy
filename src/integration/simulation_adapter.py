"""Adaptador de simulação: modelo do projeto -> .inp -> trabalhador (EPANET via WNTR) -> resultados."""

from __future__ import annotations

import os

from ..hydraulics.project import Project, now_iso
from . import runner
from .input_exporter import write_inp
from .results_importer import map_simulation


def prepare(project: Project) -> runner.RunJob:
    workdir = runner.new_workdir('simulacao')
    inp = os.path.join(workdir, 'rede.inp')
    export = write_inp(project, inp, title=project.meta.get('title', ''))
    job = runner.RunJob(kind='simulate', workdir=workdir, inp_path=inp,
                        job_path=os.path.join(workdir, 'job.json'),
                        result_path=os.path.join(workdir, 'result.json'), export=export,
                        created=now_iso(), scenario=project.active_scenario)
    runner.write_job(job.job_path, {'inp': inp, 'workdir': workdir, 'result': job.result_path})
    job.command = runner.worker_command('simulate', job.job_path,
                                        project.settings.python_interpreter)
    job.env = runner.worker_env()
    return job


def collect(job: runner.RunJob, log: str = '') -> dict:
    return map_simulation(runner.read_result(job), job, log)


def run_blocking(project: Project, timeout: float | None = 600, on_output=None) -> dict:
    job = prepare(project)
    code, log = runner.run_blocking(job, timeout, on_output)
    res = collect(job, log)
    if code != 0 and res['status'] == 'ok':
        res['status'] = 'failed'
        res['error'] = f'Processo terminou com código {code}.'
    return res
