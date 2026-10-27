"""Análise das conexões (peças) necessárias em cada junção e em cada vértice da rede.

Sem dependência de Qt nem de ezdxf: devolve uma lista de pontos (junções e vértices), cada
um com as peças, a posição e a rotação de cada bloco unifilar e os avisos.

Ângulos em graus, no sistema do modelo (anti-horário a partir do eixo +X).
Para cada tubulação, a direção num nó é a do primeiro segmento a partir do nó (considera
os vértices).

Regras:
  * grau 1 (ponta de rede) ............ CAP
  * grau 2 ............................ curva(s) pela deflexão; redução se os DN diferem
  * grau 3 ............................ tê: o par mais alinhado é a passagem (run), o outro
                                         trecho é a derivação; curva na derivação se ela não
                                         sai a 90°; curva num braço da passagem se ela não é
                                         reta; reduções nos braços de DN menor
  * grau 4 ............................ cruzeta se os trechos formam dois pares alinhados;
                                         senão "verificar"
  * vértices de tubulação ............. curva(s) pela deflexão do vértice
  * deflexão ≤ tolerância ............. absorvida pela junta, sem peça
  * curvas comerciais 90°, 45°, 22°30', 11°15' (até duas combinadas)
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

from ..hydraulics.models import Junction, Pipe

# nome do bloco, ângulo de deflexão, comprimento do braço (unidades do bloco)
CURVES = [
    ('UN1-CU5', 90.0, "90°", 4.245),
    ('UN1-CU6', 45.0, "45°", 2.939),
    ('UN1-CU7', 22.5, "22°30'", 2.188),
    ('UN1-CU8', 11.25, "11°15'", 1.551),
]
TEE_BLOCK, TEE_ARM = 'UN1-TE2', 3.867
CROSS_BLOCK, CROSS_ARM = 'UN1-CR1', 3.899
CAP_BLOCK = 'UN1-CAP'
RED_BLOCK, RED_ARM = 'UN1-RE5', 3.8

DEFAULT_DNS = [32, 40, 50, 60, 75, 85, 100, 110, 125, 150, 200, 250, 300, 350, 400, 450, 500,
               600, 700, 800, 900, 1000]


def norm(a: float) -> float:
    return a % 360.0


def diff(a: float, b: float) -> float:
    """Menor diferença angular |a - b| em [0, 180]."""
    d = abs(norm(a) - norm(b)) % 360.0
    return 360.0 - d if d > 180.0 else d


def ccw(a: float, b: float) -> float:
    """Ângulo anti-horário de a até b, em [0, 360)."""
    return norm(b - a)


def unit(a: float):
    r = math.radians(a)
    return math.cos(r), math.sin(r)


def angle_of(p, q) -> float:
    return math.degrees(math.atan2(q[1] - p[1], q[0] - p[0]))


@dataclass
class Piece:
    kind: str                 # curva, te, cruzeta, cap, reducao
    label: str                # texto da chamada (sem quantidade)
    block: str
    x: float
    y: float
    rotation: float           # graus
    ends: str = ''            # BB, BP, BBB...
    dn: str = ''              # "100" ou "150x100"
    material: str = ''
    angle: float | None = None   # deflexão da curva
    mirror: bool = False         # bloco espelhado (escala Y negativa)

    @property
    def key(self) -> str:
        return self.label


@dataclass
class FittingPoint:
    kind: str                 # 'junction' | 'vertex'
    name: str                 # nome da junção ou "P12 (vértice 2)"
    x: float
    y: float
    uid: str = ''
    pieces: list = field(default_factory=list)
    warnings: list = field(default_factory=list)      # texto completo (revisão na tela)
    short: list = field(default_factory=list)         # texto curto (chamada no desenho)
    directions: list = field(default_factory=list)   # direções dos trechos (para a chamada)


@dataclass
class FittingOptions:
    tolerance: float = 3.0            # deflexão absorvida pela junta (graus)
    curve_ends: str = 'auto'          # 'auto' | 'BB' | 'BP' (ver END_MODES)
    vertex_bends: bool = True
    caps: bool = True
    min_segment: float = 0.5          # m: vértices mais próximos que isso são unidos
    dns: list = field(default_factory=lambda: list(DEFAULT_DNS))


# ---------------------------------------------------------------------------------- utilidades
def nominal_dn(diameter_mm: float, project=None, dns=None) -> int:
    """DN comercial: o DN do catálogo cujo diâmetro de cálculo coincide; senão o DN mais
    próximo da lista."""
    if project is not None:
        for dn, d_m, _ in project.opt_settings.catalogo_completo:
            if abs(d_m * 1000.0 - diameter_mm) < 0.6:
                return int(dn)
    lst = dns or DEFAULT_DNS
    return int(min(lst, key=lambda d: abs(d - diameter_mm)))


def best_curves(deflection: float, tol: float):
    """Combinação de até duas curvas comerciais mais próxima da deflexão.

    Devolve (lista de curvas, resíduo). Lista vazia se a deflexão ≤ tolerância.
    """
    if deflection <= tol:
        return [], deflection
    # dentro da tolerância: menos peças e depois menor erro; fora dela: menor erro
    # ("sem peça" também é candidato, com erro igual à própria deflexão)
    best = ((True, 0, deflection), [], deflection)
    for n in (1, 2):
        for combo in itertools.combinations_with_replacement(CURVES, n):
            err = abs(deflection - sum(c[1] for c in combo))
            ok = err <= tol + 1e-9
            key = (not ok, n if ok else 0, err)
            if key < best[0]:
                best = (key, list(combo), err)
    return best[1], best[2]


END_MODES = {
    'auto': 'Automático: bolsa junto aos tubos; ponta onde a peça encaixa em outra peça',
    'BB': 'Todas as curvas e reduções bolsa / bolsa',
    'BP': 'Todas as curvas bolsa / ponta',
}


def spigot_placement(back: float, fwd: float, curve_deflection: float) -> tuple[float, bool]:
    """(rotação, espelhar) do bloco BP para a PONTA (braço 2) ficar na direção `back` e a
    bolsa (braço 1, a -X no bloco) na direção `fwd`.

    No bloco o braço 2 está a θ = 180 - δ no sentido anti-horário do braço 1; espelhado
    (escala Y negativa), fica a θ no sentido horário."""
    theta = 180.0 - curve_deflection
    r = norm(fwd - 180.0)
    mirror = diff(ccw(fwd, back), theta) > diff(ccw(back, fwd), theta)
    return r, mirror


def curve_rotation(d1: float, d2: float, curve_deflection: float) -> float:
    """Rotação do bloco de curva cujos braços (no bloco) estão a 180° e 180°+θ, θ = 180 - δ,
    para que fiquem nas direções d1 e d2 (direções que saem do ponto)."""
    theta = 180.0 - curve_deflection
    if diff(ccw(d1, d2), theta) <= diff(ccw(d2, d1), theta):
        return norm(d1 - 180.0)
    return norm(d2 - 180.0)


def _warn(fp, long: str, short: str):
    fp.warnings.append(long)
    fp.short.append(short)


def _deg(v: float) -> str:
    return f'{v:.1f}'.replace('.', ',') + '°'


def _dm(v: float) -> str:
    """Ângulo de peça em graus e minutos (11°15', 33°45', 45°)."""
    d = int(v)
    m = round((v - d) * 60)
    return f"{d}°{m:02d}'" if m else f'{d}°'


def _dn_txt(a, b=None):
    return f'DN{a}' if b is None or a == b else f'DN{a}x{b}'


# ---------------------------------------------------------------------------------- peças
class _Builder:
    def __init__(self, project, opts: FittingOptions, scale: float):
        self.p = project
        self.o = opts
        self.s = scale

    def dn(self, pipe) -> int:
        return nominal_dn(pipe.diameter, self.p, self.o.dns)

    def curve(self, fp, x, y, d1, d2, curve, material, dn, spigot_back=False):
        """d1 = braço que volta (de onde se vem), d2 = braço que segue.
        spigot_back: a curva encaixa, pelo braço d1, na bolsa de outra peça."""
        block, defl, txt, _ = curve
        mode = self.o.curve_ends
        mirror = False
        if mode == 'auto' and spigot_back:
            ends, name = 'BP', block + '-BP'
            rot, mirror = spigot_placement(d1, d2, defl)
        elif mode == 'BP':
            ends, name, rot = 'BP', block + '-BP', curve_rotation(d1, d2, defl)
        else:
            ends, name, rot = 'BB', block, curve_rotation(d1, d2, defl)
        fp.pieces.append(Piece('curva', f'CURVA {txt} {ends} {material} DN{dn}', name, x, y,
                               rot, ends, str(dn), material, defl, mirror))

    def curves_between(self, fp, x, y, d_in, d_out, material, dn, lead=0.0) -> float:
        """Curvas para ir da direção d_in (braço que volta) para d_out (seguir).

        lead = 0: a primeira curva fica no próprio ponto (x, y). lead > 0: a primeira curva é
        encaixada a essa distância (ponta do braço da peça anterior), bolsa com bolsa.
        Devolve a distância ocupada a partir de (x, y) (0 se não houver curva).
        """
        travel = norm(d_in + 180.0)
        defl = diff(travel, d_out)
        curves, err = best_curves(defl, self.o.tolerance)
        if not curves:
            if defl > self.o.tolerance:
                _warn(fp, f'Deflexão de {defl:.1f}° acima da tolerância da junta e abaixo da '
                          'menor curva: verificar (sem peça).',
                      f'VERIFICAR: deflexão {_deg(defl)} sem peça')
            return 0.0
        sign = 1.0 if ccw(travel, d_out) <= 180.0 else -1.0
        if err > self.o.tolerance:
            tot = sum(c[1] for c in curves)
            _warn(fp, f'Deflexão de {defl:.1f}° sem combinação comercial exata (adotado '
                      f'{tot:g}°, resíduo {err:.1f}°).',
                  f'VERIFICAR: deflexão {_deg(defl)} (adotado {_dm(tot)})')
        s = self.s
        heading = travel
        ux, uy = unit(travel)
        if lead > 0:
            used = lead + curves[0][3] * s
            cx, cy = x + ux * used, y + uy * used
        else:
            used, cx, cy = 0.0, x, y
        prev_arm = curves[0][3]
        for k, c in enumerate(curves):
            if k > 0:
                ux, uy = unit(heading)
                step = (prev_arm + c[3]) * s
                cx, cy = cx + ux * step, cy + uy * step
                used += step
            new_heading = norm(heading + sign * c[1])
            # a 1ª curva encaixa na peça anterior se houver uma (lead > 0); as seguintes
            # sempre encaixam na curva anterior
            self.curve(fp, cx, cy, norm(heading + 180.0), new_heading, c, material, dn,
                       spigot_back=(k > 0 or lead > 0))
            heading, prev_arm = new_heading, c[3]
        return used + prev_arm * s

    def reduction(self, fp, x, y, d_small, dn_big, dn_small, material, gap, spigot=False):
        """Redução com o lado maior voltado para (x, y). spigot: o lado maior encaixa na
        bolsa de outra peça => ponta no lado maior (RED. BP)."""
        ux, uy = unit(d_small)
        bp = spigot and self.o.curve_ends == 'auto'
        ends = 'BP' if bp else 'BB'
        fp.pieces.append(Piece('reducao', f'RED. {ends} {material} DN{dn_big}x{dn_small}',
                               RED_BLOCK + ('-BP' if bp else ''), x + ux * gap, y + uy * gap,
                               norm(d_small), ends, f'{dn_big}x{dn_small}', material))


def clean_points(pts, min_seg: float) -> list:
    """[(ponto, índice original)] sem os vértices a menos de `min_seg` do ponto anterior.

    Extremidades (nós) são mantidas exatas. Assim, um vértice coincidente com o nó ou
    segmentos de poucos centímetros (comuns em redes digitalizadas) não geram dobras
    falsas: a deflexão é medida entre segmentos de comprimento real.
    """
    if len(pts) < 2:
        return [(p, i) for i, p in enumerate(pts)]
    min_seg = max(min_seg, 1e-6)
    kept = [(pts[0], 0)]
    for i in range(1, len(pts) - 1):
        if math.dist(kept[-1][0], pts[i]) >= min_seg:
            kept.append((pts[i], i))
    end = (pts[-1], len(pts) - 1)
    while len(kept) > 1 and math.dist(kept[-1][0], end[0]) < min_seg:
        kept.pop()
    kept.append(end)
    return kept


def _arms(project, node_uid, min_seg: float = 0.5):
    """[(direção, tubulação)] dos trechos ligados ao nó."""
    net = project.network
    out = []
    for l in net.links_of_node(node_uid):
        if not isinstance(l, Pipe):
            continue
        pts = net.link_points(l)
        if len(pts) < 2:
            continue
        seq = [q for q, _ in clean_points(pts if l.start == node_uid else pts[::-1], min_seg)]
        a, b = seq[0], seq[1]
        if math.dist(a, b) <= 1e-9:
            continue
        out.append((angle_of(a, b), l))
    return out


def _material(pipes):
    mats = sorted({(l.material or 'PVC').strip().upper() for l in pipes})
    return mats


def analyze_junction(project, node, opts: FittingOptions, scale: float) -> FittingPoint:
    b = _Builder(project, opts, scale)
    net = project.network
    fp = FittingPoint('junction', node.name, node.x, node.y, node.uid)
    arms = _arms(project, node.uid, opts.min_segment)
    fp.directions = [a for a, _ in arms]
    others = [l for l in net.links_of_node(node.uid) if not isinstance(l, Pipe)]
    for l in others:
        tipo = 'bomba' if l.KIND == 'pump' else 'válvula'
        _warn(fp, f"Ligação com {tipo} '{l.name}': prever peças flangeadas.",
              f'PREVER FLANGES ({tipo} {l.name})')
    mats = _material([l for _, l in arms])
    if len(mats) > 1:
        _warn(fp, f"Materiais diferentes ({'/'.join(mats)}): prever adaptador.",
              f"PREVER ADAPTADOR {'/'.join(mats)}")
    mat = mats[0] if mats else 'PVC'
    x, y = node.x, node.y
    n = len(arms)
    if n == 0:
        return fp
    if n == 1:
        if opts.caps and not others:
            d, pipe = arms[0]
            dn = b.dn(pipe)
            fp.pieces.append(Piece('cap', f'CAP {mat} DN{dn}', CAP_BLOCK, x, y,
                                   norm(d - 180.0), 'B', str(dn), mat))
        return fp
    if n == 2:
        (d1, p1), (d2, p2) = arms
        dn1, dn2 = b.dn(p1), b.dn(p2)
        dn_c = max(dn1, dn2)
        used = b.curves_between(fp, x, y, d1, d2, mat, dn_c)
        if dn1 != dn2:
            d_small, big, small = (d2, dn1, dn2) if dn2 < dn1 else (d1, dn2, dn1)
            gap = 0.0 if used == 0 else used + RED_ARM * scale
            b.reduction(fp, x, y, d_small, big, small, mat, gap, spigot=used > 0)
        return fp
    if n == 3:
        pairs = list(itertools.combinations(range(3), 2))
        i, j = min(pairs, key=lambda ij: abs(180.0 - diff(arms[ij[0]][0], arms[ij[1]][0])))
        k = ({0, 1, 2} - {i, j}).pop()
        (da, pa), (db, pb), (dc, pc) = arms[i], arms[j], arms[k]
        run_dev = 180.0 - diff(da, db)
        dna, dnb, dnc = b.dn(pa), b.dn(pb), b.dn(pc)
        run_dn = max(dna, dnb)
        tee_run, tee_branch = (run_dn, dnc) if dnc <= run_dn else (dnc, dnc)
        r = norm(da) if ccw(da, dc) <= 180.0 else norm(da + 180.0)
        fp.pieces.append(Piece('te', f'TÊ BBB {mat} {_dn_txt(tee_run, tee_branch)}', TEE_BLOCK,
                               x, y, r, 'BBB', f'{tee_run}x{tee_branch}', mat))
        arm = TEE_ARM * scale
        # derivação: sai do tê a r + 90°
        branch_dir = norm(r + 90.0)
        used = {'a': arm, 'b': arm, 'c': arm}
        if diff(branch_dir, dc) > opts.tolerance:
            used['c'] = b.curves_between(fp, x, y, norm(branch_dir + 180), dc, mat, dnc,
                                         lead=arm) or arm
        # passagem não alinhada: curva no braço b (o braço a define a rotação do tê)
        if run_dev > opts.tolerance:
            out_dir = norm(da + 180.0)
            used['b'] = b.curves_between(fp, x, y, norm(out_dir + 180), db, mat, dnb,
                                         lead=arm) or arm
        red = RED_ARM * scale
        for key, d, dn_arm in (('a', da, dna), ('b', db, dnb)):
            if dn_arm < tee_run:
                b.reduction(fp, x, y, d, tee_run, dn_arm, mat, used[key] + red, spigot=True)
        if dnc < tee_branch:
            b.reduction(fp, x, y, dc, tee_branch, dnc, mat, used['c'] + red, spigot=True)
        return fp
    if n == 4:
        idx = range(4)
        best = None
        for (i, j) in itertools.combinations(idx, 2):
            k, m = sorted(set(idx) - {i, j})
            dev = abs(180 - diff(arms[i][0], arms[j][0])) + abs(180 - diff(arms[k][0], arms[m][0]))
            if best is None or dev < best[0]:
                best = (dev, (i, j), (k, m))
        dev, (i, j), (k, m) = best
        if dev > 2 * opts.tolerance + 1e-9:
            _warn(fp, 'Quatro trechos sem dois alinhamentos: definir as peças manualmente '
                      '(sugestão: dois tês).', 'VERIFICAR: definir peças (4 trechos)')
            return fp
        dn = [b.dn(l) for _, l in arms]
        A, B = max(dn[i], dn[j]), max(dn[k], dn[m])
        if B > A:
            (i, j, A), (k, m, B) = (k, m, B), (i, j, A)
        r = norm(arms[i][0])
        fp.pieces.append(Piece('cruzeta', f'CRUZETA BBBB {mat} {_dn_txt(A, B)}', CROSS_BLOCK,
                               x, y, r, 'BBBB', f'{A}x{B}', mat))
        arm = CROSS_ARM * scale
        for q, big in ((i, A), (j, A), (k, B), (m, B)):
            if dn[q] < big:
                b.reduction(fp, x, y, arms[q][0], big, dn[q], mat, arm + RED_ARM * scale,
                            spigot=True)
        return fp
    _warn(fp, f'{n} trechos ligados no mesmo ponto: definir as peças manualmente.',
          f'VERIFICAR: definir peças ({n} trechos)')
    return fp


def analyze_vertices(project, pipe, opts: FittingOptions, scale: float) -> list:
    b = _Builder(project, opts, scale)
    pts = clean_points(project.network.link_points(pipe), opts.min_segment)
    out = []
    mat = (pipe.material or 'PVC').strip().upper()
    dn = b.dn(pipe)
    for k in range(1, len(pts) - 1):
        (prev, _), (cur, idx), (nxt, _) = pts[k - 1], pts[k], pts[k + 1]
        fp = FittingPoint('vertex', f'{pipe.name} (vértice {idx})', cur[0], cur[1], pipe.uid)
        d_back, d_fwd = angle_of(cur, prev), angle_of(cur, nxt)
        fp.directions = [d_back, d_fwd]
        if b.curves_between(fp, cur[0], cur[1], d_back, d_fwd, mat, dn) > 0:
            out.append(fp)
    return out


def analyze_network(project, opts: FittingOptions | None = None, scale: float = 1.0) -> list:
    """Analisa todas as junções (e vértices, se habilitado). Ordena por nome."""
    opts = opts or FittingOptions()
    net = project.network
    pts = [analyze_junction(project, n, opts, scale) for n in net.nodes.values()
           if isinstance(n, Junction)]
    if opts.vertex_bends:
        for l in net.links.values():
            if isinstance(l, Pipe) and l.vertices:
                pts += analyze_vertices(project, l, opts, scale)
    return pts


def quantities(points) -> dict:
    """Quantitativo: rótulo da peça -> quantidade."""
    q: dict[str, int] = {}
    for fp in points:
        for pc in fp.pieces:
            q[pc.label] = q.get(pc.label, 0) + 1
    return dict(sorted(q.items()))


def callout_direction(directions) -> float:
    """Bissetriz da maior abertura entre os trechos (onde a chamada atrapalha menos)."""
    if not directions:
        return 45.0
    ds = sorted(norm(d) for d in directions)
    if len(ds) == 1:
        return norm(ds[0] + 180.0 - 45.0)
    gaps = [(ccw(ds[i], ds[(i + 1) % len(ds)]) or 360.0, ds[i]) for i in range(len(ds))]
    g, start = max(gaps)
    return norm(start + g / 2.0)
