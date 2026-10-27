"""Relatórios em HTML (e PDF via Qt). Apenas apresentam dados existentes."""

from __future__ import annotations

import html

import pandas as pd

from ..hydraulics.project import now_iso
from ..hydraulics.validation import validate
from . import tables, thematic_views as TV

REPORTS = {
    'cadastro': 'Cadastro dos elementos',
    'resultados': 'Resultados hidráulicos (pressões, vazões, velocidades, perdas)',
    'otimizacao': 'Otimização de diâmetros',
    'restricoes': 'Restrições não atendidas',
    'validacao': 'Erros de validação',
    'populacao': 'Projeção populacional adotada',
}

CSS = """
body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 9pt; color: #111; }
h1 { font-size: 15pt; } h2 { font-size: 12pt; margin-top: 14px; border-bottom: 1px solid #999; }
table { border-collapse: collapse; margin: 4px 0 10px 0; }
th, td { border: 1px solid #aaa; padding: 2px 5px; }
th { background: #e8eef6; } .warn { color: #a00; } .muted { color: #666; }
"""


def _df_html(df: pd.DataFrame, max_rows=5000) -> str:
    if df is None or df.empty:
        return '<p class="muted">Sem dados.</p>'
    return df.head(max_rows).to_html(index=False, float_format=lambda v: f'{v:.3f}',
                                     na_rep='—', border=0)


def _header(project, title):
    p = project
    scen = p.scenario().name
    return (f'<h1>{html.escape(title)}</h1><p>Projeto: <b>{html.escape(p.meta.get("title", ""))}'
            f'</b> — cenário: <b>{html.escape(scen)}</b><br>Emitido em {now_iso()}</p>')


def _stale_note(ctrl, res):
    return ''


