"""Formulário simples gerado a partir de uma lista de campos de um dataclass."""

from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QLineEdit,
                               QSpinBox, QWidget)


class FieldForm(QWidget):
    """spec: [(campo, rótulo, tipo, extra)], tipo em float|int|bool|choice|str|float_opt."""

    def __init__(self, obj, spec, parent=None):
        super().__init__(parent)
        self.obj = obj
        self.spec = spec
        self.widgets = {}
        form = QFormLayout(self)
        for key, label, typ, extra in spec:
            val = getattr(obj, key)
            extra = extra or {}
            if typ == 'float':
                w = QDoubleSpinBox()
                w.setDecimals(extra.get('decimals', 3))
                w.setRange(extra.get('min', -1e9), extra.get('max', 1e9))
                w.setValue(float(val))
                if 'step' in extra:
                    w.setSingleStep(extra['step'])
            elif typ == 'int':
                w = QSpinBox()
                w.setRange(extra.get('min', 0), extra.get('max', 10 ** 7))
                w.setValue(int(val))
            elif typ == 'bool':
                w = QCheckBox()
                w.setChecked(bool(val))
            elif typ == 'choice':
                w = QComboBox()
                for data, text in extra['choices']:
                    w.addItem(text, data)
                i = w.findData(val)
                w.setCurrentIndex(i if i >= 0 else 0)
            else:   # str, float_opt
                w = QLineEdit('' if val is None else str(val))
                if typ == 'float_opt':
                    w.setPlaceholderText(extra.get('placeholder', 'vazio = automático'))
            if extra.get('tip'):
                w.setToolTip(extra['tip'])
            self.widgets[key] = (w, typ)
            form.addRow(label, w)

    def values(self) -> dict:
        out = {}
        for key, (w, typ) in self.widgets.items():
            if typ in ('float', 'int'):
                out[key] = w.value()
            elif typ == 'bool':
                out[key] = w.isChecked()
            elif typ == 'choice':
                out[key] = w.currentData()
            elif typ == 'float_opt':
                t = w.text().strip().replace(',', '.')
                if not t:
                    out[key] = None
                else:
                    try:
                        out[key] = float(t)
                    except ValueError:
                        raise ValueError(f'Valor numérico inválido em "{key}": {t}')
            else:
                out[key] = w.text().strip()
        return out

    def apply(self):
        for k, v in self.values().items():
            setattr(self.obj, k, v)
