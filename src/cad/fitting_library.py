"""Biblioteca de blocos unifilares das conexões.

A biblioteca do programa (resources/conexoes.dxf) é gerada a partir do desenho de conexões
fornecido pelo usuário (CONEXÕES.dxf, todas bolsa/bolsa), acrescentando as variantes
bolsa/ponta das curvas (sufixo -BP). As entidades dos blocos vão para a camada 0 para
herdarem a camada e a cor do bloco inserido.

    python -m src.cad.fitting_library "C:/.../CONEXÕES.dxf"    # regenera a biblioteca
"""

from __future__ import annotations

import math
import os
import sys

RESOURCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', 'conexoes.dxf')
REQUIRED = ['UN1-CU5', 'UN1-CU6', 'UN1-CU7', 'UN1-CU8', 'UN1-TE2', 'UN1-CR1', 'UN1-CAP',
            'UN1-RE5']
CURVE_BLOCKS = ['UN1-CU5', 'UN1-CU6', 'UN1-CU7', 'UN1-CU8']
SOCKET_R = 1.088


def library_path(custom: str = '') -> str:
    if custom and os.path.exists(custom):
        return custom
    return RESOURCE


def _make_bp(doc, name):
    """Copia a curva BB e troca a bolsa do 2º braço por ponta (trecho reto até o eixo)."""
    src = doc.blocks[name]
    dst = doc.blocks.new(name + '-BP', base_point=src.block.dxf.base_point)
    sockets = [e for e in src if e.dxftype() == 'ARC' and abs(e.dxf.radius - SOCKET_R) < 0.01]
    # braço 1 fica no eixo -X (centro com y≈0 e x<0); o outro é o braço 2
    arm2 = next(e for e in sockets if not (abs(e.dxf.center.y) < 1e-6 and e.dxf.center.x < 0))
    body = max((e for e in src if e.dxftype() == 'ARC'), key=lambda e: e.dxf.radius)
    c2 = (arm2.dxf.center.x, arm2.dxf.center.y)
    ends = [body.start_point, body.end_point]
    near = min(ends, key=lambda p: math.dist((p.x, p.y), c2))
    for e in src:
        if e is arm2:
            continue
        dst.add_entity(e.copy())
    dst.add_line((near.x, near.y), c2, dxfattribs={'layer': '0'})


def _make_reduction_bp(doc, name='UN1-RE5'):
    """Redução com PONTA no lado maior (encaixa na bolsa de outra peça) e bolsa no menor."""
    src = doc.blocks[name]
    dst = doc.blocks.new(name + '-BP', base_point=src.block.dxf.base_point)
    big = max((e for e in src if e.dxftype() == 'ARC'), key=lambda e: e.dxf.radius)
    lines = [e for e in src if e.dxftype() == 'LINE']
    ends = [min((e.dxf.start, e.dxf.end), key=lambda p: p.x) for e in lines]
    for e in src:
        if e is not big:
            dst.add_entity(e.copy())
    (x1, y1), (x2, y2) = (ends[0].x, ends[0].y), (ends[1].x, ends[1].y)
    dst.add_line((x1, y1), (x2, y2), dxfattribs={'layer': '0'})           # face da ponta
    cx = big.dxf.center.x
    dst.add_line(((x1 + x2) / 2, (y1 + y2) / 2), (cx, 0.0), dxfattribs={'layer': '0'})


def build_library(source: str, dest: str = RESOURCE) -> str:
    import ezdxf
    from ezdxf.addons import Importer
    src = ezdxf.readfile(source)
    missing = [b for b in REQUIRED if b not in src.blocks]
    if missing:
        raise ValueError(f'Blocos ausentes no desenho de conexões: {missing}')
    doc = ezdxf.new('R2010')
    doc.header['$INSUNITS'] = 6
    imp = Importer(src, doc)
    for b in REQUIRED:
        imp.import_block(b)
    imp.finalize()
    for b in REQUIRED:
        for e in doc.blocks[b]:
            e.dxf.layer = '0'
            e.dxf.color = 0          # BYBLOCK: herda a cor do bloco inserido
    for b in CURVE_BLOCKS:
        _make_bp(doc, b)
    _make_reduction_bp(doc)
    for b in CURVE_BLOCKS + ['UN1-RE5']:
        for e in doc.blocks[b + '-BP']:
            e.dxf.layer = '0'
            e.dxf.color = 0
    # folha de referência com todas as peças (para conferência visual)
    msp = doc.modelspace()
    names = REQUIRED + [b + '-BP' for b in CURVE_BLOCKS + ['UN1-RE5']]
    for k, b in enumerate(names):
        msp.add_blockref(b, (k * 12.0, 0))
        msp.add_text(b, dxfattribs={'height': 1.0}).set_placement((k * 12.0 - 4, 6))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    doc.saveas(dest)
    return dest


def import_blocks(dst_doc, path: str = ''):
    """Importa os blocos de conexão para o desenho de destino."""
    import ezdxf
    from ezdxf.addons import Importer
    lib = ezdxf.readfile(library_path(path))
    imp = Importer(lib, dst_doc)
    for b in lib.blocks:
        if b.name.startswith('UN1-') and b.name not in dst_doc.blocks:
            imp.import_block(b.name)
    imp.finalize()


if __name__ == '__main__':
    print(build_library(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else RESOURCE))
