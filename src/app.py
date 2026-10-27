"""Criação da aplicação Qt."""

from __future__ import annotations

import logging
import os
import sys
import traceback

from PySide6.QtWidgets import QApplication, QMessageBox

from .utils.logging_setup import setup_logging

log = logging.getLogger(__name__)
ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', 'hidropy.ico')


def app_icon():
    from PySide6.QtGui import QIcon
    return QIcon(ICON) if os.path.exists(ICON) else QIcon()


def _install_translation(app):
    """Textos padrão do Qt (Sim/Não/Cancelar/Fechar/Salvar...) em português."""
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
    tr = QTranslator(app)
    path = QLibraryInfo.path(QLibraryInfo.TranslationsPath)
    if tr.load(QLocale('pt_BR'), 'qtbase', '_', path):
        app.installTranslator(tr)
        app._pt_translator = tr          # mantém a referência viva


def _excepthook(exc_type, exc, tb):
    text = ''.join(traceback.format_exception(exc_type, exc, tb))
    log.error('Exceção não tratada:\n%s', text)
    app = QApplication.instance()
    if app is not None:
        QMessageBox.critical(None, 'Erro inesperado',
                             f'{exc_type.__name__}: {exc}\n\nDetalhes gravados no log. O projeto '
                             'não foi salvo automaticamente; salve-o para não perder alterações.')


def run(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    setup_logging()
    sys.excepthook = _excepthook
    if sys.platform == 'win32':
        # ícone próprio na barra de tarefas também quando executado pelo python.exe
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('HidroPy.App')
        except Exception:
            pass
    app = QApplication.instance() or QApplication(argv)
    _install_translation(app)
    app.setApplicationName('HidroPy')
    app.setOrganizationName('HidroPy')
    app.setWindowIcon(app_icon())
    app.setStyle('Fusion')
    # tela de abertura: aparece antes de carregar a janela principal (importações pesadas)
    from PySide6.QtCore import QElapsedTimer, QTimer
    from .ui.splash import DURATION_MS, show_splash
    clock = QElapsedTimer()
    clock.start()
    splash = show_splash(app)
    from .ui.main_window import MainWindow
    win = MainWindow()

    def start():
        win.show()
        splash.finish(win)
        for arg in argv[1:]:
            low = arg.lower()
            if low.endswith('.shcad'):
                win.file_open(arg)
            elif low.endswith('.dxf'):
                win.import_dxf(arg)
            elif low.endswith('.inp'):
                win.import_inp(arg)
        log.info('Aplicação iniciada')

    # a splash fica 2 s no total (o tempo de carga da janela já conta)
    QTimer.singleShot(max(0, DURATION_MS - clock.elapsed()), start)
    return app.exec()
