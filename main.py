"""HidroPy — simulador hidráulico CAD. Ponto de entrada.

    python main.py [projeto.shcad | desenho.dxf | rede.inp]

Também despacha os trabalhadores de cálculo quando empacotado (PyInstaller):
    main.exe --worker simulate|optimize job.json

Verificação sem interface (simulação + otimização curta pelo mesmo caminho do F5/F6):
    main.exe --verificar projeto.shcad [gerações]

Linha de comando para scripts e agentes (saída JSON com --json; ver README):
    python main.py cli <comando> projeto.shcad|rede.inp [opções] [--json]
    HidroPy.exe cli <comando> ...      (comandos: info, validar, simular, otimizar, ...)
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _std_streams():
    # executável sem console: sys.stdout/stderr podem ser None mesmo com saída redirecionada
    for name, fd in (('stdout', 1), ('stderr', 2)):
        if getattr(sys, name) is None:
            try:
                stream = open(fd, 'w', encoding='utf-8', errors='replace', buffering=1,
                              closefd=False)
            except OSError:
                stream = open(os.devnull, 'w', encoding='utf-8')
            setattr(sys, name, stream)
        else:
            # o executável ignora PYTHONIOENCODING; a interface lê o log em UTF-8
            try:
                getattr(sys, name).reconfigure(encoding='utf-8', errors='replace',
                                               line_buffering=True)
            except (AttributeError, ValueError):
                pass


def _worker(argv):
    kind, job = argv[2], argv[3]
    _std_streams()
    if kind == 'simulate':
        from src.integration.workers import simulation_worker as w
    else:
        from src.integration.workers import optimization_worker as w
    return w.main([w.__file__, job])


def _verify(argv):
    _std_streams()
    from src.hydraulics.project_io import load_project
    from src.integration import optimization_adapter, runner, simulation_adapter
    project = load_project(argv[2])
    project.opt_settings.num_geracoes = int(argv[3]) if len(argv) > 3 else 3
    print(f'frozen={getattr(sys, "frozen", False)} script={optimization_adapter.script_path(project)}',
          flush=True)
    ok = True
    for name, adapter in (('simulação', simulation_adapter), ('otimização', optimization_adapter)):
        job = adapter.prepare(project)
        print(f'{name}: {" ".join(job.command)}', flush=True)
        code, log = runner.run_blocking(job, 3600)
        res = adapter.collect(job, log)
        print(f'{name}: código {code}, status {res["status"]} {res.get("error") or ""}', flush=True)
        ok = ok and code == 0 and res['status'] == 'ok'
    return 0 if ok else 1


def _cli(argv):
    _std_streams()
    from src.cli import main as cli_main
    return cli_main(argv[2:])


if __name__ == '__main__':
    if len(sys.argv) >= 2 and sys.argv[1] == 'cli':
        sys.exit(_cli(sys.argv))
    if len(sys.argv) >= 4 and sys.argv[1] == '--worker':
        sys.exit(_worker(sys.argv))
    if len(sys.argv) >= 3 and sys.argv[1] == '--verificar':
        sys.exit(_verify(sys.argv))
    from src.app import run
    sys.exit(run())
