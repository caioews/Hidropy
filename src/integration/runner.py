"""Infraestrutura comum aos adaptadores: diretório de trabalho, comando do
subprocesso e execução bloqueante (usada em testes e linha de comando).

A interface gráfica usa QProcess com o mesmo comando (ver ui/run_controller.py),
para não bloquear a thread principal e permitir cancelamento.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

from .input_exporter import ExportResult

APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
WORKERS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'workers')
DEFAULT_SCRIPT = os.path.join(APP_ROOT, 'main4.py')

WORKER_FILES = {
    'simulate': os.path.join(WORKERS_DIR, 'simulation_worker.py'),
    'optimize': os.path.join(WORKERS_DIR, 'optimization_worker.py'),
}


@dataclass
class RunJob:
    kind: str                 # 'simulate' | 'optimize'
    workdir: str
    inp_path: str
    job_path: str
    result_path: str
    export: ExportResult
    command: list = field(default_factory=list)
    env: dict = field(default_factory=dict)
    created: str = ''
    scenario: str = ''


def runs_root() -> str:
    root = os.path.join(tempfile.gettempdir(), 'shcad_execucoes')
    os.makedirs(root, exist_ok=True)
    return root


def new_workdir(kind: str) -> str:
    stamp = _dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    path = os.path.join(runs_root(), f'{kind}_{stamp}')
    os.makedirs(path, exist_ok=True)
    return os.path.abspath(path)


def interpreter(python_interpreter: str = '') -> str:
    return python_interpreter or sys.executable


def worker_command(kind: str, job_path: str, python_interpreter: str = '') -> list[str]:
    if getattr(sys, 'frozen', False):
        # executável gerado pelo PyInstaller: o próprio executável despacha o trabalhador
        return [sys.executable, '--worker', kind, job_path]
    return [interpreter(python_interpreter), '-u', WORKER_FILES[kind], job_path]


def worker_env() -> dict:
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUNBUFFERED'] = '1'
    env['MPLBACKEND'] = 'Agg'
    return env


def write_job(path: str, data: dict):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def read_result(job: RunJob) -> dict:
    if not os.path.exists(job.result_path):
        return {'status': 'failed',
                'error': 'O processo de cálculo terminou sem gravar resultados.'}
    try:
        with open(job.result_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        return {'status': 'failed', 'error': f'Resultado ilegível: {e}'}


def run_blocking(job: RunJob, timeout: float | None = None, on_output=None) -> tuple[int, str]:
    """Executa o trabalhador e devolve (código de saída, log)."""
    proc = subprocess.Popen(job.command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            env=job.env, cwd=job.workdir, text=True, encoding='utf-8',
                            errors='replace')
    lines = []
    try:
        for line in proc.stdout:
            lines.append(line)
            if on_output:
                on_output(line.rstrip('\n'))
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        code = -1
        lines.append('Tempo limite excedido.\n')
    return code, ''.join(lines)
