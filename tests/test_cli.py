"""Linha de comando (src/cli.py): JSON de cada comando, gravação de cenários otimizados,
preservação de trechos existentes e do main4.py."""

import hashlib
import json
import os
import subprocess
import sys

import pytest

from conftest import EXAMPLES, MAIN4, ROOT
from src import cli
from src.hydraulics.project_io import load_project, save_project

PRAIA = os.path.join(os.path.dirname(ROOT), 'RDA_Praia das Fontes.inp')
FAST = ['--geracoes', '3', '--populacao', '10']


def run(capsys, *args):
    code = cli.main([str(a) for a in args] + ['--json'])
    out = capsys.readouterr().out.strip()
    data = json.loads(out)          # o stdout é exatamente um objeto JSON
    assert data['cli_versao'] == cli.CLI_VERSION
    assert data['ok'] == (code == 0)
    return code, data


def sha(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


@pytest.fixture
def proj(tmp_path, simple_project):
    """Rede de exemplo com P1 marcado como trecho existente (executado)."""
    p = simple_project
    p.network.find_by_name('P1').fixed_in_optimization = True
    path = str(tmp_path / 'rede.shcad')
    save_project(p, path, backup=False)
    return path


def test_info_shcad(capsys):
    code, d = run(capsys, 'info', os.path.join(EXAMPLES, 'rede_exemplo.shcad'))
    assert code == 0 and d['comando'] == 'info' and d['tipo'] == 'shcad'
    assert d['rede']['juncoes'] == 9 and d['rede']['tubulacoes'] == 13
    assert d['cenarios'][0]['ativo'] and d['cenario']['nome'] == d['cenarios'][0]['nome']
    assert d['opcoes_otimizacao']['num_geracoes'] == 150
    assert d['custos_catalogo']['custo_projetado'] > 0


def test_info_inp(capsys):
    code, d = run(capsys, 'info', os.path.join(EXAMPLES, 'rede_exemplo.inp'))
    assert code == 0 and d['tipo'] == 'inp' and d['rede']['tubulacoes'] > 0


def test_usage_and_file_errors(capsys, tmp_path):
    code, d = run(capsys, 'info', str(tmp_path / 'nao_existe.shcad'))
    assert code == 2 and 'não encontrado' in d['erro']
    code, d = run(capsys, 'comando-inexistente', 'x.shcad')
    assert code == 2 and d['erro']
    code, d = run(capsys, 'info', os.path.join(EXAMPLES, 'rede_exemplo.shcad'),
                  '--cenario', 'Nenhum')
    assert code == 2 and 'Cenários' in d['erro']


def test_validar(capsys, proj, tmp_path):
    code, d = run(capsys, 'validar', proj)
    assert code == 0 and d['valido'] and d['erros'] == 0
    # rede com erro: diâmetro inválido
    p = load_project(proj)
    p.network.find_by_name('P3').diameter = 0
    bad = str(tmp_path / 'ruim.shcad')
    save_project(p, bad, backup=False)
    code, d = run(capsys, 'validar', bad)
    assert code == 1 and not d['valido'] and d['erros'] >= 1
    assert 'DIAMETRO_INVALIDO' in d['por_codigo']
    assert any(x['codigo'] == 'DIAMETRO_INVALIDO' and x['elemento'] == 'P3'
               for x in d['problemas'])
    code, d = run(capsys, 'simular', bad)
    assert code == 1 and 'validação' in d['erro']


def test_simular_e_gravar(capsys, proj):
    before = sha(proj)
    code, d = run(capsys, 'simular', proj)
    assert code == 0 and d['status'] == 'ok' and d['gravado'] is None
    assert sha(proj) == before                       # sem --gravar não toca no arquivo
    assert d['pressao_min']['valor'] < d['pressao_max']['valor']
    assert d['velocidade_max']['trecho'].startswith('P')
    assert d['atende_limites'] is True and d['fora_dos_limites']['pressao_baixa']['n'] == 0
    code, d = run(capsys, 'simular', proj, '--gravar')
    assert code == 0 and d['gravado']['arquivo'] == os.path.abspath(proj)
    assert os.path.exists(proj + '.bak') and not os.path.exists(proj + '.lock')
    code, info = run(capsys, 'info', proj)
    assert info['cenarios'][0]['ultima_simulacao']['atual'] is True
    assert info['cenarios'][0]['ultima_simulacao']['uid'] == d['resultado_uid']


def test_otimizar_cria_cenario_e_preserva_existentes(capsys, proj):
    main4 = sha(MAIN4)
    code, d = run(capsys, 'otimizar', proj, *FAST, '--semente', '7', '--dn-max', '300',
                  '--criar-cenario', 'Otimizada s7', '--detalhes')
    assert code == 0, d['erro']
    assert d['status'] == 'ok' and d['script_inalterado'] is True
    assert isinstance(d['custo'], float) and isinstance(d['viavel'], bool)
    assert d['trechos_existentes_preservados'] == 1 and d['trechos_projetados'] == 12
    assert d['configuracao']['semente'] == 7 and d['configuracao']['num_geracoes'] == 3
    assert d['configuracao']['dn_max_permitido'] == 300
    assert set(d['parametros_alterados']) >= {'num_geracoes', 'semente', 'dn_max_permitido'}
    assert d['trechos_alterados'] == len(d['alteracoes'])
    assert all(a['id'] != 'P1' for a in d['alteracoes'])
    cc = d['cenario_criado']
    assert cc['cenario_nome'] == 'Otimizada s7' and cc['ativado'] is False
    assert sha(MAIN4) == main4

    p = load_project(proj)
    assert p.scenario().name != 'Otimizada s7'       # o cenário ativo não mudou
    base = p.network
    new = next(s for s in p.scenarios if s.uid == cc['cenario_uid'])
    assert new.parent == p.active_scenario and new.results[-1]['uid'] == d['resultado_uid']
    assert new.results[-1]['opt_settings']['semente'] == 7
    p.switch_scenario(new.uid)
    opt = p.network
    assert opt.find_by_name('P1').diameter == base.find_by_name('P1').diameter == 250
    changed = {a['id']: a['para_mm'] for a in d['alteracoes']}
    for l in base.links.values():
        exp = changed.get(l.name, l.diameter)
        assert opt.links[l.uid].diameter == exp
    # opções originais do projeto não foram sobrescritas pelos overrides
    assert p.opt_settings.num_geracoes == 150 and p.opt_settings.semente == 42

    # nome repetido é recusado sem --substituir
    code, d2 = run(capsys, 'otimizar', proj, *FAST, '--criar-cenario', 'otimizada S7')
    assert code == 1 and 'Já existe' in d2['erro']
    code, d2 = run(capsys, 'otimizar', proj, *FAST, '--criar-cenario', 'Otimizada s7',
                   '--substituir')
    assert code == 0
    assert [s.name for s in load_project(proj).scenarios].count('Otimizada s7') == 1


def test_otimizar_parametros_invalidos(capsys, proj):
    code, d = run(capsys, 'otimizar', proj, '--dn-min', '300', '--dn-max', '100')
    assert code == 2 and 'dn-min' in d['erro']


def test_catalogo_json(capsys, proj, tmp_path):
    cat = tmp_path / 'cat.json'
    cat.write_text(json.dumps([{'dn': 75, 'diametro_mm': 75, 'custo': 40},
                               {'dn': 100, 'diametro_mm': 100, 'custo': 62},
                               [150, 0.15, 125.0], [200, 0.2, 205.0], [250, 0.25, 310.0]]),
                   encoding='utf-8')
    code, d = run(capsys, 'otimizar', proj, *FAST, '--catalogo', cat, '--detalhes')
    assert code == 0, d['erro']
    assert 'catalogo_completo' in d['parametros_alterados']
    assert set(d['faixa_dn']) <= {75, 100, 150, 200, 250}
    assert all(a['para_mm'] in (75, 100, 150, 200, 250) for a in d['alteracoes'])


def test_comparar_aplicar_e_ativar(capsys, proj):
    code, d = run(capsys, 'otimizar', proj, *FAST, '--criar-cenario', 'Cand A')
    assert code == 0
    n_alt = d['trechos_alterados']
    code, c = run(capsys, 'comparar', proj, '--simular', '--gravar')
    assert code == 0 and len(c['cenarios']) == 2 and c['referencia'] == 'Rede original'
    orig, cand = c['cenarios']
    assert orig['ativo'] and orig['trechos_diferentes_da_referencia'] == 0
    assert cand['nome'] == 'Cand A' and cand['trechos_diferentes_da_referencia'] == n_alt
    assert cand['otimizacao']['custo'] == d['custo']
    assert cand['simulacao']['simulado_agora'] and cand['simulacao']['pressao_min']
    if c['melhor']:
        assert c['melhor']['nome'] in ('Rede original', 'Cand A')
    assert c['gravado'] is not None
    # simulações gravadas: segunda comparação não simula de novo
    code, c2 = run(capsys, 'comparar', proj, '--cenarios', 'Cand A')
    assert len(c2['cenarios']) == 1 and c2['cenarios'][0]['simulacao']['simulado_agora'] is False

    # aplicar: o resultado mora no cenário criado
    code, e = run(capsys, 'aplicar-otimizacao', proj)
    assert code == 1 and 'Nenhuma otimização' in e['erro']
    code, ap = run(capsys, 'aplicar-otimizacao', proj, '--de-cenario', 'Cand A', '--detalhes')
    assert code == 0 and ap['trechos_alterados'] == n_alt and ap['resultado_atual']
    assert os.path.exists(ap['gravado']['backup'])
    p = load_project(proj)
    assert p.scenario().name == 'Rede original'
    assert p.network.find_by_name('P1').diameter == 250          # existente intacto
    for a in ap['alteracoes']:
        assert p.network.find_by_name(a['id']).diameter == a['para_mm']
    code, e = run(capsys, 'aplicar-otimizacao', proj, '--de-cenario', 'Cand A')
    assert code == 1 and 'desatualizado' in e['erro']

    code, at = run(capsys, 'ativar-cenario', proj, '--cenario', 'cand a')
    assert code == 0 and load_project(proj).scenario().name == 'Cand A'


def test_exportacoes(capsys, proj, tmp_path):
    out = tmp_path / 'saidas'
    code, d = run(capsys, 'exportar-dxf', proj, '--planta', 'execucao',
                  '--saida', out / 'exec.dxf')
    assert code == 0 and d['pecas'] > 0 and os.path.getsize(d['saida']) > 0
    code, d = run(capsys, 'exportar-dxf', proj, '--saida', out / 'calc.dxf')
    assert code == 0 and d['resultados_usados'] is None and d['aviso']
    code, d = run(capsys, 'exportar-dxf', proj, '--simular', '--saida', out / 'calc2.dxf')
    assert code == 0 and d['resultados_usados']
    code, d = run(capsys, 'planilha', proj, '--saida', out / 'res.xlsx')
    assert code == 1 and '--simular' in d['erro']
    code, d = run(capsys, 'planilha', proj, '--simular', '--saida', out / 'res.xlsx')
    assert code == 0 and d['linhas'] == {'Nos': 10, 'Trechos': 13}
    assert all(os.path.exists(f) for f in d['arquivos'])
    code, d = run(capsys, 'planilha', proj, '--tipo', 'cadastro', '--saida', out / 'cad.csv')
    assert code == 0 and len(d['arquivos']) >= 2
    code, d = run(capsys, 'relatorio', proj, '--secoes', 'cadastro,validacao',
                  '--saida', out / 'rel.html')
    assert code == 0 and d['secoes'] == ['cadastro', 'validacao']
    with open(d['saida'], encoding='utf-8') as f:
        assert 'Cadastro dos elementos' in f.read()
    code, d = run(capsys, 'relatorio', proj, '--secoes', 'xyz', '--saida', out / 'r.html')
    assert code == 2


def test_importar_inp(capsys, tmp_path):
    target = tmp_path / 'importada.shcad'
    code, d = run(capsys, 'importar', os.path.join(EXAMPLES, 'rede_exemplo.inp'),
                  '--saida', target, '--titulo', 'Importada')
    assert code == 0 and d['tubulacoes'] > 0
    p = load_project(str(target))
    assert p.meta['title'] == 'Importada' and len(p.network.links) == d['ligacoes']
    code, d = run(capsys, 'importar', os.path.join(EXAMPLES, 'rede_exemplo.inp'),
                  '--saida', target)
    assert code == 2 and 'sobrescrever' in d['erro']


def test_dispatch_main_py(tmp_path):
    """`python main.py cli ...`: JSON puro no stdout, mensagens no stderr."""
    r = subprocess.run([sys.executable, os.path.join(ROOT, 'main.py'), 'cli', 'validar',
                        os.path.join(EXAMPLES, 'rede_exemplo.shcad'), '--json'],
                       capture_output=True, text=True, encoding='utf-8', cwd=str(tmp_path))
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert d['comando'] == 'validar' and d['valido'] is True


@pytest.mark.skipif(not os.path.exists(PRAIA), reason='RDA_Praia das Fontes.inp ausente')
def test_rede_real_inp(capsys, tmp_path):
    code, d = run(capsys, 'info', PRAIA)
    assert code == 0 and d['rede']['tubulacoes'] > 100
    target = tmp_path / 'praia.shcad'
    code, d = run(capsys, 'otimizar', PRAIA, '--geracoes', '2', '--populacao', '8',
                  '--criar-cenario', 'Teste CLI', '--saida', target)
    assert code == 0, d['erro']
    assert d['status'] == 'ok' and d['trechos_existentes_preservados'] == 0
    assert 0 <= d['trechos_alterados'] <= d['trechos_projetados']
    assert d['cenario_criado']['arquivo'] == str(target)
    p = load_project(str(target))
    assert [s.name for s in p.scenarios] == ['Rede original', 'Teste CLI']
    # o .shcad gerado já pode ser usado como entrada
    code, c = run(capsys, 'comparar', target)
    assert code == 0 and len(c['cenarios']) == 2
    # e .inp + destino existente é recusado (identificadores não correspondem)
    code, d = run(capsys, 'otimizar', PRAIA, '--geracoes', '1', '--populacao', '4',
                  '--criar-cenario', 'Outro', '--saida', target)
    assert code == 1 and 'já existe' in d['erro']
