"""Exportação para DXF (ezdxf): geometria CAD nas camadas originais e a rede
hidráulica com simbologia, cada tipo de elemento na sua camada."""

from __future__ import annotations

import math

from ..hydraulics.project import Project
from . import geometry as G

UNITS_CODE = {'m': 6, 'mm': 4, 'cm': 5, 'km': 7, 'ft': 2, 'in': 1}


def _rgb(hexcolor: str):
    h = hexcolor.lstrip('#')
    if len(h) != 6:
        return None
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def export_dxf(project: Project, path: str, symbol_size: float = 2.0, include_cad: bool = True,
               include_labels: bool = True, extra_labels: dict | None = None,
               include_hidden: bool = False, flow_signs: dict | None = None):
    """flow_signs: uid -> +1/-1 (sentido da vazão calculada); gera as setas de escoamento."""
    doc = build_network_doc(project, symbol_size, include_cad, include_labels, extra_labels,
                            include_hidden, flow_signs)
    doc.saveas(path)
    return path


def build_network_doc(project: Project, symbol_size: float = 2.0, include_cad: bool = True,
                      include_labels: bool = True, extra_labels: dict | None = None,
                      include_hidden: bool = False, flow_signs: dict | None = None,
                      junction_symbols: bool = True):
    """Desenho com a geometria CAD e a rede (tubulações, símbolos, setas). Devolve o doc."""
    import ezdxf
    from ezdxf import colors

    doc = ezdxf.new('R2010', setup=True)
    doc.header['$INSUNITS'] = UNITS_CODE.get(project.settings.length_unit, 6)
    msp = doc.modelspace()

    def ensure_layer(name):
        if name not in doc.layers:
            l = project.layer_by_name(name)
            layer = doc.layers.add(name)
            if l is not None:
                rgb = _rgb(l.color)
                if rgb:
                    layer.rgb = rgb
                if not l.visible:
                    layer.off()
                if l.locked:
                    layer.lock()
        return name

    def attribs(e):
        a = {'layer': ensure_layer(e.layer or '0')}
        color = getattr(e, 'color', '')
        if color and _rgb(color):
            a['true_color'] = colors.rgb2int(_rgb(color))
        return a

    def visible(e):
        return include_hidden or project.layer_visible(e.layer)

    if include_cad:
        for e in project.cad.values():
            if not visible(e):
                continue
            a = attribs(e)
            if e.geom == 'line' and len(e.points) >= 2:
                msp.add_line((*e.points[0][:2], e.z), (*e.points[1][:2], e.z), dxfattribs=a)
            elif e.geom == 'polyline':
                pl = msp.add_lwpolyline([p[:2] for p in e.points], close=e.closed, dxfattribs=a)
                pl.dxf.elevation = e.z
            elif e.geom == 'circle':
                msp.add_circle((*e.points[0][:2], e.z), e.radius, dxfattribs=a)
            elif e.geom == 'arc':
                msp.add_arc((*e.points[0][:2], e.z), e.radius, e.start_angle, e.end_angle,
                            dxfattribs=a)
            elif e.geom == 'text':
                t = msp.add_text(e.text, dxfattribs=dict(a, height=e.height, rotation=e.rotation))
                t.set_placement(tuple(e.points[0][:2]))
            elif e.geom == 'point':
                msp.add_point((*e.points[0][:2], e.z), dxfattribs=a)
            elif e.geom == 'dimension' and len(e.points) >= 2:
                dim = msp.add_aligned_dim(p1=tuple(e.points[0][:2]), p2=tuple(e.points[1][:2]),
                                          distance=e.offset, dxfattribs=a)
                dim.render()

    net = project.network
    r = symbol_size
    label_layer = 'Rótulos da rede'
    arrow_layer = 'Setas de escoamento'
    existing_layer = 'Tubulações existentes'
    for l in net.links.values():
        if not visible(l):
            continue
        pts = net.link_points(l)
        if len(pts) < 2:
            continue
        a = attribs(l)
        if getattr(l, 'existing', False):
            # trechos existentes (executados): camada própria, linha tracejada
            if existing_layer not in doc.layers:
                base = project.layer_by_name(l.layer)
                lay = doc.layers.add(existing_layer, linetype='DASHED')
                rgb = _rgb(base.color) if base is not None else None
                if rgb:
                    lay.rgb = rgb
            a = dict(a, layer=existing_layer, linetype='BYLAYER', ltscale=r * 4)
        msp.add_lwpolyline(pts, dxfattribs=a)
        (mx, my), ang = G.point_at_fraction(pts, 0.5)
        if l.KIND == 'pump':
            msp.add_circle((mx, my), r, dxfattribs=a)
            ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
            tri = [(mx + r * ca, my + r * sa), (mx - r * 0.6 * ca - r * 0.6 * sa,
                                                my - r * 0.6 * sa + r * 0.6 * ca),
                   (mx - r * 0.6 * ca + r * 0.6 * sa, my - r * 0.6 * sa - r * 0.6 * ca)]
            msp.add_lwpolyline(tri, close=True, dxfattribs=a)
        elif l.KIND == 'valve':
            ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
            nx, ny = -sa, ca
            p1 = (mx - r * ca + r * nx, my - r * sa + r * ny)
            p2 = (mx - r * ca - r * nx, my - r * sa - r * ny)
            p3 = (mx + r * ca + r * nx, my + r * sa + r * ny)
            p4 = (mx + r * ca - r * nx, my + r * sa - r * ny)
            msp.add_lwpolyline([p1, p2, p3, p4], close=True, dxfattribs=a)
            msp.add_text(l.valve_type, dxfattribs=dict(a, height=r * 0.8)).set_placement(
                (mx + r * 1.2, my + r * 1.2))
        sign = (flow_signs or {}).get(l.uid, 0)
        if sign:
            (ax, ay), aang = G.point_at_fraction(pts, 0.5 if l.KIND == 'pipe' else 0.3)
            if sign < 0:
                aang += 180.0
            ca, sa = math.cos(math.radians(aang)), math.sin(math.radians(aang))
            s_ = r * 1.5
            tip = (ax + s_ * ca, ay + s_ * sa)
            back = (ax - s_ * 0.6 * ca, ay - s_ * 0.6 * sa)
            left = (back[0] - s_ * 0.5 * sa, back[1] + s_ * 0.5 * ca)
            right = (back[0] + s_ * 0.5 * sa, back[1] - s_ * 0.5 * ca)
            if arrow_layer not in doc.layers:
                doc.layers.add(arrow_layer, color=1)
            msp.add_solid([tip, left, right], dxfattribs={'layer': arrow_layer})
        if include_labels:
            txt = l.name
            if l.KIND == 'pipe':
                txt += f' DN{l.diameter:g}' + (' (existente)' if l.existing else '')
            if extra_labels and l.uid in extra_labels:
                txt += ' ' + extra_labels[l.uid]
            msp.add_text(txt, dxfattribs={'layer': ensure_layer(label_layer), 'height': r,
                                          'rotation': ang if -90 <= ang <= 90 else ang - 180}
                         ).set_placement((mx, my + r * 0.5))

    for n in net.nodes.values():
        if not visible(n):
            continue
        a = attribs(n)
        z = getattr(n, 'elevation', 0.0) or 0.0
        if n.KIND == 'junction' and junction_symbols:
            msp.add_circle((n.x, n.y, z), r * 0.6, dxfattribs=a)
            msp.add_point((n.x, n.y, z), dxfattribs=a)
        elif n.KIND == 'reservoir':
            msp.add_lwpolyline([(n.x - r * 1.5, n.y - r), (n.x + r * 1.5, n.y - r),
                                (n.x + r * 1.5, n.y + r), (n.x - r * 1.5, n.y + r)],
                               close=True, dxfattribs=a)
            msp.add_line((n.x - r, n.y + r * 0.3), (n.x + r, n.y + r * 0.3), dxfattribs=a)
        elif n.KIND == 'tank':
            msp.add_lwpolyline([(n.x - r, n.y - r * 1.5), (n.x + r, n.y - r * 1.5),
                                (n.x + r, n.y + r * 1.5), (n.x - r, n.y + r * 1.5)],
                               close=True, dxfattribs=a)
        if include_labels:
            txt = n.name
            if extra_labels and n.uid in extra_labels:
                txt += ' ' + extra_labels[n.uid]
            msp.add_text(txt, dxfattribs={'layer': ensure_layer(label_layer), 'height': r}
                         ).set_placement((n.x + r * 1.2, n.y + r * 1.2))
    return doc
