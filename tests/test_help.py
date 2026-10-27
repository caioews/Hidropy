"""Menu Ajuda: manual do usuário e janela Sobre."""

import re

AUTHOR = 'Caio Henrique de Oliveira Nascimento'
LINKEDIN = 'linkedin.com/in/caio-henrique-6a6650236'


def test_help_menu_has_manual_and_about_only(qapp):
    from src.ui.main_window import MainWindow
    w = MainWindow()
    menu = next(m for m in w.menuBar().actions() if m.text().replace('&', '') == 'Ajuda')
    labels = [a.text() for a in menu.menu().actions() if a.text()]
    assert labels == ['Manual do HidroPy', 'Sobre o HidroPy']
    assert not hasattr(w, 'feature_status')
    w.ctrl.mark_saved()
    w.close()


def test_manual_content(qapp):
    from src.ui.dialogs.help_dialogs import MANUAL, ManualDialog
    html = open(MANUAL, encoding='utf-8').read()
    assert AUTHOR in html and LINKEDIN in html and 'IFCE' in html
    # o manual descreve o que existe; nada de "pendente"/"não implementado"
    low = html.lower()
    for word in ('pendente', 'não implementad', 'não suportad', 'main4', 'wntr', 'deap'):
        assert word not in low, word
    # todo link do sumário aponta para uma seção existente
    targets = set(re.findall(r'href="#([\w-]+)"', html))
    anchors = set(re.findall(r'<a name="([\w-]+)"', html))
    assert targets and targets <= anchors
    dlg = ManualDialog()
    text = dlg.browser.toPlainText()
    assert 'Otimização de diâmetros' in text and 'Planta de execução' in text
    assert dlg.browser.openExternalLinks()


def test_about_dialog(qapp):
    from PySide6.QtWidgets import QLabel
    from src.ui.dialogs.help_dialogs import AboutDialog
    dlg = AboutDialog()
    texts = ' '.join(l.text() for l in dlg.findChildren(QLabel))
    assert AUTHOR in texts and 'IFCE' in texts and 'Maracanaú' in texts
    assert f'https://www.{LINKEDIN}' in texts
    assert any(l.openExternalLinks() for l in dlg.findChildren(QLabel))
    assert any(not l.pixmap().isNull() for l in dlg.findChildren(QLabel))      # logo
