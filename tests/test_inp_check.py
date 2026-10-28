"""Verificação de .inp antes da importação: codificação, arquivo corrompido e correções."""

import os

import pytest

from src.hydraulics.project import Project
from src.integration.inp_check import InpError, check_inp, prepare
from src.integration.inp_importer import import_inp

BASE = """[TITLE]
Rede de distribuição — São Gonçalo (demanda 0,01 L/s)

[JUNCTIONS]
;ID  Elev  Demand
 J1  {e1}  0.5   ; ponto ç
 J2  12    0.5

[RESERVOIRS]
 R1  50

[PIPES]
 P1  R1  J1  100  100  130  0  {st}  ;
 P2  J1  J2  80   75   130  0  Open  ;

[STATUS]
{status}

[REPORT]
 Status  {rep}

[OPTIONS]
 Units  LPS
 Unbalanced  {unb}

[COORDINATES]
 J1  10  0
 J2  90  0
 R1  0   0

[BACKDROP]
 UNITS  {units}

[END]
"""


def write(tmp_path, name, encoding='utf-8', **kw):
    vals = dict(e1='10', st='Open', status='', rep='No', unb='Continue 10', units='Meters')
    vals.update(kw)
    path = tmp_path / name
    path.write_bytes(BASE.format(**vals).encode(encoding))
    return str(path)


def load(path, fix=True):
    chk = check_inp(path)
    net, _ = import_inp(prepare(chk, apply_fixes=fix), Project())
    return chk, net


def test_ansi_file_converted_to_utf8(tmp_path):
    path = write(tmp_path, 'ansi.inp', encoding='cp1252')
    with pytest.raises(UnicodeDecodeError):
        open(path, encoding='utf-8').read()
    chk, net = load(path, fix=False)
    assert chk.encoding == 'cp1252' and chk.converted and not chk.issues
    assert len(net.nodes) == 3
    assert 'São Gonçalo' in chk.text
    assert open(path, 'rb').read().decode('cp1252').count('Gonçalo') == 1   # original intacto


@pytest.mark.parametrize('enc, label', [('utf-8-sig', 'UTF-8 (com BOM)'), ('utf-16', 'UTF-16')])
def test_other_encodings(tmp_path, enc, label):
    chk, net = load(write(tmp_path, 'x.inp', encoding=enc), fix=False)
    assert chk.encoding_label == label and len(net.nodes) == 3


def test_translated_backdrop_units_detected_and_fixed(tmp_path):
    path = write(tmp_path, 'metros.inp', units='Metros')
    chk = check_inp(path)
    assert len(chk.issues) == 1
    issue = chk.issues[0]
    assert issue.section == 'BACKDROP' and 'Metros' in issue.message and 'METERS' in issue.fixed
    with pytest.raises(Exception):                       # sem corrigir, o EPANET recusa
        import_inp(prepare(chk, apply_fixes=False), Project())
    net, _ = import_inp(prepare(chk, apply_fixes=True), Project())
    assert len(net.nodes) == 3
    assert 'Metros' in open(path, encoding='utf-8').read()           # original não muda


def test_other_translations_and_decimal_comma(tmp_path):
    path = write(tmp_path, 'pt.inp', e1='10,5', st='Fechado', status=' P2  Aberto',
                 rep='Sim', unb='Continuar 10', units='Pés')
    chk = check_inp(path)
    msgs = ' | '.join(i.message for i in chk.issues)
    for part in ("'10,5' → 10.5", "'Fechado' → CLOSED", "'Aberto' → OPEN", "'Sim' → YES",
                 "'Continuar' → CONTINUE", "'Pés' → FEET"):
        assert part in msgs
    assert '0,01 L/s' in chk.fixed_text                  # o título nunca é alterado
    assert '; ponto ç' in chk.fixed_text                 # comentários preservados
    net, _ = import_inp(prepare(chk, apply_fixes=True), Project())
    j1 = net.find_by_name('J1')
    assert j1.elevation == 10.5
    assert net.find_by_name('P1').status == 'Closed'


