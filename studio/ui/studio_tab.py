"""Вкладка «Студия»: сцена, микрофоны, пульт, параметры записи, превью и запись микса."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
                             QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QProgressBar,
                             QPushButton, QScrollArea, QSpinBox, QSplitter, QTabWidget, QTextEdit,
                             QVBoxLayout, QWidget)

from .. import stems as stems_mod
from ..dsp import PREAMPS, TAPES
from ..generators.base import GeneratedTrack
from ..mics import MICS, PATTERNS, polar_gain, proximity_boost_db
from ..render import RenderCancelled, channel_geometry, describe_scene, render_preview, render_session
from ..scenes import AMBIENCE_KINDS, SCENES
from ..session import INSTRUMENTS, Session, session_from_stems
from .stage import StageView
from .widgets import ChannelStrip, SliderSpin
from .paths import project_root
from .workers import Task

AUDIO_FILTER = "Аудио (*.wav *.flac *.mp3 *.m4a *.aiff *.aif *.ogg)"


def open_in_finder(path: Path):
    path = Path(path)
    target = path if path.is_dir() else path.parent
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)] if path.is_file() else ["open", str(target)])
    elif sys.platform.startswith("win"):
        os.startfile(str(target))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(target)])


def read_sidecar(path: Path) -> tuple[dict, dict]:
    """Метаданные и готовые дорожки трека из <файл>.json, который пишут движки генерации."""
    side = Path(path).with_suffix(".json")
    if not side.exists():
        return {}, {}
    try:
        t = GeneratedTrack.from_sidecar(side)
    except (OSError, ValueError, KeyError, TypeError):
        return {}, {}
    meta = dict(t.meta)
    for k, v in (("title", t.title), ("lyrics", t.lyrics), ("cover", t.cover), ("engine", t.engine)):
        if v:
            meta[k] = str(v)
    stems = {k: v for k, v in t.stems.items() if v and Path(v).exists()}
    return meta, stems


class StudioTab(QWidget):
    status = pyqtSignal(str)

    def __init__(self, player, settings, parent=None):
        super().__init__(parent)
        self.player = player
        self.settings = settings
        self.session = Session()
        self.session_path: Path | None = None
        self.task: Task | None = None
        self.strips: dict[str, ChannelStrip] = {}
        self.current_id: str | None = None
        self._loading = False
        self._ui()
        self._load_session_into_ui()

    # ── пути ─────────────────────────────────────────────────
    @property
    def out_root(self) -> Path:
        return project_root(self.settings)

    def session_dir(self) -> Path:
        if self.session_path:
            return self.session_path.parent
        safe = "".join(c if c.isalnum() or c in " -_()" else "_" for c in self.session.name).strip() or "session"
        d = self.out_root / "sessions" / safe
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ── UI ───────────────────────────────────────────────────
    def _ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        bar = QHBoxLayout()
        self.title = QLabel("Новая сессия")
        self.title.setObjectName("h1")
        bar.addWidget(self.title)
        bar.addStretch()
        for text, slot, tip in [
            ("Новая", self.new_session, "Пустая сессия"),
            ("Открыть…", self.open_session, "Открыть *.studio.json"),
            ("Сохранить", self.save_session, "Сохранить сессию"),
            ("+ Дорожки…", self.add_tracks, "Добавить готовые стемы/дорожки как каналы"),
            ("Импорт песни…", self.import_song_dialog, "Разделить готовую песню на дорожки и открыть в студии"),
        ]:
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            bar.addWidget(b)
        root.addLayout(bar)

        scene_row = QHBoxLayout()
        scene_row.addWidget(QLabel("Помещение:"))
        self.scene_combo = QComboBox()
        for sid, sc in SCENES.items():
            self.scene_combo.addItem(sc.name, sid)
        self.scene_combo.currentIndexChanged.connect(self._scene_changed)
        scene_row.addWidget(self.scene_combo, 2)
        scene_row.addWidget(QLabel("Хвост ×"))
        self.rt_scale = QDoubleSpinBox()
        self.rt_scale.setRange(0.2, 3.0)
        self.rt_scale.setSingleStep(0.1)
        self.rt_scale.setToolTip("Множитель RT60 выбранного помещения")
        self.rt_scale.valueChanged.connect(self._rt_changed)
        scene_row.addWidget(self.rt_scale)
        scene_row.addWidget(QLabel("Эмбиент"))
        self.amb = QDoubleSpinBox()
        self.amb.setRange(-40, 20)
        self.amb.setSuffix(" дБ")
        self.amb.setToolTip("Смещение уровня шума помещения / публики относительно пресета")
        self.amb.valueChanged.connect(self._amb_changed)
        scene_row.addWidget(self.amb)
        self.scene_info = QLabel()
        self.scene_info.setObjectName("muted")
        scene_row.addWidget(self.scene_info, 3)
        root.addLayout(scene_row)

        split = QSplitter(Qt.Horizontal)
        root.addWidget(split, 1)

        left = QSplitter(Qt.Vertical)
        self.stage = StageView()
        self.stage.channel_selected.connect(self.select_channel)
        self.stage.channel_moved.connect(self._moved)
        self.stage.listener_moved.connect(lambda *_: self._refresh_strips())
        stage_box = QWidget()
        sb = QVBoxLayout(stage_box)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.setSpacing(2)
        sb.addWidget(self.stage, 1)
        self.stage_info = QLabel()
        self.stage_info.setObjectName("muted")
        self.stage_info.setWordWrap(True)
        self.stage.info_changed.connect(self.stage_info.setText)
        sb.addWidget(self.stage_info)
        left.addWidget(stage_box)
        self.mixer_area = QScrollArea()
        self.mixer_area.setWidgetResizable(True)
        self.mixer_area.setMinimumHeight(270)
        self.mixer_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.mixer_host = QWidget()
        self.mixer_lay = QHBoxLayout(self.mixer_host)
        self.mixer_lay.setContentsMargins(4, 4, 4, 4)
        self.mixer_lay.addStretch()
        self.mixer_area.setWidget(self.mixer_host)
        left.addWidget(self.mixer_area)
        left.setSizes([440, 280])
        split.addWidget(left)

        self.side = QTabWidget()
        self.side.setMinimumWidth(440)
        self.side.addTab(self._build_inspector(), "Канал")
        self.side.addTab(self._build_recording(), "Запись")
        self.report = QTextEdit()
        self.report.setReadOnly(True)
        self.report.setPlaceholderText("Здесь появится отчёт рендера: громкость, true peak, дистанции и задержки.")
        self.side.addTab(self.report, "Отчёт")
        split.addWidget(self.side)
        split.setSizes([860, 470])

        root.addWidget(self._build_transport())

    def _build_inspector(self) -> QWidget:
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        w = QWidget()
        self.insp = w
        v = QVBoxLayout(w)

        g = QGroupBox("Источник")
        f = QFormLayout(g)
        self.ch_name = QLineEdit()
        self.ch_name.editingFinished.connect(self._name_changed)
        f.addRow("Название", self.ch_name)
        self.ch_inst = QComboBox()
        for iid, p in INSTRUMENTS.items():
            self.ch_inst.addItem(p.name, iid)
        self.ch_inst.activated.connect(self._inst_changed)
        f.addRow("Инструмент", self.ch_inst)
        self.ch_src = QLabel()
        self.ch_src.setObjectName("muted")
        self.ch_src.setWordWrap(True)
        f.addRow("Файл", self.ch_src)
        row = QHBoxLayout()
        self.ch_stereo = QCheckBox("Стерео-источник")
        self.ch_stereo.setToolTip("Сохранять стерео дорожки (пэды, оверхеды). Иначе — моно-источник на сцене")
        self.ch_stereo.toggled.connect(lambda on: self._set("stereo", on))
        row.addWidget(self.ch_stereo)
        rm = QPushButton("Удалить канал")
        rm.setObjectName("stop")
        rm.clicked.connect(self.remove_channel)
        row.addWidget(rm)
        f.addRow(row)
        v.addWidget(g)

        g = QGroupBox("Микрофон")
        f = QFormLayout(g)
        self.ch_mic = QComboBox()
        for mid, m in MICS.items():
            self.ch_mic.addItem(m.name, mid)
        self.ch_mic.activated.connect(self._mic_changed)
        f.addRow("Модель", self.ch_mic)
        self.mic_desc = QLabel()
        self.mic_desc.setWordWrap(True)
        self.mic_desc.setObjectName("muted")
        f.addRow(self.mic_desc)
        self.ch_dist = SliderSpin(1, 300, 1, 0, " см")
        self.ch_dist.valueChanged.connect(lambda x: self._set("mic_distance_cm", x, mic=True))
        f.addRow("Дистанция", self.ch_dist)
        self.ch_angle = SliderSpin(0, 180, 1, 0, "°")
        self.ch_angle.valueChanged.connect(lambda x: self._set("mic_angle_deg", x, mic=True))
        f.addRow("Угол к оси", self.ch_angle)
        self.mic_info = QLabel()
        self.mic_info.setObjectName("ok")
        self.mic_info.setWordWrap(True)
        f.addRow(self.mic_info)
        v.addWidget(g)

        g = QGroupBox("Канальная обработка")
        f = QFormLayout(g)
        self.ch_drive = SliderSpin(0, 24, 0.5, 1, " дБ")
        self.ch_drive.valueChanged.connect(lambda x: self._set("drive_db", x))
        f.addRow("Драйв преампа", self.ch_drive)
        self.ch_hpf = SliderSpin(20, 400, 5, 0, " Гц")
        self.ch_hpf.valueChanged.connect(lambda x: self._set("hpf_hz", x))
        f.addRow("Срез НЧ (HPF)", self.ch_hpf)
        self.ch_low = SliderSpin(-12, 12, 0.5, 1, " дБ")
        self.ch_low.valueChanged.connect(lambda x: self._set("eq_low_db", x))
        f.addRow("НЧ 100 Гц", self.ch_low)
        mid = QHBoxLayout()
        self.ch_mid = SliderSpin(-12, 12, 0.5, 1, " дБ")
        self.ch_mid.valueChanged.connect(lambda x: self._set("eq_mid_db", x))
        self.ch_midf = QSpinBox()
        self.ch_midf.setRange(150, 8000)
        self.ch_midf.setSingleStep(50)
        self.ch_midf.setSuffix(" Гц")
        self.ch_midf.valueChanged.connect(lambda x: self._set("eq_mid_freq", float(x)))
        mid.addWidget(self.ch_mid, 1)
        mid.addWidget(self.ch_midf)
        f.addRow("Середина", mid)
        self.ch_high = SliderSpin(-12, 12, 0.5, 1, " дБ")
        self.ch_high.valueChanged.connect(lambda x: self._set("eq_high_db", x))
        f.addRow("ВЧ 10 кГц", self.ch_high)
        self.ch_comp = SliderSpin(0, 100, 1, 0, " %")
        self.ch_comp.valueChanged.connect(lambda x: self._set("comp", x / 100.0))
        f.addRow("Компрессия", self.ch_comp)
        self.ch_send = SliderSpin(-30, 12, 0.5, 1, " дБ")
        self.ch_send.valueChanged.connect(lambda x: self._set("reverb_send_db", x))
        f.addRow("Посыл в зал", self.ch_send)
        v.addWidget(g)
        self.geo_info = QLabel()
        self.geo_info.setWordWrap(True)
        self.geo_info.setObjectName("muted")
        v.addWidget(self.geo_info)
        v.addStretch()
        sc.setWidget(w)
        return sc

    def _build_recording(self) -> QWidget:
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        w = QWidget()
        v = QVBoxLayout(w)

        g = QGroupBox("Формат записи")
        f = QFormLayout(g)
        self.r_sr = QComboBox()
        for sr in (44100, 48000, 88200, 96000):
            self.r_sr.addItem(f"{sr / 1000:g} кГц", sr)
        self.r_sr.activated.connect(lambda _: self._rset("sample_rate", self.r_sr.currentData()))
        f.addRow("Частота", self.r_sr)
        self.r_bits = QComboBox()
        for b, t in ((16, "16 бит"), (24, "24 бит"), (32, "32 бит float")):
            self.r_bits.addItem(t, b)
        self.r_bits.activated.connect(lambda _: self._rset("bit_depth", self.r_bits.currentData()))
        f.addRow("Разрядность", self.r_bits)
        self.r_fmt = QComboBox()
        for k, t in (("wav", "WAV"), ("flac", "FLAC"), ("alac", "ALAC (.m4a)"), ("mp3", "MP3 320")):
            self.r_fmt.addItem(t, k)
        self.r_fmt.activated.connect(lambda _: self._rset("output_format", self.r_fmt.currentData()))
        f.addRow("Файл", self.r_fmt)
        v.addWidget(g)

        g = QGroupBox("Тракт")
        f = QFormLayout(g)
        self.r_pre = QComboBox()
        for k, p in PREAMPS.items():
            self.r_pre.addItem(p["name"], k)
        self.r_pre.activated.connect(lambda _: self._rset("preamp", self.r_pre.currentData()))
        f.addRow("Преамп", self.r_pre)
        self.r_drive = SliderSpin(0, 18, 0.5, 1, " дБ")
        self.r_drive.valueChanged.connect(lambda x: self._rset("preamp_drive_db", x))
        f.addRow("Драйв (все каналы)", self.r_drive)
        self.r_room = SliderSpin(-40, 6, 0.5, 1, " дБ")
        self.r_room.valueChanged.connect(lambda x: self._rset("room_mics_db", x))
        f.addRow("Room-микрофоны", self.r_room)
        self.r_pair = SliderSpin(0.1, 2.0, 0.05, 2, " м")
        self.r_pair.valueChanged.connect(lambda x: self._rset("pair_spacing_m", x))
        f.addRow("База пары A-B", self.r_pair)
        self.r_align = QCheckBox("Выравнивать задержку room-пары")
        self.r_align.setToolTip("Убирает общую задержку прихода звука к паре, сохраняя разницу между инструментами")
        self.r_align.toggled.connect(lambda on: self._rset("align_room_mics", on))
        f.addRow(self.r_align)
        self.r_width = SliderSpin(0, 2, 0.05, 2, "×")
        self.r_width.valueChanged.connect(lambda x: self._rset("stereo_width", x))
        f.addRow("Ширина стерео", self.r_width)
        v.addWidget(g)

        g = QGroupBox("Мастер")
        f = QFormLayout(g)
        self.r_bus = SliderSpin(0, 100, 1, 0, " %")
        self.r_bus.valueChanged.connect(lambda x: self._rset("bus_comp", x / 100.0))
        f.addRow("Склейка (bus comp)", self.r_bus)
        self.r_tape = QComboBox()
        for k, p in TAPES.items():
            self.r_tape.addItem(p["name"], k)
        self.r_tape.activated.connect(lambda _: self._rset("tape", self.r_tape.currentData()))
        f.addRow("Лента / носитель", self.r_tape)
        self.r_lufs = SliderSpin(-24, -6, 0.5, 1, " LUFS")
        self.r_lufs.valueChanged.connect(lambda x: self._rset("target_lufs", x))
        f.addRow("Громкость", self.r_lufs)
        self.r_ceil = SliderSpin(-3, 0, 0.1, 1, " dBTP")
        self.r_ceil.valueChanged.connect(lambda x: self._rset("ceiling_db", x))
        f.addRow("Потолок", self.r_ceil)
        self.r_lim = QCheckBox("True-peak лимитер")
        self.r_lim.toggled.connect(lambda on: self._rset("limiter", on))
        f.addRow(self.r_lim)
        self.r_fade = SliderSpin(0, 15, 0.5, 1, " с")
        self.r_fade.valueChanged.connect(lambda x: self._rset("fade_out_s", x))
        f.addRow("Затухание в конце", self.r_fade)
        self.r_seed = QSpinBox()
        self.r_seed.setRange(0, 999999)
        self.r_seed.valueChanged.connect(lambda x: self._rset("seed", int(x)))
        f.addRow("Seed (шумы, хвост)", self.r_seed)
        v.addWidget(g)
        hint = QLabel("Подсказка: стриминги нормализуют к ≈ −14 LUFS; для мастеринга во внешней DAW "
                      "выберите 32 бит float и отключите лимитер.")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        v.addWidget(hint)
        v.addStretch()
        sc.setWidget(w)
        return sc

    def _build_transport(self) -> QWidget:
        g = QGroupBox("Транспорт")
        lay = QVBoxLayout(g)
        row = QHBoxLayout()
        row.addWidget(QLabel("С"))
        self.pv_start = QDoubleSpinBox()
        self.pv_start.setRange(0, 3600)
        self.pv_start.setSuffix(" с")
        row.addWidget(self.pv_start)
        row.addWidget(QLabel("длиной"))
        self.pv_len = QDoubleSpinBox()
        self.pv_len.setRange(3, 120)
        self.pv_len.setValue(20)
        self.pv_len.setSuffix(" с")
        row.addWidget(self.pv_len)
        self.btn_preview = QPushButton("Превью")
        self.btn_preview.setObjectName("start")
        self.btn_preview.clicked.connect(self.preview)
        row.addWidget(self.btn_preview)
        self.btn_orig = QPushButton("Оригинал")
        self.btn_orig.setToolTip("Прослушать исходную песню (A/B)")
        self.btn_orig.clicked.connect(self.play_original)
        row.addWidget(self.btn_orig)
        self.btn_stop = QPushButton("Стоп")
        self.btn_stop.setObjectName("stop")
        self.btn_stop.clicked.connect(self.stop)
        row.addWidget(self.btn_stop)
        row.addStretch()
        self.cb_stems = QCheckBox("+ стемы")
        self.cb_stems.setToolTip("Дополнительно сохранить каждый канал с его комнатой (32 бит, до мастера)")
        row.addWidget(self.cb_stems)
        self.btn_record = QPushButton("Записать микс")
        self.btn_record.setObjectName("accent")
        self.btn_record.clicked.connect(self.record)
        row.addWidget(self.btn_record)
        self.btn_folder = QPushButton("Папка")
        self.btn_folder.clicked.connect(lambda: open_in_finder(self.session_dir()))
        row.addWidget(self.btn_folder)
        lay.addLayout(row)
        row2 = QHBoxLayout()
        self.prog = QProgressBar()
        self.prog.setRange(0, 1000)
        self.prog.setValue(0)
        row2.addWidget(self.prog, 2)
        self.prog_lbl = QLabel("Готово к работе")
        self.prog_lbl.setObjectName("muted")
        row2.addWidget(self.prog_lbl, 3)
        lay.addLayout(row2)
        return g

    # ── синхронизация UI ⇄ сессия ────────────────────────────
    def _load_session_into_ui(self):
        self._loading = True
        s = self.session
        self.title.setText(s.name)
        self.scene_combo.setCurrentIndex(max(0, self.scene_combo.findData(s.scene)))
        self.rt_scale.setValue(s.rt60_scale)
        self.amb.setValue(s.ambience_db_offset)
        r = s.recording
        self.r_sr.setCurrentIndex(max(0, self.r_sr.findData(r.sample_rate)))
        self.r_bits.setCurrentIndex(max(0, self.r_bits.findData(r.bit_depth)))
        self.r_fmt.setCurrentIndex(max(0, self.r_fmt.findData(r.output_format)))
        self.r_pre.setCurrentIndex(max(0, self.r_pre.findData(r.preamp)))
        self.r_drive.setValue(r.preamp_drive_db)
        self.r_room.setValue(r.room_mics_db)
        self.r_pair.setValue(r.pair_spacing_m)
        self.r_align.setChecked(r.align_room_mics)
        self.r_width.setValue(r.stereo_width)
        self.r_bus.setValue(r.bus_comp * 100)
        self.r_tape.setCurrentIndex(max(0, self.r_tape.findData(r.tape)))
        self.r_lufs.setValue(r.target_lufs)
        self.r_ceil.setValue(r.ceiling_db)
        self.r_lim.setChecked(r.limiter)
        self.r_fade.setValue(r.fade_out_s)
        self.r_seed.setValue(r.seed)
        self._loading = False
        self._update_scene_info()
        self.stage.set_session(s)
        self._rebuild_mixer()
        self.select_channel(s.channels[0].id if s.channels else None)

    def _update_scene_info(self):
        d = describe_scene(self.session)
        sc = self.session.scene_preset
        amb = AMBIENCE_KINDS.get(sc.ambience, sc.ambience)
        self.scene_info.setText(f"{d['size']} · RT60 {d['rt60_s']} с · крит. дист. {d['critical_distance_m']} м · "
                                f"эмбиент: {amb}")
        self.scene_info.setToolTip(sc.description)

    def _rebuild_mixer(self):
        while self.mixer_lay.count() > 1:
            it = self.mixer_lay.takeAt(0)
            w = it.widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self.strips.clear()
        for ch in self.session.channels:
            st = ChannelStrip(ch)
            st.changed.connect(self._strip_changed)
            st.selected.connect(self.select_channel)
            self.mixer_lay.insertWidget(self.mixer_lay.count() - 1, st)
            self.strips[ch.id] = st
        self._refresh_strips()
        if not self.session.channels:
            hint = QLabel("Пульт пуст. Сгенерируйте песню и нажмите «В студию», импортируйте готовую песню "
                          "или добавьте дорожки.")
            hint.setObjectName("muted")
            hint.setWordWrap(True)
            self.mixer_lay.insertWidget(0, hint)

    def _refresh_strips(self):
        for cid, st in self.strips.items():
            g = channel_geometry(self.session, st.ch)
            st.sync(auto_pan=g["auto_pan"])
            st.set_selected(cid == self.current_id)
        self._update_geo()

    def select_channel(self, ch_id):
        self.current_id = ch_id
        ch = self.session.channel(ch_id) if ch_id else None
        self.insp.setEnabled(ch is not None)
        for cid, st in self.strips.items():
            st.set_selected(cid == ch_id)
        if ch_id:
            self.stage.select(ch_id)
        if not ch:
            return
        self._loading = True
        self.ch_name.setText(ch.name)
        self.ch_inst.setCurrentIndex(max(0, self.ch_inst.findData(ch.instrument)))
        self.ch_src.setText(Path(ch.source).name)
        self.ch_src.setToolTip(ch.source)
        self.ch_stereo.setChecked(ch.stereo)
        self.ch_mic.setCurrentIndex(max(0, self.ch_mic.findData(ch.mic)))
        self.ch_dist.setValue(ch.mic_distance_cm)
        self.ch_angle.setValue(ch.mic_angle_deg)
        self.ch_drive.setValue(ch.drive_db)
        self.ch_hpf.setValue(ch.hpf_hz)
        self.ch_low.setValue(ch.eq_low_db)
        self.ch_mid.setValue(ch.eq_mid_db)
        self.ch_midf.setValue(int(ch.eq_mid_freq))
        self.ch_high.setValue(ch.eq_high_db)
        self.ch_comp.setValue(ch.comp * 100)
        self.ch_send.setValue(ch.reverb_send_db)
        self._loading = False
        self._update_mic_info()
        self._update_geo()

    def _cur(self):
        return self.session.channel(self.current_id) if self.current_id else None

    def _set(self, attr, value, mic=False):
        if self._loading:
            return
        ch = self._cur()
        if not ch:
            return
        setattr(ch, attr, value)
        if mic:
            self._update_mic_info()

    def _rset(self, attr, value):
        if not self._loading:
            setattr(self.session.recording, attr, value)

    def _update_mic_info(self):
        ch = self._cur()
        if not ch:
            return
        m = MICS.get(ch.mic)
        if not m:
            return
        pat = PATTERNS[m.pattern]["name"]
        self.mic_desc.setText(f"{pat} · {m.description}")
        if m.id == "di":
            self.mic_info.setText("Линейный сигнал: без окраски микрофона и без room-пары.")
            self.ch_dist.setEnabled(False)
            self.ch_angle.setEnabled(False)
            return
        self.ch_dist.setEnabled(True)
        self.ch_angle.setEnabled(True)
        prox = proximity_boost_db(m, ch.mic_distance_cm / 100.0)
        pg = 20 * __import__("math").log10(polar_gain(m.pattern, ch.mic_angle_deg) + 1e-9)
        off = m.offaxis_hf_db * min(ch.mic_angle_deg / 90.0, 1.5)
        self.mic_info.setText(f"Эффект близости: +{prox:.1f} дБ НЧ · чувствительность по углу: {pg:+.1f} дБ · "
                              f"ВЧ вне оси: {off:+.1f} дБ")

    def _update_geo(self):
        ch = self._cur()
        if not ch:
            self.geo_info.setText("")
            return
        g = channel_geometry(self.session, ch)
        self.geo_info.setText(
            f"На сцене: x={ch.x:.1f} м, y={ch.y:.1f} м · до room-пары {g['distance_m']:.1f} м "
            f"({g['delay_ms']:.0f} мс) · азимут {g['azimuth_deg']:+.0f}° · "
            f"критическая дистанция помещения {g['critical_distance_m']:.1f} м")

    # ── обработчики ──────────────────────────────────────────
    def _scene_changed(self, _):
        if self._loading:
            return
        self.session.set_scene(self.scene_combo.currentData())
        self._update_scene_info()
        self.stage.set_session(self.session)
        self._refresh_strips()

    def _rt_changed(self, v):
        if self._loading:
            return
        self.session.rt60_scale = float(v)
        self._update_scene_info()
        self.stage.rebuild()

    def _amb_changed(self, v):
        if not self._loading:
            self.session.ambience_db_offset = float(v)

    def _moved(self, ch_id, x, y):
        st = self.strips.get(ch_id)
        if st:
            st.sync(auto_pan=channel_geometry(self.session, st.ch)["auto_pan"])
        if ch_id == self.current_id:
            self._update_geo()

    def _strip_changed(self, ch_id):
        self.stage.refresh_token(ch_id)

    def _name_changed(self):
        ch = self._cur()
        if ch and self.ch_name.text().strip():
            ch.name = self.ch_name.text().strip()
            self.stage.refresh_token(ch.id)
            if ch.id in self.strips:
                self.strips[ch.id].sync(channel_geometry(self.session, ch)["auto_pan"])

    def _inst_changed(self, _):
        ch = self._cur()
        if not ch:
            return
        self.session.apply_instrument(ch, self.ch_inst.currentData())
        self.stage.rebuild()
        self._refresh_strips()
        self.select_channel(ch.id)

    def _mic_changed(self, _):
        ch = self._cur()
        if not ch:
            return
        ch.mic = self.ch_mic.currentData()
        self._update_mic_info()
        if ch.id in self.strips:
            self.strips[ch.id].sync(channel_geometry(self.session, ch)["auto_pan"])

    # ── сессии ───────────────────────────────────────────────
    def set_session(self, session: Session, path: Path | None = None):
        self.session = session
        self.session_path = path
        self._load_session_into_ui()
        self.status.emit(f"Сессия: {session.name} · каналов: {len(session.channels)}")

    def new_session(self):
        self.set_session(Session())

    def open_session(self):
        p, _ = QFileDialog.getOpenFileName(self, "Открыть сессию", str(self.out_root / "sessions"),
                                           "Сессия (*.studio.json *.json)")
        if p:
            try:
                self.set_session(Session.load(p), Path(p))
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось открыть сессию:\n{e}")

    def save_session(self) -> Path:
        path = self.session_path or (self.session_dir() / "session.studio.json")
        self.session.save(path)
        self.session_path = path
        self.status.emit(f"Сессия сохранена: {path}")
        return path

    def add_tracks(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Добавить дорожки", str(Path.home()), AUDIO_FILTER)
        for f in files:
            self.session.add_channel(f)
        if files:
            self.stage.rebuild()
            self._rebuild_mixer()
            self.select_channel(self.session.channels[-1].id)

    def remove_channel(self):
        ch = self._cur()
        if not ch:
            return
        self.session.channels = [c for c in self.session.channels if c.id != ch.id]
        self.stage.rebuild()
        self._rebuild_mixer()
        self.select_channel(self.session.channels[0].id if self.session.channels else None)

    def import_song_dialog(self):
        p, _ = QFileDialog.getOpenFileName(self, "Импорт готовой песни", str(Path.home()), AUDIO_FILTER)
        if p:
            self.import_song(Path(p))

    def ask_method(self) -> str | None:
        methods = stems_mod.available_methods()
        keys = list(methods)
        default = "demucs" if stems_mod.demucs_available() else "hpss"
        item, ok = QInputDialog.getItem(self, "Разделение на дорожки",
                                        "Как подготовить песню для студии?",
                                        [methods[k] for k in keys], keys.index(default), False)
        return keys[[methods[k] for k in keys].index(item)] if ok else None

    def import_song(self, path: Path, meta: dict | None = None, stems: dict | None = None,
                    method: str | None = None):
        """Открыть песню в студии. stems — готовые дорожки от движка (без разделения)."""
        side_meta, side_stems = read_sidecar(path)
        meta = {**side_meta, **dict(meta or {})}
        meta.setdefault("title", path.stem)
        meta["source"] = str(path)
        name = meta.get("title") or path.stem
        stems = stems or (side_stems if method is None else None)
        if stems:
            sp = Path(stems[next(iter(stems))]).parent.parent / "session.studio.json"
            if sp.exists():          # песню уже открывали — сохраняем настройки пользователя
                try:
                    self.set_session(Session.load(sp), sp)
                    return
                except (OSError, ValueError, KeyError, TypeError):
                    pass
            s = session_from_stems({k: str(v) for k, v in stems.items()}, name=name, meta=meta)
            s.save(sp)
            self.set_session(s, sp)
            return
        method = method or self.ask_method()
        if not method:
            return
        safe = "".join(c if c.isalnum() or c in " -_()" else "_" for c in name).strip() or "song"
        sdir = self.out_root / "sessions" / safe
        if (sdir / "session.studio.json").exists():
            sdir = sdir.with_name(f"{safe} {time.strftime('%Y%m%d-%H%M%S')}")
        stem_dir = sdir / "stems"

        def job(progress, cancel):
            st = stems_mod.separate(path, stem_dir, method, progress=progress, cancel=cancel)
            return st

        def done(st):
            s = session_from_stems({k: str(v) for k, v in st.items()}, name=name, meta=meta)
            sp = sdir / "session.studio.json"
            s.save(sp)
            self.set_session(s, sp)
            self.report.setPlainText(f"Песня разделена ({stems_mod.METHODS[method]}): {', '.join(st)}\n"
                                     f"Сессия: {sp}")

        self._run(job, done, "Разделение на дорожки")

    # ── рендер ───────────────────────────────────────────────
    def _busy(self, on: bool):
        for b in (self.btn_preview, self.btn_record):
            b.setEnabled(not on)
        self.btn_stop.setText("Отменить" if on else "Стоп")

    def _run(self, job, done, title):
        if self.task and self.task.is_alive():
            QMessageBox.information(self, "Подождите", "Уже выполняется задача — дождитесь или нажмите «Отменить».")
            return
        self.task = Task(job, name=title)
        self.task.sig.progress.connect(lambda f, m: (self.prog.setValue(int(f * 1000)), self.prog_lbl.setText(m)))

        def _done(res):
            self._busy(False)
            self.prog.setValue(1000)
            done(res)

        def _err(msg):
            self._busy(False)
            self.prog.setValue(0)
            first = msg.split("\n")[0]
            if "отмен" in first.lower() or "cancel" in first.lower():
                self.prog_lbl.setText("Отменено")
                return
            self.prog_lbl.setText("Ошибка")
            self.report.setPlainText(msg)
            QMessageBox.warning(self, title, first)

        self.task.sig.done.connect(_done)
        self.task.sig.error.connect(_err)
        self._busy(True)
        self.prog_lbl.setText(title + "…")
        self.task.start()

    def _check_ready(self) -> bool:
        if not self.session.channels:
            QMessageBox.information(self, "Пусто", "Добавьте хотя бы одну дорожку.")
            return False
        missing = [c.name for c in self.session.channels if not Path(c.source).exists()]
        if missing:
            QMessageBox.warning(self, "Нет файлов", "Не найдены файлы каналов: " + ", ".join(missing))
            return False
        return True

    def preview(self):
        if not self._check_ready():
            return
        start, length = self.pv_start.value(), self.pv_len.value()
        session = Session.from_dict(self.session.to_dict())     # снимок — UI можно крутить дальше
        out = Path(tempfile.gettempdir()) / f"ams_preview_{os.getpid()}.wav"

        def job(progress, cancel):
            r = render_preview(session, start, length, progress=progress, cancel=cancel)
            from ..audio_io import write_audio
            write_audio(out, r.audio, r.sr, 24, "wav")
            return r

        def done(r):
            self.player.play(out)
            m = r.report["master"]
            self.prog_lbl.setText(f"Превью {start:.0f}–{start + length:.0f} с · "
                                  f"{m.get('lufs_after', m.get('lufs'))} LUFS · рендер {r.report['render_time_s']} с")
            self._show_report(r.report)

        self._run(job, done, "Рендер превью")

    def record(self):
        if not self._check_ready():
            return
        self.save_session()
        session = Session.from_dict(self.session.to_dict())
        sdir = self.session_dir()
        stamp = time.strftime("%Y%m%d-%H%M%S")
        base = f"{session.meta.get('title') or session.name} — {session.scene_preset.name.split(' (')[0]} {stamp}"
        base = "".join(c if c.isalnum() or c in " -_()—" else "_" for c in base)
        out = sdir / "renders" / base
        stems_dir = (sdir / "renders" / f"{base} — stems") if self.cb_stems.isChecked() else None

        def job(progress, cancel):
            return render_session(session, out_path=out, export_stems_dir=stems_dir, progress=progress,
                                  cancel=cancel)

        def done(r):
            self._show_report(r.report)
            (out.parent / f"{base}.report.json").write_text(json.dumps(r.report, ensure_ascii=False, indent=2),
                                                            encoding="utf-8")
            self.prog_lbl.setText(f"Записано: {r.path.name}")
            self.status.emit(f"Микс записан: {r.path}")
            self.last_render = r.path
            if QMessageBox.question(self, "Готово", f"Микс записан:\n{r.path}\n\nПрослушать?") == QMessageBox.Yes:
                self.player.play(r.path)

        self._run(job, done, "Запись микса")

    def _show_report(self, rep: dict):
        m = rep["master"]
        lines = [f"Помещение: {rep['scene']['name']} ({rep['scene']['size']}, RT60 {rep['scene']['rt60_s']} с) · "
                 f"длительность {rep['duration_s']} с · {rep['sample_rate']} Гц · рендер {rep['render_time_s']} с",
                 f"Мастер: {m}"]
        for c in rep["channels"]:
            lines.append(f"  {c['name']}: {c['mic']}, до пары {c['distance_m']} м / {c['delay_ms']} мс, "
                         f"панорама {c['pan']:+.2f}, близость +{c['proximity_db']} дБ, посыл {c['reverb_send']}")
        self.report.setPlainText("\n".join(lines))
        self.side.setCurrentWidget(self.report)

    def play_original(self):
        src = self.session.meta.get("source")
        if src and Path(src).exists():
            self.player.play(src)
        else:
            QMessageBox.information(self, "Нет оригинала", "У этой сессии нет исходного файла песни.")

    def stop(self):
        if self.task and self.task.is_alive():
            self.task.cancel()
        self.player.stop()

    def last_render_path(self):
        return getattr(self, "last_render", None)


__all__ = ["StudioTab", "open_in_finder", "RenderCancelled"]
