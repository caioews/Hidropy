"""Controlador do documento: dono do Project, da pilha de desfazer e da seleção.

Toda alteração do modelo passa por `apply()`, que empilha um EditCommand
(QUndoCommand) contendo os dicionários antes/depois de cada elemento afetado.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack

from ..hydraulics import editing
from ..hydraulics.models import Pipe
from ..hydraulics.project import Project

log = logging.getLogger(__name__)


class ChangeSet:
    def __init__(self, added=(), removed=(), modified=()):
        self.added = set(added)
        self.removed = set(removed)
        self.modified = set(modified)

    @property
    def all(self):
        return self.added | self.removed | self.modified


class EditCommand(QUndoCommand):
    def __init__(self, controller: 'DocumentController', changes, text: str):
        super().__init__(text)
        self.ctrl = controller
        self.changes = list(changes)

    def _apply(self, forward: bool):
        p = self.ctrl.project
        added, removed, modified = set(), set(), set()
        seq = self.changes if forward else list(reversed(self.changes))
        # remoções primeiro, depois inclusões/alterações (mantém referências válidas)
        ops = [(uid, (after if forward else before), (before if forward else after))
               for uid, before, after in seq]
        for uid, target, _ in ops:
            if target is None:
                p.remove(uid)
                removed.add(uid)
        for uid, target, source in ops:
            if target is not None:
                p.put_dict(target)
                (added if source is None else modified).add(uid)
        p.network.invalidate()
        self.ctrl._after_change(ChangeSet(added, removed, modified))

    def redo(self):
        self._apply(True)

    def undo(self):
        self._apply(False)


class DocumentController(QObject):
    elementsChanged = Signal(object)      # ChangeSet
    projectReplaced = Signal()
    layersChanged = Signal()
    resultsChanged = Signal()
    selectionChanged = Signal(list, object)   # uids, origem
    dirtyChanged = Signal(bool)
    scenarioChanged = Signal()
    message = Signal(str)

    def __init__(self, project: Project | None = None):
        super().__init__()
        self.project = project or Project()
        self.undo_stack = QUndoStack(self)
        self.undo_stack.cleanChanged.connect(self._on_clean_changed)
        self.selection: list[str] = []
        self._extra_dirty = False
        self.clipboard: dict | None = None
        self._hash_cache: str | None = None

    # ------------------------------------------------------------- estado
    def _on_clean_changed(self, clean):
        try:
            self.dirtyChanged.emit(self.dirty)
        except RuntimeError:      # pilha já destruída no encerramento
            pass

    @property
    def dirty(self) -> bool:
        return self._extra_dirty or not self.undo_stack.isClean()

    def mark_dirty(self):
        self._extra_dirty = True
        self.dirtyChanged.emit(True)

    def mark_saved(self):
        self._extra_dirty = False
        self.undo_stack.setClean()
        self.dirtyChanged.emit(False)

    def replace_project(self, project: Project):
        self.project = project
        self.undo_stack.clear()
        self.selection = []
        self._extra_dirty = False
        self._hash_cache = None
        self.projectReplaced.emit()
        self.selectionChanged.emit([], None)
        self.dirtyChanged.emit(False)

    # ------------------------------------------------------------- edição
    def apply(self, changes, text: str):
        changes = [c for c in changes if c[1] != c[2]]
        if not changes:
            return False
        self.undo_stack.push(EditCommand(self, changes, text))
        return True

    def _after_change(self, cs: ChangeSet):
        # comprimento automático: mantém o campo `length` sincronizado com a geometria
        net = self.project.network
        touched_nodes = {u for u in cs.all if u in net.nodes}
        for l in net.links.values():
            if isinstance(l, Pipe) and l.auto_length and (
                    l.uid in cs.all or l.start in touched_nodes or l.end in touched_nodes):
                l.length = round(net.geometric_length(l), 4)
        self._hash_cache = None
        sel = [u for u in self.selection if self.project.get(u) is not None]
        if sel != self.selection:
            self.selection = sel
            self.selectionChanged.emit(sel, None)
        self.elementsChanged.emit(cs)

    def add_elements(self, elems, text='Inserir elemento'):
        return self.apply(editing.add(elems), text)

    def update_element(self, uid, text='Editar propriedade', **props):
        return self.apply(editing.update(self.project, uid, **props), text)

    def update_elements(self, items, text='Editar propriedades'):
        return self.apply(editing.update_many(self.project, items), text)

    def delete(self, uids, text='Excluir'):
        return self.apply(editing.delete(self.project, uids), text)

    # ------------------------------------------------------------- seleção
    def set_selection(self, uids, source=None):
        uids = [u for u in dict.fromkeys(uids) if self.project.get(u) is not None]
        if uids == self.selection:
            return
        self.selection = uids
        self.selectionChanged.emit(uids, source)

    def selected_elements(self):
        return [e for e in (self.project.get(u) for u in self.selection) if e is not None]

    # ------------------------------------------------------------- resultados
    def current_hash(self) -> str:
        if self._hash_cache is None:
            from ..integration.input_exporter import network_hash
            self._hash_cache = network_hash(self.project)
        return self._hash_cache

    def invalidate_hash(self):
        self._hash_cache = None

    def is_current(self, result: dict | None) -> bool:
        return bool(result) and result.get('inp_sha256') == self.current_hash()

    def add_result(self, result: dict):
        scen = result.get('scenario') or self.project.active_scenario
        try:
            target = self.project.scenario(scen)
        except KeyError:
            target = self.project.scenario()
        if target.uid == self.project.active_scenario:
            self.project.add_result(result)
        else:
            target.results.append(result)
        self.mark_dirty()
        self.resultsChanged.emit()

    # ------------------------------------------------------------- cenários
    def switch_scenario(self, uid):
        self.project.switch_scenario(uid)
        self.undo_stack.clear()
        self._hash_cache = None
        self.selection = []
        self.mark_dirty()
        self.scenarioChanged.emit()
        self.projectReplaced.emit()
