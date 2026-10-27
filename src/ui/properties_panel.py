"""Painel de propriedades: editores gerados a partir de hydraulics.schema.

Seleção múltipla do mesmo tipo => edição em lote das propriedades compatíveis.
Resultados (somente leitura) do instante selecionado aparecem em seção própria.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGroupBox, QLabel, QLineEdit,
                               QMessageBox, QScrollArea, QVBoxLayout, QWidget)

from ..hydraulics.models import KIND_LABELS
from ..hydraulics.schema import (props_for, parse_value, format_demand_cats,
                                 parse_demand_cats)
from ..results import thematic_views as TV
from .guards import confirm_existing_diameter

MIXED = '‹vários›'


class PropertiesPanel(QWidget):
    def __init__(self, controller, canvas, parent=None):
        super().__init__(parent)
        self.ctrl = controller
        self.canvas = canvas
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.scroll)
        self.ctrl.selectionChanged.connect(lambda *_: self.rebuild())
        self.ctrl.elementsChanged.connect(self._on_changed)
        self.ctrl.resultsChanged.connect(self.rebuild)
        self.ctrl.projectReplaced.connect(self.rebuild)
        self._building = False
        self.rebuild()

    def _on_changed(self, cs):
        if set(self.ctrl.selection) & cs.all:
            self.rebuild()

    # ------------------------------------------------------------------
    def rebuild(self):
        self._building = True
        host = QWidget()
        v = QVBoxLayout(host)
        elems = self.ctrl.selected_elements()
        if not elems:
            v.addWidget(QLabel('Nenhum elemento selecionado.'))
            v.addStretch()
            self.scroll.setWidget(host)
            self._building = False
            return
        kinds = {e.KIND for e in elems}
        if len(kinds) > 1:
            counts = {}
            for e in elems:
                counts[e.KIND] = counts.get(e.KIND, 0) + 1
            v.addWidget(QLabel(f'<b>{len(elems)} elementos</b><br>' + '<br>'.join(
                f'{KIND_LABELS[k]}: {n}' for k, n in counts.items())))
            box = QGroupBox('Propriedades comuns')
            form = QFormLayout(box)
            self._add_layer_editor(form, elems)
            v.addWidget(box)
            v.addStretch()
            self.scroll.setWidget(host)
            self._building = False
            return

        e0 = elems[0]
        title = (f'<b>{KIND_LABELS[e0.KIND]} {e0.name}</b>' if len(elems) == 1 else
                 f'<b>{len(elems)} × {KIND_LABELS[e0.KIND]}</b> — edição em lote')
        v.addWidget(QLabel(title))
        box = QGroupBox('Dados')
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignRight)
        props = props_for(e0)
        if e0.KIND == 'cad':
            # todas as entidades selecionadas precisam ter a mesma geometria
            if len({e.geom for e in elems}) > 1:
                props = [p for p in props if p.key in ('layer', 'color', 'notes')]
        for prop in props:
            if len(elems) > 1 and not prop.batch:
                continue
            self._add_editor(form, prop, elems)
        v.addWidget(box)
        if len(elems) == 1:
            self._add_results(v, e0)
        v.addStretch()
        self.scroll.setWidget(host)
        self._building = False

    def _value(self, e, key):
        if key == 'geom_length':
            return self.ctrl.project.network.geometric_length(e)
        return getattr(e, key, None)

    def _common(self, elems, key):
        vals = [self._value(e, key) for e in elems]
        return vals[0] if all(v == vals[0] for v in vals) else MIXED

    def _add_layer_editor(self, form, elems):
        cb = QComboBox()
        names = [l.name for l in self.ctrl.project.layers.values()]
        cur = self._common(elems, 'layer')
        if cur == MIXED:
            cb.addItem(MIXED)
        cb.addItems(names)
        cb.setCurrentText(cur)
        cb.currentTextChanged.connect(lambda t: t != MIXED and self._commit(elems, 'layer', t))
        form.addRow('Camada', cb)

    def _name_of(self, uid):
        e = self.ctrl.project.get(uid) if uid else None
        return e.name if e is not None else ''

    def _add_editor(self, form, prop, elems):
        net = self.ctrl.project.network
        val = self._common(elems, prop.key)
        label = prop.label + (f' ({prop.unit})' if prop.unit else '')
        w = None
        if prop.type == 'computed':
            text = val if isinstance(val, str) else ('' if val is None else f'{val:.3f}')
            w = QLabel(text)
        elif prop.type == 'bool':
            w = QCheckBox()
            if val == MIXED:
                w.setTristate(True)
                w.setCheckState(Qt.PartiallyChecked)
            else:
                w.setChecked(bool(val))
            w.clicked.connect(lambda checked, p=prop: self._commit(elems, p.key, bool(checked)))
        elif prop.type in ('choice', 'layer', 'ref_node', 'ref_link', 'ref_pattern', 'ref_curve'):
            w = QComboBox()
            if prop.type == 'choice':
                options = [(c, c) for c in prop.choices]
            elif prop.type == 'layer':
                options = [(l.name, l.name) for l in self.ctrl.project.layers.values()]
            else:
                store = {'ref_node': net.nodes, 'ref_link': net.links,
                         'ref_pattern': net.patterns, 'ref_curve': net.curves}[prop.type]
                options = ([('', '')] if not prop.required else []) + \
                    sorted(((u, e.name) for u, e in store.items()), key=lambda t: t[1])
            if val == MIXED:
                w.addItem(MIXED, MIXED)
            for data, text in options:
                w.addItem(text, data)
            idx = w.findData(val)
            w.setCurrentIndex(idx if idx >= 0 else 0)
            w.activated.connect(lambda i, p=prop, cb=w: cb.itemData(i) != MIXED and
                                self._commit(elems, p.key, cb.itemData(i)))
        elif prop.type == 'demand_cats':
            text = MIXED if val == MIXED else format_demand_cats(val or [], self._name_of)
            w = QLineEdit(text)
            w.setPlaceholderText('vazão:padrão:nome; ...')
            w.editingFinished.connect(lambda p=prop, le=w: self._commit_text(elems, p, le))
        else:
            if val == MIXED:
                text = ''
            elif val is None:
                text = ''
            elif isinstance(val, float):
                text = f'{val:.6g}' if abs(val) < 1e5 else f'{val:.3f}'
            else:
                text = str(val)
            w = QLineEdit(text)
            if val == MIXED:
                w.setPlaceholderText(MIXED)
            w.editingFinished.connect(lambda p=prop, le=w: self._commit_text(elems, p, le))
        if prop.note:
            w.setToolTip(prop.note)
        if prop.key == 'length' and len(elems) == 1 and getattr(elems[0], 'auto_length', False):
            w.setEnabled(False)
            w.setToolTip('Desligue o comprimento automático para informar um comprimento '
                         'hidráulico independente.')
        form.addRow(label, w)

    def _commit_text(self, elems, prop, le):
        if self._building or not le.isModified():
            return
        le.setModified(False)
        text = le.text()
        if text == '' and le.placeholderText() == MIXED:
            return
        try:
            if prop.type == 'demand_cats':
                pats = {p.name: u for u, p in self.ctrl.project.network.patterns.items()}
                value = parse_demand_cats(text, lambda n: pats.get(n, ''))
            else:
                value = parse_value(prop, text)
        except ValueError as ex:
            QMessageBox.warning(self, 'Valor inválido', str(ex))
            self.rebuild()
            return
        if prop.key == 'name':
            other = self.ctrl.project.network.find_by_name(value, elems[0].COLLECTION)
            if other is not None and other.uid != elems[0].uid:
                QMessageBox.warning(self, 'Identificador duplicado',
                                    f"Já existe um elemento chamado '{value}'.")
                self.rebuild()
                return
        self._commit(elems, prop.key, value)

    def _commit(self, elems, key, value):
        if self._building:
            return
        items = [(e.uid, {key: value}) for e in elems]
        if not confirm_existing_diameter(self, self.ctrl.project, [e.uid for e in elems], key):
            self.rebuild()
            return
        if key in ('start', 'end'):
            e = elems[0]
            other = e.end if key == 'start' else e.start
            if value == other:
                QMessageBox.warning(self, 'Conexão inválida',
                                    'Os nós inicial e final devem ser diferentes.')
                self.rebuild()
                return
        label = f'Editar {key}' + (f' ({len(elems)} elementos)' if len(elems) > 1 else '')
        self.ctrl.update_elements(items, label)

    # ------------------------------------------------------------------ resultados
    def _add_results(self, v, e):
        p = self.ctrl.project
        t = self.canvas.theme.time_index
        sim = p.latest_result('simulation')
        opt = p.latest_result('optimization')
        rows = []
        if sim and e.COLLECTION in ('node', 'link'):
            store = sim.get('nodes' if e.COLLECTION == 'node' else 'links', {})
            d = store.get(e.uid)
            if d:
                times = sim.get('times', [0])
                ti = min(t, len(times) - 1) if times else 0
                rows.append(('Instante', f'{(times[ti] if times else 0) / 3600:.2f} h'))
                names = {'pressure': ('Pressão', 'm'), 'head': ('Carga hidráulica', 'm'),
                         'demand': ('Demanda atendida', 'L/s'), 'level': ('Nível', 'm'),
                         'volume': ('Volume', 'm³'), 'inflow': ('Vazão de entrada', 'L/s'),
                         'outflow': ('Vazão de saída', 'L/s'), 'flow': ('Vazão', 'L/s'),
                         'velocity': ('Velocidade', 'm/s'),
                         'unit_headloss': ('Perda unitária', 'm/km'),
                         'headloss': ('Perda de carga', 'm'), 'status': ('Estado', ''),
                         'setting': ('Ajuste', '')}
                for key, (lab, unit) in names.items():
                    val = TV.value_at(d.get(key), ti)
                    if val is None:
                        continue
                    if key == 'status':
                        rows.append((lab, TV.STATUS_LABELS.get(int(round(val)), str(val))))
                    else:
                        rows.append((f'{lab} ({unit})' if unit else lab, f'{val:.3f}'))
                o = p.sim_options
                if e.KIND == 'junction':
                    pr = TV.value_at(d.get('pressure'), ti)
                    if pr is not None:
                        ok = o.pressure_min <= pr <= o.pressure_max
                        rows.append(('Validação', 'dentro dos limites' if ok else
                                     f'FORA de {o.pressure_min:g}–{o.pressure_max:g} m'))
        if opt and e.uid in opt.get('pipes', {}):
            d = opt['pipes'][e.uid]
            rows.append(('— Otimização —', ''))
            rows.append(('Diâmetro original (mm)', f"{d['orig_diam_mm']:g}"))
            rows.append(('Diâmetro otimizado (mm)', f"{d['opt_diam_mm']:g}"))
            if d.get('v_max') is not None:
                rows.append(('Velocidade máx. otimizada (m/s)', f"{d['v_max']:.3f}"))
        if opt and e.uid in opt.get('junctions', {}):
            d = opt['junctions'][e.uid]
            rows.append(('— Otimização —', ''))
            rows.append(('Pressão mín. otimizada (m)', f"{d['p_min']:.3f}"))
            rows.append(('Alvo de pressão do script (m)', f"{d['alvo']:.3f}"))
        if not rows:
            return
        box = QGroupBox('Resultados')
        form = QFormLayout(box)
        for a, b in rows:
            form.addRow(a, QLabel(b))
        v.addWidget(box)