def test_binary_epanet_project_reported_as_corrupted(tmp_path):
    path = tmp_path / 'rede.inp'
    path.write_bytes(b'\x06\t<EPANET2>(N\x00\x01\x02' + os.urandom(2000))
    with pytest.raises(InpError, match='binário do EPANET'):
        check_inp(str(path))


@pytest.mark.parametrize('content, match', [
    (b'', 'vazio'),
    (b'\x00\x01\x02\x03' * 200, 'corrompido'),
    (bytes(range(1, 9)) * 300, 'corrompido'),
    ('isto não é uma rede\nnem tem seções\n'.encode('utf-8'), 'não é um arquivo .inp'),
])
def test_garbage_reported(tmp_path, content, match):
    path = tmp_path / 'lixo.inp'
    path.write_bytes(content)
    with pytest.raises(InpError, match=match):
        check_inp(str(path))


def test_missing_end_is_only_a_warning(tmp_path):
    path = tmp_path / 'sem_end.inp'
    path.write_text(BASE.format(e1='10', st='Open', status='', rep='No', unb='Continue 10',
                                units='Meters').replace('[END]', ''), encoding='utf-8')
    chk, net = load(str(path))
    assert any('[END]' in w for w in chk.warnings) and len(net.nodes) == 3


# arquivos reais enviados pelo usuário (opcionais: só rodam se existirem na máquina)
DOWNLOADS = os.path.join(os.path.expanduser('~'), 'Downloads')
UNIT_FILE = os.path.join(DOWNLOADS, 'exemplo inp com unidade errada.inp')
CORRUPT_FILE = os.path.join(DOWNLOADS, 'exemplo inp corrompido.inp')


@pytest.mark.skipif(not os.path.exists(UNIT_FILE), reason='arquivo de exemplo ausente')
def test_user_file_with_translated_unit():
    chk = check_inp(UNIT_FILE)
    assert [i.section for i in chk.issues] == ['BACKDROP']
    net, _ = import_inp(prepare(chk, apply_fixes=True), Project())
    assert len(net.nodes) == 27


@pytest.mark.skipif(not os.path.exists(CORRUPT_FILE), reason='arquivo de exemplo ausente')
def test_user_corrupted_file():
    with pytest.raises(InpError):
        check_inp(CORRUPT_FILE)


def test_gui_import_flow(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from src.ui.main_window import MainWindow
    w = MainWindow()
    shown = {}
    monkeypatch.setattr(QMessageBox, 'critical',
                        staticmethod(lambda *a, **k: shown.setdefault('critical', a[2])))
    # arquivo corrompido: avisa e não importa
    bad = tmp_path / 'ruim.inp'
    bad.write_bytes(b'\x06\t<EPANET2>' + os.urandom(500))
    w.import_inp(str(bad))
    assert 'binário do EPANET' in shown['critical'] and not w.ctrl.project.network.nodes
    # unidade traduzida: pede autorização; "Cancelar" não importa
    path = write(tmp_path, 'metros.inp', units='Metros')
    monkeypatch.setattr(QMessageBox, 'exec', lambda self: next(
        b for b in self.buttons() if 'Cancel' in b.text() or 'Cancelar' in b.text()).click())
    w.import_inp(path)
    assert not w.ctrl.project.network.nodes
    # "Corrigir e importar" importa a rede corrigida
    monkeypatch.setattr(QMessageBox, 'exec', lambda self: next(
        b for b in self.buttons() if b.text() == 'Corrigir e importar').click())
    w.import_inp(path)
    assert len(w.ctrl.project.network.nodes) == 3
    assert 'METERS' in w.logw.toPlainText() or 'Corrigido' in w.logw.toPlainText()
    # ANSI: converte sem perguntar nada
    w2 = MainWindow()
    w2.import_inp(write(tmp_path, 'ansi.inp', encoding='cp1252'))
    assert len(w2.ctrl.project.network.nodes) == 3
    assert 'convertida para UTF-8' in w2.logw.toPlainText()
    for x in (w, w2):
        x.ctrl.mark_saved()
        x.close()
