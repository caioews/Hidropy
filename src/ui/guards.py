"""Confirmações antes de edições sensíveis."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox


def confirm_existing_diameter(parent, project, uids, key) -> bool:
    """Pede confirmação antes de alterar o diâmetro de trechos existentes (executados)."""
    if key != 'diameter':
        return True
    names = [l.name for l in (project.network.links.get(u) for u in uids)
             if l is not None and getattr(l, 'existing', False)]
    if not names:
        return True
    lista = ', '.join(names[:10]) + (f' e mais {len(names) - 10}' if len(names) > 10 else '')
    msg = ('Este trecho está marcado como executado.' if len(names) == 1 else
           f'{len(names)} trechos estão marcados como executados.')
    return QMessageBox.question(
        parent, 'Trecho existente',
        f'{msg}\n({lista})\n\nAlterar o diâmetro mesmo assim?',
        QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes
