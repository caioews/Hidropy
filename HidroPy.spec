# -*- mode: python ; coding: utf-8 -*-
# Executável Windows (pasta única):  python -m PyInstaller --noconfirm HidroPy.spec
# Saída: dist/HidroPy/HidroPy.exe
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [('main4.py', '.'),     # motor original, lido como texto pelo trabalhador de otimização
         ('src/cad/resources/conexoes.dxf', 'src/cad/resources'),   # blocos de conexões
         ('src/resources/hidropy.ico', 'src/resources'),           # ícone da janela
         ('src/resources/hidropy_logo.png', 'src/resources'),      # símbolo da splash
         ('src/resources/hidropy.png', 'src/resources'),           # logo da janela Sobre
         ('src/resources/manual.html', 'src/resources')]           # manual do usuário
binaries = []
hiddenimports = ['openpyxl']

# wntr: binários EPANET (epanet/Windows/*.dll) e dados; deap: o main4.py é executado a partir
# do código-fonte (exec), então os módulos que ele importa precisam estar no pacote.
for pkg in ('wntr', 'deap'):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
hiddenimports += collect_submodules('ezdxf')
# módulos da biblioteca padrão usados apenas pelo main4.py
hiddenimports += ['atexit', 'random', 'shutil', 'tempfile', 'warnings']

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtQuick',
              'PySide6.QtQml', 'PySide6.Qt3DCore', 'tkinter', 'pytest', 'IPython'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='HidroPy',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon='src/resources/hidropy.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='HidroPy',
)
