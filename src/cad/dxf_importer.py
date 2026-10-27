"""Importação DXF (ezdxf) preservando coordenadas, camadas, cores e unidades.

Fluxo em duas etapas:
    info = inspect_dxf(path)          # camadas, contagens, unidades (para o diálogo)
    result = import_dxf(path, opts)   # entidades CadEntity + camadas

Nada é convertido em elemento hidráulico aqui (ver editing.cad_to_pipes).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from ..hydraulics.models import CadEntity, Layer

INSUNITS = {0: '', 1: 'in', 2: 'ft', 3: 'mi', 4: 'mm', 5: 'cm', 6: 'm', 7: 'km',
            8: 'µin', 9: 'mil', 10: 'yd', 14: 'dm'}
TO_METERS = {'in': 0.0254, 'ft': 0.3048, 'mi': 1609.344, 'mm': 0.001, 'cm': 0.01, 'm': 1.0,
             'km': 1000.0, 'yd': 0.9144, 'dm': 0.1}
SUPPORTED = {'LINE', 'LWPOLYLINE', 'POLYLINE', 'CIRCLE', 'ARC', 'TEXT', 'MTEXT', 'POINT',
             'INSERT', 'SPLINE', 'ELLIPSE', 'DIMENSION'}


@dataclass
class DxfInfo:
    path: str
    units: str
    version: str
    layers: dict = field(default_factory=dict)   # nome -> {'color', 'count', 'types'}
    extents: tuple | None = None


@dataclass
class DxfImportOptions:
    layers: set | None = None          # None = todas
    reference_layers: set = field(default_factory=set)
    lock_reference: bool = True
    scale: float = 1.0                 # 1.0 = preserva coordenadas originais
    explode_blocks: bool = True


@dataclass
class DxfImportResult:
    entities: list = field(default_factory=list)
    layers: list = field(default_factory=list)
    skipped: dict = field(default_factory=dict)  # tipo -> quantidade
    units: str = ''


def _aci_hex(aci: int) -> str:
    from ezdxf.colors import aci2rgb
    try:
        r, g, b = aci2rgb(abs(int(aci)))
    except Exception:
        return '#c8c8c8'
    if (r, g, b) == (255, 255, 255):
        return '#d0d0d0'      # branco do AutoCAD fica legível em fundo claro
    return f'#{r:02x}{g:02x}{b:02x}'


def _entity_color(ent) -> str:
    try:
        tc = ent.dxf.get('true_color')
        if tc is not None:
            return '#{:06x}'.format(int(tc) & 0xFFFFFF)
        c = ent.dxf.get('color', 256)
        if c in (0, 256):          # BYBLOCK / BYLAYER
            return ''
        return _aci_hex(c)
    except Exception:
        return ''


def inspect_dxf(path: str) -> DxfInfo:
    import ezdxf
    doc = ezdxf.readfile(path)
    units = INSUNITS.get(int(doc.header.get('$INSUNITS', 0)), '')
    info = DxfInfo(path=os.path.abspath(path), units=units, version=doc.dxfversion)
    for l in doc.layers:
        info.layers[l.dxf.name] = {'color': _aci_hex(l.dxf.get('color', 7)), 'count': 0,
                                   'types': {}}
    for ent in doc.modelspace():
        name = ent.dxf.get('layer', '0')
        d = info.layers.setdefault(name, {'color': '#c8c8c8', 'count': 0, 'types': {}})
        d['count'] += 1
        t = ent.dxftype()
        d['types'][t] = d['types'].get(t, 0) + 1
    try:
        from ezdxf import bbox
        ext = bbox.extents(doc.modelspace(), fast=True)
        if ext.has_data:
            info.extents = (ext.extmin.x, ext.extmin.y, ext.extmax.x, ext.extmax.y)
    except Exception:
        pass
    return info


def import_dxf(path: str, opts: DxfImportOptions | None = None) -> DxfImportResult:
    import ezdxf
    opts = opts or DxfImportOptions()
    doc = ezdxf.readfile(path)
    res = DxfImportResult(units=INSUNITS.get(int(doc.header.get('$INSUNITS', 0)), ''))
    s = float(opts.scale or 1.0)

    def P(v):
        return [float(v[0]) * s, float(v[1]) * s]

    used_layers: set[str] = set()

    def want(layer):
        return opts.layers is None or layer in opts.layers

    def add(ent, layer, **kw):
        e = CadEntity(layer=layer, color=_entity_color(ent), **kw)
        res.entities.append(e)
        used_layers.add(layer)

    def handle(ent, layer_override=None):
        t = ent.dxftype()
        layer = layer_override or ent.dxf.get('layer', '0')
        if not want(layer):
            return
        try:
            if t == 'LINE':
                a, b = ent.dxf.start, ent.dxf.end
                add(ent, layer, geom='line', points=[P(a), P(b)], z=float(a[2]))
            elif t == 'LWPOLYLINE':
                pts = [P(p) for p in ent.get_points('xy')]
                if len(pts) >= 2:
                    add(ent, layer, geom='polyline', points=pts, closed=bool(ent.closed),
                        z=float(ent.dxf.get('elevation', 0.0)))
            elif t == 'POLYLINE':
                verts = list(ent.points())
                pts = [P(v) for v in verts]
                if len(pts) >= 2:
                    add(ent, layer, geom='polyline', points=pts, closed=bool(ent.is_closed),
                        z=float(verts[0][2]) if verts else 0.0)
            elif t == 'CIRCLE':
                add(ent, layer, geom='circle', points=[P(ent.dxf.center)],
                    radius=float(ent.dxf.radius) * s, z=float(ent.dxf.center[2]))
            elif t == 'ARC':
                add(ent, layer, geom='arc', points=[P(ent.dxf.center)],
                    radius=float(ent.dxf.radius) * s, start_angle=float(ent.dxf.start_angle),
                    end_angle=float(ent.dxf.end_angle), z=float(ent.dxf.center[2]))
            elif t == 'TEXT':
                add(ent, layer, geom='text', points=[P(ent.dxf.insert)],
                    text=ent.dxf.get('text', ''), height=float(ent.dxf.get('height', 1.0)) * s,
                    rotation=float(ent.dxf.get('rotation', 0.0)), z=float(ent.dxf.insert[2]))
            elif t == 'MTEXT':
                add(ent, layer, geom='text', points=[P(ent.dxf.insert)], text=ent.plain_text(),
                    height=float(ent.dxf.get('char_height', 1.0)) * s,
                    rotation=float(ent.get_rotation()), z=float(ent.dxf.insert[2]))
            elif t == 'POINT':
                add(ent, layer, geom='point', points=[P(ent.dxf.location)],
                    z=float(ent.dxf.location[2]))
            elif t in ('SPLINE', 'ELLIPSE'):
                pts = [P(v) for v in ent.flattening(0.01 / s if s else 0.01)]
                if len(pts) >= 2:
                    add(ent, layer, geom='polyline', points=pts)
            elif t in ('INSERT', 'DIMENSION'):
                if not opts.explode_blocks and t == 'INSERT':
                    res.skipped[t] = res.skipped.get(t, 0) + 1
                    return
                for sub in ent.virtual_entities():
                    sub_layer = sub.dxf.get('layer', '0')
                    handle(sub, layer if sub_layer == '0' else None)
            else:
                res.skipped[t] = res.skipped.get(t, 0) + 1
        except Exception:
            res.skipped[t + ' (erro)'] = res.skipped.get(t + ' (erro)', 0) + 1

    for ent in doc.modelspace():
        handle(ent)

    for name in sorted(used_layers):
        try:
            dl = doc.layers.get(name)
            color = _aci_hex(dl.dxf.get('color', 7))
        except Exception:
            color = '#c8c8c8'
        ref = name in opts.reference_layers
        res.layers.append(Layer(name=name, color=color, reference=ref,
                                locked=ref and opts.lock_reference, source='dxf'))
    return res


def unit_scale(src_units: str, target: str = 'm') -> float:
    if not src_units or src_units not in TO_METERS:
        return 1.0
    return TO_METERS[src_units] / TO_METERS[target]

