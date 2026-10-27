"""Tela de abertura: ciano, nome, subtítulo e crédito; dura ~2 s antes da janela principal."""


def test_splash_pixmap(qapp):
    from PySide6.QtGui import QColor
    from src.ui import splash
    pm = splash.splash_pixmap(1.0)
    assert (pm.width(), pm.height()) == (splash.WIDTH, splash.HEIGHT)
    assert pm.width() > pm.height()                                   # retangular
    img = pm.toImage()
    assert img.pixelColor(5, 5) == QColor('#0ABDDB')                   # fundo ciano
    # há texto branco na faixa do título e no canto inferior direito (crédito)
    def has_white(x0, y0, x1, y1):
        return any(img.pixelColor(x, y).lightness() > 200
                   for x in range(x0, x1, 2) for y in range(y0, y1, 2))
    assert has_white(240, 110, 560, 190)
    assert has_white(480, splash.HEIGHT - 34, splash.WIDTH - 18, splash.HEIGHT - 12)
    assert not has_white(10, splash.HEIGHT - 34, 200, splash.HEIGHT - 12)    # crédito só à direita


def test_startup_shows_splash_then_main_window(qapp, monkeypatch):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QSplashScreen
    from src import app as app_mod
    from src.ui.main_window import MainWindow
    seen = {}

    def tops(cls):
        return [w for w in QApplication.topLevelWidgets() if isinstance(w, cls) and w.isVisible()]

    def early():                       # 1 s depois: splash visível, janela ainda não
        seen['early'] = (bool(tops(QSplashScreen)), bool(tops(MainWindow)))

    def late():                        # 3 s depois: janela visível, splash fechada
        seen['late'] = (bool(tops(QSplashScreen)), bool(tops(MainWindow)))
        for w in tops(MainWindow):
            w.ctrl.mark_saved()
            w.close()
        QApplication.instance().quit()

    QTimer.singleShot(1000, early)
    QTimer.singleShot(3000, late)
    app_mod.run(['hidropy'])
    assert seen['early'] == (True, False)
    assert seen['late'] == (False, True)
