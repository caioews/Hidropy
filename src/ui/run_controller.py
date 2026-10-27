"""Execução dos trabalhadores em QProcess (não bloqueia a interface; cancelável)."""

from __future__ import annotations

import logging
import re

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

from ..integration import simulation_adapter, optimization_adapter

log = logging.getLogger(__name__)
_GEN = re.compile(r'Geracao\s+(\d+)')


class RunController(QObject):
    output = Signal(str)
    progress = Signal(int, int, str)      # valor, máximo (0 = indeterminado), texto
    finished = Signal(dict)               # resultado já associado aos uids
    started = Signal(str)

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.ctrl = controller
        self.proc: QProcess | None = None
        self.job = None
        self.kind = ''
        self.log_lines: list[str] = []
        self._buf = ''
        self._cancelled = False

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.state() != QProcess.NotRunning

    def start(self, kind: str):
        if self.running:
            raise RuntimeError('Já existe um cálculo em execução.')
        project = self.ctrl.project
        if kind == 'simulate':
            self.job = simulation_adapter.prepare(project)
            self.max_gen = 0
        else:
            self.job = optimization_adapter.prepare(project)
            self.max_gen = project.opt_settings.num_geracoes
        self.kind = kind
        self.log_lines = []
        self._buf = ''
        self._cancelled = False
        self.proc = QProcess(self)
        env = QProcessEnvironment()
        for k, v in self.job.env.items():
            env.insert(k, v)
        self.proc.setProcessEnvironment(env)
        self.proc.setWorkingDirectory(self.job.workdir)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(self._done)
        self.proc.errorOccurred.connect(self._error)
        cmd = self.job.command
        log.info('Executando: %s', ' '.join(cmd))
        self.output.emit(f'> {" ".join(cmd)}')
        self.output.emit(f'  diretório de trabalho: {self.job.workdir}')
        self.proc.start(cmd[0], cmd[1:])
        self.started.emit(kind)
        self.progress.emit(0, self.max_gen, 'Simulando…' if kind == 'simulate' else
                           'Otimizando (main4.py)…')

    def cancel(self):
        if self.running:
            self._cancelled = True
            self.output.emit('Cancelamento solicitado pelo usuário.')
            self.proc.kill()

    def _read(self):
        data = bytes(self.proc.readAllStandardOutput()).decode('utf-8', errors='replace')
        self._buf += data
        *lines, self._buf = self._buf.split('\n')
        for line in lines:
            line = line.rstrip('\r')
            self.log_lines.append(line)
            self.output.emit(line)
            m = _GEN.search(line)
            if m and self.max_gen:
                g = int(m.group(1))
                self.progress.emit(g, self.max_gen, f'Geração {g} de {self.max_gen}')

    def _error(self, err):
        if err == QProcess.FailedToStart:
            self.output.emit('ERRO: não foi possível iniciar o processo de cálculo. Verifique '
                             'o interpretador Python em Configurações.')
            self._finish({'status': 'failed', 'error': 'Falha ao iniciar o processo de cálculo.'},
                         -1)

    def _done(self, code, status):
        if self._buf:
            self.log_lines.append(self._buf)
            self.output.emit(self._buf)
            self._buf = ''
        self._finish(None, code)

    def _finish(self, raw, code):
        if self.job is None:
            return
        log_text = '\n'.join(self.log_lines)
        adapter = simulation_adapter if self.kind == 'simulate' else optimization_adapter
        if self._cancelled:
            res = adapter.collect(self.job, log_text)
            res['status'] = 'cancelled'
            res['error'] = 'Cálculo cancelado pelo usuário.'
        elif raw is not None:
            from ..integration.results_importer import map_simulation, map_optimization
            mapper = map_simulation if self.kind == 'simulate' else map_optimization
            res = mapper(raw, self.job, log_text)
        else:
            res = adapter.collect(self.job, log_text)
            if code != 0 and res['status'] == 'ok':
                res['status'] = 'failed'
                res['error'] = f'Processo terminou com código {code}.'
        self.job = None
        if self.proc is not None:
            self.proc.deleteLater()
        self.proc = None
        self.progress.emit(0, 1, '')
        self.finished.emit(res)
