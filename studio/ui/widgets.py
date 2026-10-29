"""Небольшие составные виджеты: слайдер+число, канальная линейка пульта."""
from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QSlider, QToolButton,
                             QVBoxLayout, QWidget)

from ..session import Channel


class SliderSpin(QWidget):
    """Горизонтальный слайдер, связанный с полем ввода. Значение — float."""
    valueChanged = pyqtSignal(float)

    def __init__(self, lo: float, hi: float, step: float = 1.0, decimals: int = 0, suffix: str = "",
                 parent=None):
        super().__init__(parent)
        self._k = 10 ** decimals
        self._lock = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(int(round(lo * self._k)), int(round(hi * self._k)))
        self.slider.setSingleStep(max(1, int(round(step * self._k))))
        self.spin = QDoubleSpinBox()
        self.spin.setRange(lo, hi)
        self.spin.setDecimals(decimals)
        self.spin.setSingleStep(step)
        self.spin.setSuffix(suffix)
        self.spin.setFixedWidth(96)
        self.spin.setKeyboardTracking(False)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.spin)
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)

    def _from_slider(self, v: int):
        if self._lock:
            return
        self._lock = True
        self.spin.setValue(v / self._k)
        self._lock = False
        self.valueChanged.emit(v / self._k)

    def _from_spin(self, v: float):
        if self._lock:
            return
        self._lock = True
        self.slider.setValue(int(round(v * self._k)))
        self._lock = False
        self.valueChanged.emit(float(v))

    def value(self) -> float:
        return float(self.spin.value())

    def setValue(self, v: float):
        self._lock = True
        self.spin.setValue(float(v))
        self.slider.setValue(int(round(float(v) * self._k)))
        self._lock = False


class ChannelStrip(QFrame):
    """Линейка пульта: фейдер, панорама, Mute/Solo."""
    changed = pyqtSignal(str)          # id канала
    selected = pyqtSignal(str)

    def __init__(self, ch: Channel, parent=None):
        super().__init__(parent)
        self.ch = ch
        self.setObjectName("strip")
        self.setFixedWidth(104)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)
        self.name = QLabel()
        self.name.setAlignment(Qt.AlignCenter)
        self.name.setWordWrap(True)
        lay.addWidget(self.name)
        self.mic = QLabel()
        self.mic.setObjectName("muted")
        self.mic.setAlignment(Qt.AlignCenter)
        self.mic.setStyleSheet("font-size:10px;")
        lay.addWidget(self.mic)

        pan_row = QHBoxLayout()
        self.auto = QCheckBox("A")
        self.auto.setToolTip("Авто-панорама по положению на сцене")
        self.pan = QSlider(Qt.Horizontal)
        self.pan.setRange(-100, 100)
        self.pan.setToolTip("Панорама")
        pan_row.addWidget(self.auto)
        pan_row.addWidget(self.pan, 1)
        lay.addLayout(pan_row)

        fader_row = QHBoxLayout()
        self.fader = QSlider(Qt.Vertical)
        self.fader.setRange(-480, 120)       # десятые доли дБ
        self.fader.setMinimumHeight(110)
        self.fader.setToolTip("Фейдер, дБ (двойной клик — 0 дБ)")
        fader_row.addStretch()
        fader_row.addWidget(self.fader)
        fader_row.addStretch()
        lay.addLayout(fader_row, 1)
        self.db = QLabel()
        self.db.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.db)

        btns = QHBoxLayout()
        self.m = QToolButton()
        self.m.setText("M")
        self.m.setObjectName("mute")
        self.m.setCheckable(True)
        self.s = QToolButton()
        self.s.setText("S")
        self.s.setObjectName("solo")
        self.s.setCheckable(True)
        btns.addWidget(self.m)
        btns.addWidget(self.s)
        lay.addLayout(btns)
        self.sync()

        self.fader.valueChanged.connect(self._fader)
        self.pan.valueChanged.connect(self._pan)
        self.auto.toggled.connect(self._auto)
        self.m.toggled.connect(self._mute)
        self.s.toggled.connect(self._solo)

    def sync(self, auto_pan: float | None = None):
        ch = self.ch
        for w in (self.fader, self.pan, self.auto, self.m, self.s):
            w.blockSignals(True)
        self.name.setText(ch.name)
        self.name.setStyleSheet(f"color:{ch.color}; font-weight:bold;")
        from ..mics import MICS
        full = MICS[ch.mic].name if ch.mic in MICS else ch.mic
        short = full.split(" (")[0]
        self.mic.setText(self.mic.fontMetrics().elidedText(short, Qt.ElideRight, 90))
        self.mic.setToolTip(full)
        self.fader.setValue(int(round(ch.gain_db * 10)))
        self.db.setText(f"{ch.gain_db:+.1f} дБ")
        self.auto.setChecked(ch.pan is None)
        self.pan.setEnabled(ch.pan is not None)
        p = ch.pan if ch.pan is not None else (auto_pan or 0.0)
        self.pan.setValue(int(round(p * 100)))
        self.m.setChecked(ch.mute)
        self.s.setChecked(ch.solo)
        for w in (self.fader, self.pan, self.auto, self.m, self.s):
            w.blockSignals(False)

    def set_selected(self, on: bool):
        self.setProperty("selected", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, e):
        self.selected.emit(self.ch.id)
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        self.fader.setValue(0)

    def _fader(self, v):
        self.ch.gain_db = v / 10.0
        self.db.setText(f"{self.ch.gain_db:+.1f} дБ")
        self.changed.emit(self.ch.id)

    def _pan(self, v):
        if self.ch.pan is not None:
            self.ch.pan = v / 100.0
            self.changed.emit(self.ch.id)

    def _auto(self, on):
        self.ch.pan = None if on else self.pan.value() / 100.0
        self.pan.setEnabled(not on)
        self.changed.emit(self.ch.id)

    def _mute(self, on):
        self.ch.mute = on
        self.changed.emit(self.ch.id)

    def _solo(self, on):
        self.ch.solo = on
        self.changed.emit(self.ch.id)