def build_report(ctrl, which: set[str], time_index: int = 0) -> str:
    p = ctrl.project
    parts = [f'<html><head><meta charset="utf-8"><style>{CSS}</style></head><body>',
             _header(p, 'Relatório — HidroPy')]
    sim = p.latest_result('simulation')
    opt = p.latest_result('optimization')
    if 'cadastro' in which:
        parts.append('<h2>Cadastro dos elementos</h2>')
        for kind, title in (('junction', 'Junções'), ('reservoir', 'Reservatórios'),
                            ('tank', 'Tanques'), ('pipe', 'Tubulações'), ('pump', 'Bombas'),
                            ('valve', 'Válvulas')):
            df = tables.elements_df(p, kind)
            if not df.empty:
                parts.append(f'<h3>{title} ({len(df)})</h3>' + _df_html(df))
    if 'resultados' in which:
        parts.append('<h2>Resultados hidráulicos</h2>')
        if not sim:
            parts.append('<p class="muted">Nenhuma simulação bem-sucedida neste cenário.</p>')
        else:
            times = sim.get('times', [0])
            ti = min(time_index, len(times) - 1)
            parts.append(_stale_note(ctrl, sim))
            parts.append(f'<p>Motor: {html.escape(sim.get("engine", ""))} — instante '
                         f'{times[ti] / 3600:.2f} h de {len(times)} — calculado em '
                         f'{sim["created"]}</p>')
            parts.append('<h3>Nós (pressões e cargas)</h3>' +
                         _df_html(tables.node_results_df(p, sim, ti)))
            parts.append('<h3>Ligações (vazões, velocidades e perdas de carga)</h3>' +
                         _df_html(tables.link_results_df(p, sim, ti)))
            if sim.get('warnings'):
                parts.append('<h3>Advertências do EPANET</h3><pre>' +
                             html.escape('\n'.join(sim['warnings'])) + '</pre>')
    if 'otimizacao' in which:
        parts.append('<h2>Otimização de diâmetros (main4.py)</h2>')
        if not opt:
            parts.append('<p class="muted">Nenhuma otimização bem-sucedida neste cenário.</p>')
        else:
            parts.append(_stale_note(ctrl, opt))
            s = opt.get('summary', {})
            rows = [('Custo da solução (R$)', s.get('custo')),
                    ('Custo da rede original pelo catálogo (R$)', s.get('custo_original')),
                    ('Solução viável', 'SIM' if s.get('viavel') else 'NÃO'),
                    ('Violação total (adimensional)', s.get('violacao')),
                    ('Nós abaixo do alvo / acima do máximo',
                     f"{s.get('n_p_baixa')} / {s.get('n_p_alta')}"),
                    ('Trechos acima da velocidade máxima', s.get('n_v_alta')),
                    ('Pressão mínima / máxima (m)',
                     f"{s.get('p_min', 0):.2f} / {s.get('p_max', 0):.2f}"),
                    ('Velocidade máxima (m/s)', f"{s.get('v_max', 0):.3f}"),
                    ('Faixa de DN usada pelo script', s.get('faixa_dn')),
                    ('Avaliações únicas (cache do GA)', s.get('avaliacoes_unicas'))]
            parts.append('<table>' + ''.join(
                f'<tr><th>{html.escape(str(a))}</th><td>{html.escape(str(b))}</td></tr>'
                for a, b in rows) + '</table>')
            n_ex, L_ex = tables.existing_summary(p)
            parts.append(f'<h3>Trechos existentes (executados) preservados: {n_ex} — '
                         f'{L_ex:,.1f} m</h3><p>Diâmetros mantidos pela otimização e fora do '
                         'custo (TRECHOS_FIXOS do main4.py).</p>' +
                         _df_html(tables.existing_pipes_df(p)))
            parts.append('<h3>Comparação por trecho</h3>' + _df_html(tables.optimization_df(p, opt)))
            parts.append('<h3>Pressões nodais</h3>' +
                         _df_html(tables.optimization_nodes_df(p, opt)))
    if 'restricoes' in which:
        parts.append('<h2>Restrições não atendidas</h2>')
        if not sim:
            parts.append('<p class="muted">Sem simulação.</p>')
        else:
            o = p.sim_options
            v = TV.violations(p, sim)
            net = p.network
            parts.append(_stale_note(ctrl, sim))
            parts.append(f'<p>Limites: pressão {o.pressure_min:g}–{o.pressure_max:g} m; '
                         f'velocidade ≤ {o.velocity_max:g} m/s (envoltória do período).</p>')
            for key, title in (('p_low', 'Pressão abaixo do mínimo'),
                               ('p_high', 'Pressão acima do máximo'),
                               ('v_high', 'Velocidade acima do máximo'),
                               ('v_low', 'Velocidade abaixo do mínimo'),
                               ('reverse', 'Inversão de sentido de escoamento')):
                names = [(net.nodes.get(u) or net.links.get(u)).name for u in v[key]]
                parts.append(f'<p><b>{title}:</b> {len(names)} ' +
                             (html.escape(', '.join(sorted(names))) if names else '') + '</p>')
            if opt:
                bad = [p.network.nodes[u].name for u, d in opt.get('junctions', {}).items()
                       if not d.get('ok_pressure') and u in p.network.nodes]
                parts.append(f'<p><b>Otimização — nós fora do alvo do script:</b> {len(bad)} '
                             + html.escape(', '.join(bad)) + '</p>')
    if 'populacao' in which:
        from ..hydraulics.population import METHODS, BASES
        parts.append('<h2>Projeção populacional</h2>')
        st = p.population_study()
        if st is None or st.ka is None:
            parts.append('<p class="muted">Nenhum estudo de projeção salvo no projeto.</p>')
        else:
            pop = f'{st.design_population:,.0f}'.replace(',', '.')
            parts.append(
                f'<p>Estudo: <b>{html.escape(st.name)}</b> — método adotado: '
                f'<b>{METHODS[st.adopted_method]}</b> — coeficientes a partir de '
                f'{BASES[st.base].lower()}.<br>Ka = {st.ka:.2f} hab/ano; Kg = {st.kg:.6f} /ano '
                f'({100 * st.growth_rate:.3f}% a.a.).<br><b>População de projeto em '
                f'{st.end_year}: {pop} hab</b></p>')
            parts.append('<h3>Censos</h3>' + _df_html(pd.DataFrame(
                [{'Ano': c[0], 'População (hab)': c[1]} for c in st.censuses])))
            parts.append('<h3>Projeção</h3>' + _df_html(pd.DataFrame(
                [{'Ano': r['ano'], 'Aritmético (hab)': round(r['aritmetico']),
                  'Geométrico (hab)': round(r['geometrico'])} for r in st.table])))
    if 'validacao' in which:
        parts.append('<h2>Validação do modelo</h2>')
        issues = validate(p)
        if not issues:
            parts.append('<p>Nenhum problema encontrado.</p>')
        else:
            df = pd.DataFrame([{'Tipo': i.severity, 'Código': i.code, 'Mensagem': i.message}
                               for i in issues])
            parts.append(_df_html(df))
    parts.append('</body></html>')
    return '\n'.join(parts)


def save_html(text: str, path: str):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def save_pdf(text: str, path: str):
    """Requer QGuiApplication ativa."""
    from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument
    from PySide6.QtCore import QMarginsF
    writer = QPdfWriter(path)
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Landscape,
                                     QMarginsF(12, 12, 12, 12), QPageLayout.Millimeter))
    writer.setResolution(110)
    doc = QTextDocument()
    doc.setHtml(text)
    doc.setPageSize(writer.pageLayout().paintRectPixels(writer.resolution()).size())
    doc.print_(writer)
