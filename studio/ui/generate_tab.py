"""Вкладка «Генерация»: выбор движка, описание песни, текст со структурой, результаты."""
from __future__ import annotations

import time
from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
                             QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
                             QProgressBar, QPushButton, QScrollArea, QSpinBox, QSplitter, QVBoxLayout, QWidget)

from ..generators import ENGINES, GeneratedTrack, GenerationRequest
from .keystore import get_secret, save_secret
from .studio_tab import open_in_finder
from .paths import project_root
from .workers import Task

STYLE_CHIPS = {
    "Поп": "modern pop, catchy hook, polished production, female vocals",
    "Рок": "alternative rock, driving drums, distorted guitars, energetic male vocals",
    "Хип-хоп": "hip-hop, boom bap drums, deep bass, confident rap vocals",
    "Электроника": "electronic, house, four-on-the-floor, warm analog synths",
    "Лоу-фай": "lo-fi hip hop, mellow, vinyl texture, jazzy piano, chill",
    "Синтвейв": "synthwave, 80s, retro arpeggios, gated reverb drums",
    "Акустика": "acoustic folk, fingerpicked guitar, intimate vocals, warm room",
    "Джаз": "smooth jazz, upright bass, brushed drums, saxophone",
    "Оркестр": "cinematic orchestral, strings, brass, epic choir",
    "Инди": "indie pop, dreamy guitars, reverb, airy vocals",
}
TAGS = ["[Intro]", "[Verse]", "[Pre-Chorus]", "[Chorus]", "[Bridge]", "[Instrumental]", "[Drop]", "[Outro]"]
KEYS = ["Авто"] + [f"{n} {m}" for m in ("major", "minor")
                   for n in ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")]
LANGS = [("ru", "Русский"), ("en", "English"), ("uk", "Українська"), ("de", "Deutsch"), ("fr", "Français"),
         ("es", "Español"), ("it", "Italiano"), ("ja", "日本語"), ("ko", "한국어"), ("zh", "中文"),
         ("unknown", "Другой / без языка")]


def repolish(w, name: str):
    w.setObjectName(name)
    w.style().unpolish(w)
    w.style().polish(w)


class GenerateTab(QWidget):
    send_to_studio = pyqtSignal(object)      # GeneratedTrack
    status = pyqtSignal(str)

    def __init__(self, player, settings, parent=None):
        super().__init__(parent)
        self.player = player
        self.settings = settings
        self.task: Task | None = None
        self.engine = None
        self.param_widgets: dict = {}
        self._ui()
        self._load_history()
        self._engine_changed()

    @property
    def out_root(self) -> Path:
        p = project_root(self.settings) / "generated"
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ── UI ───────────────────────────────────────────────────
    def _ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        split = QSplitter(Qt.Horizontal)
        root.addWidget(split)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left = QWidget()
        lv = QVBoxLayout(left)
        left_scroll.setWidget(left)
        split.addWidget(left_scroll)

        # движок
        g = QGroupBox("Движок генерации")
        f = QFormLayout(g)
        self.engine_combo = QComboBox()
        for eid, cls in ENGINES.items():
            self.engine_combo.addItem(cls.name, eid)
        saved = self.settings.value("engine", "acestep")
        self.engine_combo.setCurrentIndex(max(0, self.engine_combo.findData(saved)))
        self.engine_combo.currentIndexChanged.connect(self._engine_changed)
        f.addRow("Движок", self.engine_combo)
        self.engine_desc = QLabel()
        self.engine_desc.setWordWrap(True)
        self.engine_desc.setObjectName("muted")
        f.addRow(self.engine_desc)

        self.ace_url = QLineEdit(self.settings.value("acestep_url", "") or "")
        self.ace_url.setPlaceholderText("http://127.0.0.1:8001 (или ACESTEP_API_URL)")
        self.ace_url.editingFinished.connect(lambda: (self.settings.setValue("acestep_url", self.ace_url.text()),
                                                      self._engine_changed()))
        self.ace_url_lbl = QLabel("Адрес ACE-Step")
        f.addRow(self.ace_url_lbl, self.ace_url)

        key_row = QHBoxLayout()
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText("GPTUNNEL_API_KEY")
        key_row.addWidget(self.api_key, 1)
        self.save_key_btn = QPushButton("В Связку ключей")
        self.save_key_btn.setToolTip("Сохранить ключ в Связке ключей macOS (не в файлах проекта)")
        self.save_key_btn.clicked.connect(self._save_key)
        key_row.addWidget(self.save_key_btn)
        self.key_lbl = QLabel("Ключ GPTunneL")
        f.addRow(self.key_lbl, key_row)
        self.api_key.editingFinished.connect(self._engine_changed)

        st_row = QHBoxLayout()
        self.engine_status = QLabel("…")
        self.engine_status.setWordWrap(True)
        st_row.addWidget(self.engine_status, 1)
        chk = QPushButton("Проверить")
        chk.clicked.connect(self._check_engine)
        st_row.addWidget(chk)
        f.addRow("Статус", st_row)
        m_row = QHBoxLayout()
        self.model_combo = QComboBox()
        self.model_combo.currentIndexChanged.connect(self._model_changed)
        m_row.addWidget(self.model_combo, 1)
        f.addRow("Модель", m_row)
        lv.addWidget(g)

        self.params_box = QGroupBox("Параметры движка")
        self.params_form = QFormLayout(self.params_box)
        lv.addWidget(self.params_box)

        # песня
        g = QGroupBox("Песня")
        f = QFormLayout(g)
        self.title_ed = QLineEdit()
        self.title_ed.setPlaceholderText("Название (необязательно)")
        f.addRow("Название", self.title_ed)
        self.style_ed = QPlainTextEdit()
        self.style_ed.setPlaceholderText("Жанр, настроение, инструменты, тип вокала. Например: "
                                         "dark synthwave, 100 bpm, deep male vocals, analog bass")
        self.style_ed.setMaximumHeight(70)
        f.addRow("Стиль", self.style_ed)
        chips = QHBoxLayout()
        chips.setSpacing(4)
        for name, text in STYLE_CHIPS.items():
            b = QPushButton(name)
            b.setObjectName("tag")
            b.setToolTip(text)
            b.clicked.connect(lambda _, t=text: self._append_style(t))
            chips.addWidget(b)
        chips.addStretch()
        chip_w = QWidget()
        chip_w.setLayout(chips)
        chip_scroll = QScrollArea()
        chip_scroll.setWidget(chip_w)
        chip_scroll.setWidgetResizable(True)
        chip_scroll.setFixedHeight(42)
        chip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        f.addRow("", chip_scroll)

        self.lyrics_ed = QPlainTextEdit()
        self.lyrics_ed.setPlaceholderText("[Verse]\nТекст куплета…\n\n[Chorus]\nПрипев…")
        self.lyrics_ed.setMinimumHeight(180)
        f.addRow("Текст", self.lyrics_ed)
        tags = QHBoxLayout()
        tags.setSpacing(4)
        for t in TAGS:
            b = QPushButton(t)
            b.setObjectName("tag")
            b.clicked.connect(lambda _, x=t: self._insert_tag(x))
            tags.addWidget(b)
        tags.addStretch()
        f.addRow("Структура", tags)
        self.instr = QCheckBox("Инструментал (без вокала)")
        self.instr.toggled.connect(lambda on: self.lyrics_ed.setEnabled(not on))
        f.addRow(self.instr)

        r1 = QHBoxLayout()
        self.duration = QDoubleSpinBox()
        self.duration.setRange(10, 600)
        self.duration.setValue(150)
        self.duration.setSuffix(" с")
        r1.addWidget(QLabel("Длина"))
        r1.addWidget(self.duration)
        self.bpm = QSpinBox()
        self.bpm.setRange(0, 300)
        self.bpm.setSpecialValueText("авто")
        r1.addWidget(QLabel("BPM"))
        r1.addWidget(self.bpm)
        self.key = QComboBox()
        self.key.addItems(KEYS)
        r1.addWidget(QLabel("Тональность"))
        r1.addWidget(self.key)
        f.addRow(r1)
        r2 = QHBoxLayout()
        self.lang = QComboBox()
        for code, name in LANGS:
            self.lang.addItem(name, code)
        r2.addWidget(QLabel("Язык"))
        r2.addWidget(self.lang)
        self.variations = QSpinBox()
        self.variations.setRange(1, 8)
        self.variations.setValue(2)
        r2.addWidget(QLabel("Вариантов"))
        r2.addWidget(self.variations)
        self.seed = QSpinBox()
        self.seed.setRange(-1, 2 ** 31 - 1)
        self.seed.setValue(-1)
        self.seed.setSpecialValueText("случайный")
        r2.addWidget(QLabel("Seed"))
        r2.addWidget(self.seed)
        f.addRow(r2)
        lv.addWidget(g)

        row = QHBoxLayout()
        self.btn_gen = QPushButton("Сгенерировать")
        self.btn_gen.setObjectName("start")
        self.btn_gen.clicked.connect(self.generate)
        row.addWidget(self.btn_gen, 2)
        self.btn_price = QPushButton("Цена")
        self.btn_price.clicked.connect(self._price)
        row.addWidget(self.btn_price)
        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.setObjectName("stop")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel)
        row.addWidget(self.btn_cancel)
        lv.addLayout(row)
        self.prog = QProgressBar()
        self.prog.setRange(0, 1000)
        lv.addWidget(self.prog)
        self.prog_lbl = QLabel("")
        self.prog_lbl.setObjectName("muted")
        self.prog_lbl.setWordWrap(True)
        lv.addWidget(self.prog_lbl)
        notice = QLabel("Публикуя сгенерированную музыку, соблюдайте лицензию модели и правила площадок "
                        "о маркировке AI-контента.")
        notice.setWordWrap(True)
        notice.setObjectName("muted")
        lv.addWidget(notice)
        lv.addStretch()

        # результаты
        right = QWidget()
        rv = QVBoxLayout(right)
        lbl = QLabel("Результаты")
        lbl.setObjectName("h1")
        rv.addWidget(lbl)
        self.results = QListWidget()
        self.results.itemDoubleClicked.connect(lambda it: self._play(it))
        self.results.currentItemChanged.connect(self._show_details)
        rv.addWidget(self.results, 1)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(160)
        rv.addWidget(self.details)
        br = QHBoxLayout()
        for text, slot, name in (("Слушать", lambda: self._play(self.results.currentItem()), ""),
                                 ("Стоп", lambda: self.player.stop(), "stop"),
                                 ("→ В студию", self._to_studio, "accent"),
                                 ("Папка", self._open_folder, ""),
                                 ("В форму", self._reuse, "")):
            b = QPushButton(text)
            if name:
                b.setObjectName(name)
            b.clicked.connect(slot)
            br.addWidget(b)
        rv.addLayout(br)
        split.addWidget(right)
        split.setSizes([620, 420])

    # ── движок ───────────────────────────────────────────────
    def _make_engine(self):
        eid = self.engine_combo.currentData()
        cls = ENGINES[eid]
        if eid == "acestep":
            return cls(base_url=self.ace_url.text().strip() or None)
        if eid == "gptunnel":
            key = self.api_key.text().strip()
            if not key:
                key, src = get_secret("gptunnel", "GPTUNNEL_API_KEY")
                if key:
                    self.api_key.setPlaceholderText(f"ключ загружен: {src}")
            return cls(api_key=key)
        return cls()

    def _engine_changed(self, *_):
        eid = self.engine_combo.currentData()
        self.settings.setValue("engine", eid)
        self.engine = self._make_engine()
        self.engine_desc.setText(self.engine.description)
        for w in (self.ace_url, self.ace_url_lbl):
            w.setVisible(eid == "acestep")
        for w in (self.api_key, self.save_key_btn, self.key_lbl):
            w.setVisible(eid == "gptunnel")
        self.btn_price.setVisible(eid == "gptunnel")
        self.engine_status.setText("нажмите «Проверить»" if eid != "demo" else "встроен, работает без сети")
        repolish(self.engine_status, "muted" if eid != "demo" else "ok")
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItem("по умолчанию", "")
        self.model_combo.blockSignals(False)
        self._rebuild_params()

    def _check_engine(self):
        eng = self._make_engine()
        self.engine = eng
        self.engine_status.setText("проверка…")

        def job(progress, cancel):
            ok, msg = eng.is_available()
            models = eng.models() if ok else []
            return ok, msg, models

        def done(res):
            ok, msg, models = res
            self.engine_status.setText(("✓ " if ok else "✗ ") + msg)
            repolish(self.engine_status, "ok" if ok else "err")
            self.model_combo.blockSignals(True)
            self.model_combo.clear()
            if not models:
                self.model_combo.addItem("по умолчанию", "")
            for m in models:
                self.model_combo.addItem(m["name"], m["id"])
                if m.get("default"):
                    self.model_combo.setCurrentIndex(self.model_combo.count() - 1)
            self.model_combo.blockSignals(False)
            self._rebuild_params()

        t = Task(job, name="check")
        t.sig.done.connect(done)
        t.sig.error.connect(lambda m: self.engine_status.setText("✗ " + m.split("\n")[0]))
        t.start()
        self._check_task = t

    def _model_changed(self, *_):
        self._rebuild_params()

    def _rebuild_params(self):
        while self.params_form.rowCount():
            self.params_form.removeRow(0)
        self.param_widgets = {}
        schema = self.engine.param_schema(self.model_combo.currentData() or "") if self.engine else []
        self.params_box.setVisible(bool(schema))
        for p in schema:
            t = p.get("type")
            if t == "enum":
                w = QComboBox()
                labels = p.get("option_labels") or [str(o) for o in p.get("options", [])]
                for val, lab in zip(p.get("options", []), labels):
                    w.addItem(str(lab), val)
                if p.get("default") is not None:
                    w.setCurrentIndex(max(0, w.findData(p["default"])))
            elif t == "boolean":
                w = QCheckBox()
                w.setChecked(bool(p.get("default")))
            elif t == "number":
                if p.get("integer"):
                    w = QSpinBox()
                    w.setRange(int(p.get("min", 0)), int(p.get("max", 10 ** 6)))
                    w.setSingleStep(int(p.get("step", 1) or 1))
                    w.setValue(int(p.get("default") or p.get("min", 0)))
                else:
                    w = QDoubleSpinBox()
                    w.setRange(float(p.get("min", 0)), float(p.get("max", 10 ** 6)))
                    w.setSingleStep(float(p.get("step", 0.1) or 0.1))
                    w.setValue(float(p.get("default") or p.get("min", 0)))
                if p.get("unit"):
                    w.setSuffix(" " + str(p["unit"]))
            else:
                w = QLineEdit(str(p.get("default") or ""))
            self.param_widgets[p["key"]] = (w, t)
            self.params_form.addRow(p.get("label") or p["key"], w)

    def _extra(self) -> dict:
        out = {}
        for k, (w, t) in self.param_widgets.items():
            if t == "enum":
                out[k] = w.currentData()
            elif t == "boolean":
                out[k] = w.isChecked()
            elif t == "number":
                out[k] = w.value()
            else:
                out[k] = w.text().strip() or None
        return out

    def _save_key(self):
        key = self.api_key.text().strip()
        if not key:
            QMessageBox.information(self, "Ключ", "Введите ключ в поле слева.")
            return
        if save_secret("gptunnel", key):
            QMessageBox.information(self, "Ключ", "Ключ сохранён в Связке ключей macOS (сервис ai-music-studio).")
        else:
            QMessageBox.information(self, "Ключ", "Связка ключей недоступна. Используйте переменную окружения "
                                                  "GPTUNNEL_API_KEY (см. .env.example).")

    # ── форма ────────────────────────────────────────────────
    def _append_style(self, text):
        cur = self.style_ed.toPlainText().strip()
        self.style_ed.setPlainText(f"{cur}, {text}" if cur else text)

    def _insert_tag(self, tag):
        c = self.lyrics_ed.textCursor()
        prefix = "" if c.atBlockStart() else "\n"
        c.insertText(f"{prefix}{tag}\n")
        self.lyrics_ed.setFocus()

    def build_request(self) -> GenerationRequest:
        key = self.key.currentText()
        return GenerationRequest(
            title=self.title_ed.text().strip(),
            style=self.style_ed.toPlainText().strip(),
            lyrics=self.lyrics_ed.toPlainText().strip(),
            instrumental=self.instr.isChecked(),
            duration=self.duration.value(),
            bpm=self.bpm.value() or None,
            key="" if key == "Авто" else key,
            language=self.lang.currentData(),
            seed=None if self.seed.value() < 0 else self.seed.value(),
            variations=self.variations.value(),
            model=self.model_combo.currentData() or "",
            extra=self._extra(),
        )

    # ── генерация ────────────────────────────────────────────
    def generate(self):
        req = self.build_request()
        if not req.style and not req.lyrics and self.engine_combo.currentData() != "demo":
            QMessageBox.information(self, "Пусто", "Опишите стиль или вставьте текст песни.")
            return
        eng = self._make_engine()
        out = self.out_root / time.strftime("%Y-%m-%d")
        self.btn_gen.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.prog.setValue(0)
        self.task = Task(lambda p, c: eng.generate(req, out, progress=p, cancel=c), name="generate")
        self.task.sig.progress.connect(lambda f, m: (self.prog.setValue(int(f * 1000)), self.prog_lbl.setText(m)))
        self.task.sig.done.connect(self._gen_done)
        self.task.sig.error.connect(self._gen_err)
        self.task.start()
        self.status.emit(f"Генерация: {eng.name}")

    def _gen_done(self, tracks):
        self.btn_gen.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        for t in tracks:
            self._add_result(t, top=True)
        self.results.setCurrentRow(0)
        self.prog_lbl.setText(f"Готово: {len(tracks)} трек(а) · {tracks[0].path.parent}")
        self.status.emit(f"Сгенерировано: {len(tracks)}")

    def _gen_err(self, msg):
        self.btn_gen.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        first = msg.split("\n")[0]
        self.prog_lbl.setText("Ошибка: " + first)
        if "отмен" not in first.lower():
            QMessageBox.warning(self, "Генерация", first)

    def _cancel(self):
        if self.task:
            self.task.cancel()

    def _price(self):
        eng = self._make_engine()
        req = self.build_request()
        self.prog_lbl.setText("Расчёт цены…")
        t = Task(lambda p, c: eng.estimate_price(req), name="price")
        t.sig.done.connect(lambda s: self.prog_lbl.setText(f"Цена: {s or 'нет данных'}"))
        t.sig.error.connect(lambda m: self.prog_lbl.setText("Цена: " + m.split("\n")[0]))
        t.start()
        self._price_task = t

    # ── результаты ───────────────────────────────────────────
    def _add_result(self, t: GeneratedTrack, top: bool = False):
        dur = t.meta.get("duration")
        label = f"{t.title}  ·  {t.engine}" + (f"  ·  {float(dur):.0f} с" if dur else "")
        it = QListWidgetItem(label)
        it.setData(Qt.UserRole, t)
        it.setToolTip(str(t.path))
        if top:
            self.results.insertItem(0, it)
        else:
            self.results.addItem(it)

    def _load_history(self):
        files = sorted(self.out_root.glob("*/**/*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:100]
        for side in files:
            if side.name.endswith(".studio.json") or side.name.endswith(".report.json"):
                continue
            try:
                t = GeneratedTrack.from_sidecar(side)
                if not t.path.exists():
                    continue
                self._add_result(t)
            except (OSError, ValueError, KeyError):
                continue

    def _current(self) -> GeneratedTrack | None:
        it = self.results.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _show_details(self, *_):
        t = self._current()
        if not t:
            self.details.setPlainText("")
            return
        meta = "\n".join(f"{k}: {v}" for k, v in t.meta.items() if v not in (None, "", [], {}))
        stems = f"\nДорожки: {', '.join(t.stems)}" if t.stems else ""
        self.details.setPlainText(f"{t.path}\n{meta}{stems}\n\n{t.lyrics or ''}".strip())

    def _play(self, it):
        t = it.data(Qt.UserRole) if it else None
        if t:
            self.player.play(t.path)

    def _to_studio(self):
        t = self._current()
        if not t:
            QMessageBox.information(self, "Студия", "Выберите трек в списке результатов.")
            return
        self.send_to_studio.emit(t)

    def _open_folder(self):
        t = self._current()
        open_in_finder(t.path if t else self.out_root)

    def _reuse(self):
        t = self._current()
        if not t:
            return
        self.title_ed.setText(t.title)
        if t.meta.get("prompt") or t.meta.get("tags"):
            self.style_ed.setPlainText(str(t.meta.get("prompt") or t.meta.get("tags")))
        if t.lyrics:
            self.lyrics_ed.setPlainText(t.lyrics)
