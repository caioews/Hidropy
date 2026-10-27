"""Árvore de navegação da rede, sincronizada com a seleção do desenho."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QAbstractItemView, QTreeWidget, QTreeWidgetItem

ROLE_UID = Qt.UserRole
ROLE_KIND = Qt.UserRole + 1

GROUPS = [
    ('Nós', [('junction', 'Junções'), ('reservoir', 'Reservatórios'), ('tank', 'Tanques')]),
    ('Ligações', [('pipe_projected', 'Tubulações projetadas'),
                  ('pipe_existing', 'Tubulações existentes'), ('pump', 'Bombas'),
                  ('valve', 'Válvulas')]),
    ('Controles', [('control', None)]),
    ('Curvas e padrões', [('curve', 'Curvas'), ('pattern', 'Padrões')]),
]


class NetworkTree(QTreeWidget):
    openEditor = Signal(str, str)     # kind, uid
    scenarioActivated = Signal(str)
    resultActivated = Signal(str)

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.ctrl = controller
        self.setHeaderHidden(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.items: dict[str, QTreeWidgetItem] = {}
        self._sync = False
        self._timer = QTimer(self, singleShot=True, interval=150, timeout=self.rebuild)
        self.itemSelectionChanged.connect(self._on_tree_selection)
        self.itemDoubleClicked.connect(self._on_double)
        self.ctrl.elementsChanged.connect(lambda cs: self._timer.start())
        self.ctrl.projectReplaced.connect(self.rebuild)
        self.ctrl.resultsChanged.connect(lambda: self._timer.start())
        self.ctrl.selectionChanged.connect(self._on_model_selection)
        self.rebuild()

    def rebuild(self):
        self._sync = True
        expanded = {self.itemText(it) for it in self._all_items() if it.isExpanded()}
        self.clear()
        self.items.clear()
        p = self.ctrl.project
        net = p.network
        by_kind: dict[str, list] = {}
        for e in net.elements():
            kind = e.KIND
            if kind == 'pipe':
                kind = 'pipe_existing' if e.existing else 'pipe_projected'
            by_kind.setdefault(kind, []).append(e)
        for title, subs in GROUPS:
            top = QTreeWidgetItem([title])
            self.addTopLevelItem(top)
            total = 0
            for kind, label in subs:
                elems = sorted(by_kind.get(kind, []), key=lambda e: e.name)
                parent = top
                if label:
                    parent = QTreeWidgetItem([f'{label} ({len(elems)})'])
                    parent.setData(0, ROLE_KIND, 'group:' + kind)
                    top.addChild(parent)
                for e in elems:
                    it = QTreeWidgetItem([e.name])
                    it.setData(0, ROLE_UID, e.uid)
                    it.setData(0, ROLE_KIND, e.KIND)
                    parent.addChild(it)
                    self.items[e.uid] = it
                total += len(elems)
                if parent is not top and parent.text(0) in expanded:
                    parent.setExpanded(True)
            top.setText(0, f'{title} ({total})')
            top.setExpanded(True)
        # cenários
        sc = QTreeWidgetItem([f'Cenários ({len(p.scenarios)})'])
        self.addTopLevelItem(sc)
        bold = QFont()
        bold.setBold(True)
        for s in p.scenarios:
            it = QTreeWidgetItem([s.name + ('  [ativo]' if s.uid == p.active_scenario else '')])
            it.setData(0, ROLE_KIND, 'scenario')
            it.setData(0, ROLE_UID, s.uid)
            if s.uid == p.active_scenario:
                it.setFont(0, bold)
            sc.addChild(it)
        sc.setExpanded(True)
        # resultados do cenário ativo
        res = p.results()
        rt = QTreeWidgetItem([f'Resultados ({len(res)})'])
        self.addTopLevelItem(rt)
        for r in reversed(res):
            kind = 'Simulação' if r['kind'] == 'simulation' else 'Otimização'
            state = ' — falhou' if r['status'] != 'ok' else ''
            it = QTreeWidgetItem([f"{kind} {r['created'][11:19]}{state}"])
            it.setData(0, ROLE_KIND, 'result')
            it.setData(0, ROLE_UID, r['uid'])
            it.setToolTip(0, r.get('error') or r['created'])
            rt.addChild(it)
        rt.setExpanded(True)
        self._sync = False
        self._on_model_selection(self.ctrl.selection, None)

    def _all_items(self):
        out = []
        stack = [self.topLevelItem(i) for i in range(self.topLevelItemCount())]
        while stack:
            it = stack.pop()
            out.append(it)
            stack += [it.child(i) for i in range(it.childCount())]
        return out

    @staticmethod
    def itemText(it):
        return it.text(0)

    def _on_tree_selection(self):
        if self._sync:
            return
        uids = [it.data(0, ROLE_UID) for it in self.selectedItems()
                if it.data(0, ROLE_UID) and it.data(0, ROLE_KIND) not in ('scenario', 'result')]
        self.ctrl.set_selection(uids, 'tree')

    def _on_model_selection(self, uids, source):
        if source == 'tree':
            return
        self._sync = True
        self.clearSelection()
        first = None
        for u in uids:
            it = self.items.get(u)
            if it is not None:
                it.setSelected(True)
                first = first or it
        if first is not None:
            self.scrollToItem(first)
        self._sync = False

    def _on_double(self, it, col):
        kind = it.data(0, ROLE_KIND)
        uid = it.data(0, ROLE_UID)
        if kind == 'scenario':
            self.scenarioActivated.emit(uid)
        elif kind == 'result':
            self.resultActivated.emit(uid)
        elif kind in ('curve', 'pattern', 'control') or (kind or '').startswith('group:'):
            self.openEditor.emit(kind.replace('group:', ''), uid or '')
        elif uid:
            self.openEditor.emit('zoom', uid)
