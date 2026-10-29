#!/usr/bin/env python3
"""
gui_pipeline.py — GUI для full_pipeline.py на PyQt5
Запуск: python gui_pipeline.py
"""

import sys, threading, queue, os, subprocess
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QTextEdit,
    QProgressBar, QSlider, QGroupBox, QMessageBox,
    QListWidget, QListWidgetItem, QComboBox, QCheckBox,
    QLineEdit, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject
from PyQt5.QtGui import QColor

AUDIO_EXTS = {".m4a", ".wav", ".flac", ".mp3", ".aiff", ".aif", ".ogg"}
PYEXE  = sys.executable
SCRIPT = Path(__file__).parent / "full_pipeline.py"

# ── Стиль (Catppuccin Mocha — как у тебя) ────────────────────────────────────
STYLE = """
QWidget        { background:#1e1e2e; color:#cdd6f4;
                 font-family:Menlo,Monaco,monospace; font-size:12px; }
QGroupBox      { border:1px solid #45475a; border-radius:6px;
                 margin-top:10px; padding:8px; }
QGroupBox::title { subcontrol-origin:margin; left:10px;
                   color:#89b4fa; font-weight:bold; }
QLineEdit      { background:#313244; border:1px solid #45475a;
                 border-radius:4px; padding:4px 8px; }
QLineEdit:focus{ border-color:#89b4fa; }
QPushButton    { background:#313244; border:1px solid #45475a;
                 border-radius:6px; padding:6px 14px; }
QPushButton:hover   { background:#45475a; }
QPushButton#start   { background:#89b4fa; color:#1e1e2e;
                       font-weight:bold; font-size:14px; }
QPushButton#start:hover    { background:#74c7ec; }
QPushButton#start:disabled { background:#45475a; color:#6c7086; }
QPushButton#stop    { color:#f38ba8; border-color:#f38ba8; }
QPushButton#stop:hover     { background:#3d2a2e; }
QPushButton#stop:disabled  { color:#45475a; border-color:#45475a; }
QTextEdit      { background:#181825; border:1px solid #313244;
                 border-radius:4px; padding:6px;
                 color:#a6e3a1; font-size:11px; }
QProgressBar   { background:#313244; border:1px solid #45475a;
                 border-radius:4px; text-align:center; height:20px; }
QProgressBar::chunk { background:#89b4fa; border-radius:3px; }
QSlider::groove:horizontal { background:#313244; height:6px; border-radius:3px; }
QSlider::handle:horizontal { background:#89b4fa; width:16px; height:16px;
                              margin:-5px 0; border-radius:8px; }
QListWidget    { background:#181825; border:1px solid #313244;
                 border-radius:4px; padding:4px; }
QListWidget::item          { padding:3px 6px; border-radius:3px; }
QListWidget::item:selected { background:#313244; }
QComboBox      { background:#313244; border:1px solid #45475a;
                 border-radius:4px; padding:4px 8px; }
QComboBox::drop-down { border:none; width:20px; }
QComboBox QAbstractItemView { background:#313244; border:1px solid #45475a;
                               selection-background-color:#45475a; }
QCheckBox      { spacing:6px; }
QCheckBox::indicator       { width:14px; height:14px; border-radius:3px;
                              border:1px solid #45475a; background:#313244; }
QCheckBox::indicator:checked { background:#89b4fa; border-color:#89b4fa; }
"""


# ════════════════════════════════════════════════════════════════════════════
#  SIGNALS + WORKER
# ════════════════════════════════════════════════════════════════════════════

class Signals(QObject):
    log          = pyqtSignal(str)
    track_start  = pyqtSignal(str)
    track_done   = pyqtSignal(str)
    track_error  = pyqtSignal(str)
    progress     = pyqtSignal(int, int)   # current, total
    finished     = pyqtSignal()


class PipelineWorker(threading.Thread):
    def __init__(self, tracks: list, out_dir: Path, params: dict, sig: Signals):
        super().__init__(daemon=True)
        self.tracks  = tracks
        self.out_dir = out_dir
        self.params  = params
        self.sig     = sig
        self._stop   = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        total = len(self.tracks)
        for idx, track in enumerate(self.tracks):
            if self._stop.is_set():
                break

            self.sig.track_start.emit(track.name)
            success = self._process(track)

            if success:
                self.sig.track_done.emit(track.name)
            else:
                self.sig.track_error.emit(track.name)

            self.sig.progress.emit(idx + 1, total)

        self.sig.finished.emit()

    def _process(self, track: Path) -> bool:
        cmd = [
            str(PYEXE), str(SCRIPT),
            str(track),
            "--output-dir", str(self.out_dir),
            "--steps",    str(self.params["steps"]),
            "--guidance", str(self.params["guidance"]),
            "--humanize-intensity", self.params["intensity"],
            "--device",   self.params["device"],
            "--format",   self.params["format"],
            "--seed",     str(self.params["seed"]),
        ]
        if self.params.get("no_audiosr"):  cmd.append("--no-audiosr")
        if self.params.get("no_humanize"): cmd.append("--no-humanize")
        if self.params.get("no_noise"):    cmd.append("--no-noise")

        env = os.environ.copy()
        env["HF_HUB_OFFLINE"] = "1"

        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, env=env,
            )
            for line in proc.stdout:
                if self._stop.is_set():
                    proc.terminate()
                    return False
                line = line.rstrip()
                if line:
                    self.sig.log.emit(line)
            proc.wait()
            return proc.returncode == 0
        except Exception as e:
            self.sig.log.emit(f"[ERR] {e}")
            return False


# ════════════════════════════════════════════════════════════════════════════
#  ГЛАВНОЕ ОКНО
# ════════════════════════════════════════════════════════════════════════════

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Audio Pipeline")
        self.resize(900, 720)
        self.setStyleSheet(STYLE)

        self.tracks:   list[Path] = []
        self.out_dir:  Path | None = None
        self.worker:   PipelineWorker | None = None
        self.sig = Signals()
        self.sig.log.connect(self._on_log)
        self.sig.track_start.connect(self._on_track_start)
        self.sig.track_done.connect(self._on_track_done)
        self.sig.track_error.connect(self._on_track_error)
        self.sig.progress.connect(self._on_progress)
        self.sig.finished.connect(self._on_finished)

        self._ui()

    # ── Layout ───────────────────────────────────────────────────────────────

    def _ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(14, 14, 14, 14)

        # Заголовок
        title = QLabel("▶  Audio Pipeline")
        title.setStyleSheet("font-size:18px; font-weight:bold; color:#cdd6f4; padding:4px 0;")
        root.addWidget(title)

        # Основная часть: левая (папки+треклист) + правая (настройки)
        mid = QHBoxLayout()
        mid.setSpacing(10)
        root.addLayout(mid, stretch=1)

        # Левая колонка
        left = QVBoxLayout()
        left.setSpacing(8)
        mid.addLayout(left, stretch=1)

        self._build_folders(left)
        self._build_tracklist(left)

        # Правая колонка — настройки
        right_box = QGroupBox("Настройки")
        right_box.setFixedWidth(240)
        right_lay = QVBoxLayout(right_box)
        right_lay.setSpacing(6)
        mid.addWidget(right_box)
        self._build_settings(right_lay)
        right_lay.addStretch()

        # Нижняя панель
        self._build_bottom(root)

    # ── Папки ────────────────────────────────────────────────────────────────

    def _build_folders(self, parent):
        g = QGroupBox("Папки")
        lay = QVBoxLayout(g)
        lay.setSpacing(6)

        r1 = QHBoxLayout()
        b1 = QPushButton("📂  Входная папка")
        b1.clicked.connect(self._choose_input)
        self.lbl_in = QLabel("не выбрана")
        self.lbl_in.setStyleSheet("color:#6c7086;")
        self.lbl_in.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        r1.addWidget(b1); r1.addWidget(self.lbl_in, 1)
        lay.addLayout(r1)

        r2 = QHBoxLayout()
        b2 = QPushButton("💾  Выходная папка")
        b2.clicked.connect(self._choose_output)
        self.lbl_out = QLabel("авто (рядом с входной)")
        self.lbl_out.setStyleSheet("color:#6c7086;")
        self.lbl_out.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        r2.addWidget(b2); r2.addWidget(self.lbl_out, 1)
        lay.addLayout(r2)

        parent.addWidget(g)

    # ── Список треков ─────────────────────────────────────────────────────────

    def _build_tracklist(self, parent):
        g = QGroupBox("Очередь треков")
        lay = QVBoxLayout(g)
        self.track_list = QListWidget()
        self.track_list.setSelectionMode(QListWidget.NoSelection)
        lay.addWidget(self.track_list)
        parent.addWidget(g, stretch=1)

    # ── Настройки ────────────────────────────────────────────────────────────

    def _build_settings(self, lay):
        # Steps
        r = QHBoxLayout()
        r.addWidget(QLabel("Steps"))
        self.steps_lbl = QLabel("12")
        self.steps_lbl.setStyleSheet("color:#89b4fa; font-weight:bold; min-width:28px;")
        r.addWidget(self.steps_lbl)
        lay.addLayout(r)
        self.steps_sl = QSlider(Qt.Horizontal)
        self.steps_sl.setRange(4, 50); self.steps_sl.setValue(12)
        self.steps_sl.valueChanged.connect(lambda v: self.steps_lbl.setText(str(v)))
        lay.addWidget(self.steps_sl)

        # Guidance
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Guidance"))
        self.guid_lbl = QLabel("2.0")
        self.guid_lbl.setStyleSheet("color:#89b4fa; font-weight:bold; min-width:28px;")
        r2.addWidget(self.guid_lbl)
        lay.addLayout(r2)
        self.guid_sl = QSlider(Qt.Horizontal)
        self.guid_sl.setRange(10, 50); self.guid_sl.setValue(20)  # x10
        self.guid_sl.valueChanged.connect(lambda v: self.guid_lbl.setText(f"{v/10:.1f}"))
        lay.addWidget(self.guid_sl)

        lay.addSpacing(6)

        # Intensity
        lay.addWidget(QLabel("Intensity"))
        self.intensity_cb = QComboBox()
        self.intensity_cb.addItems(["ultra-low", "low", "medium", "high"])
        lay.addWidget(self.intensity_cb)

        # Device
        lay.addWidget(QLabel("Device"))
        self.device_cb = QComboBox()
        self.device_cb.addItems(["mps", "cuda", "cpu"])
        lay.addWidget(self.device_cb)

        # Format
        lay.addWidget(QLabel("Format"))
        self.format_cb = QComboBox()
        self.format_cb.addItems(["alac", "flac"])
        lay.addWidget(self.format_cb)

        lay.addSpacing(6)

        # Опции
        self.chk_no_audiosr  = QCheckBox("Пропустить AudioSR")
        self.chk_no_humanize = QCheckBox("Пропустить Humanize")
        self.chk_no_noise    = QCheckBox("Без шума")
        lay.addWidget(self.chk_no_audiosr)
        lay.addWidget(self.chk_no_humanize)
        lay.addWidget(self.chk_no_noise)

        lay.addSpacing(6)

        # Seed
        r3 = QHBoxLayout()
        r3.addWidget(QLabel("Seed"))
        self.seed_edit = QLineEdit("42")
        self.seed_edit.setFixedWidth(70)
        r3.addWidget(self.seed_edit)
        lay.addLayout(r3)

    # ── Нижняя панель ─────────────────────────────────────────────────────────

    def _build_bottom(self, root):
        # Кнопки
        btn_row = QHBoxLayout()
        self.btn_start = QPushButton("▶  Запустить")
        self.btn_start.setObjectName("start")
        self.btn_start.setMinimumHeight(44)
        self.btn_start.clicked.connect(self._start)
        self.btn_stop = QPushButton("■  Стоп")
        self.btn_stop.setObjectName("stop")
        self.btn_stop.setMinimumHeight(44)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop)
        btn_clear = QPushButton("Очистить лог")
        btn_clear.setMinimumHeight(44)
        btn_clear.clicked.connect(lambda: self.log_box.clear())
        btn_row.addWidget(self.btn_start)
        btn_row.addWidget(self.btn_stop)
        btn_row.addStretch()
        btn_row.addWidget(btn_clear)
        root.addLayout(btn_row)

        # Прогресс
        prog_row = QHBoxLayout()
        self.prog_lbl = QLabel("Ожидание...")
        self.prog_lbl.setStyleSheet("color:#6c7086;")
        self.prog_stats = QLabel("")
        self.prog_stats.setStyleSheet("color:#6c7086;")
        prog_row.addWidget(self.prog_lbl, 1)
        prog_row.addWidget(self.prog_stats)
        root.addLayout(prog_row)

        self.pbar = QProgressBar()
        self.pbar.setRange(0, 100)
        self.pbar.setValue(0)
        root.addWidget(self.pbar)

        # Лог
        root.addWidget(QLabel("Лог:"))
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(180)
        root.addWidget(self.log_box)

    # ── Выбор папок ──────────────────────────────────────────────────────────

    def _choose_input(self):
        d = QFileDialog.getExistingDirectory(self, "Входная папка с треками")
        if not d:
            return
        p = Path(d)
        self._load_tracks(p)

    def _choose_output(self):
        d = QFileDialog.getExistingDirectory(self, "Выходная папка")
        if not d:
            return
        self.out_dir = Path(d)
        self.lbl_out.setStyleSheet("color:#cdd6f4;")
        self.lbl_out.setText(str(self.out_dir))
        self._log(f"Выходная папка: {self.out_dir}")

    def _load_tracks(self, folder: Path):
        self.tracks = sorted(
            p for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in AUDIO_EXTS
        )
        self.track_list.clear()
        for t in self.tracks:
            item = QListWidgetItem(f"  {t.name}")
            item.setForeground(QColor("#6c7086"))
            self.track_list.addItem(item)

        self.lbl_in.setStyleSheet("color:#cdd6f4;")
        self.lbl_in.setText(f"{folder.name}  ({len(self.tracks)} треков)")

        if self.out_dir is None:
            self.out_dir = folder.parent / (folder.name + " — processed")
            self.lbl_out.setStyleSheet("color:#6c7086;")
            self.lbl_out.setText(str(self.out_dir) + "  (авто)")

        self._log(f"Найдено {len(self.tracks)} треков в «{folder.name}»")

    # ── Запуск / стоп ────────────────────────────────────────────────────────

    def _start(self):
        if not self.tracks:
            return QMessageBox.warning(self, "", "Сначала выберите входную папку.")
        if self.out_dir is None:
            return QMessageBox.warning(self, "", "Укажи папку для результата.")
        if not SCRIPT.exists():
            return QMessageBox.critical(self, "Ошибка",
                f"full_pipeline.py не найден:\n{SCRIPT}\n\nОба файла должны лежать в одной папке.")

        self.out_dir.mkdir(parents=True, exist_ok=True)

        # Сброс цветов треков
        for i in range(self.track_list.count()):
            self.track_list.item(i).setForeground(QColor("#6c7086"))

        params = {
            "steps":       self.steps_sl.value(),
            "guidance":    self.guid_sl.value() / 10,
            "intensity":   self.intensity_cb.currentText(),
            "device":      self.device_cb.currentText(),
            "format":      self.format_cb.currentText(),
            "no_audiosr":  self.chk_no_audiosr.isChecked(),
            "no_humanize": self.chk_no_humanize.isChecked(),
            "no_noise":    self.chk_no_noise.isChecked(),
            "seed":        self.seed_edit.text() or "42",
        }

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.pbar.setValue(0)
        self.log_box.clear()
        self._log("═" * 50)
        self._log(f"Старт  ·  {len(self.tracks)} треков  ·  "
                  f"steps={params['steps']}  guidance={params['guidance']}  "
                  f"intensity={params['intensity']}")
        self._log("═" * 50)

        self._current_idx = 0
        self._total       = len(self.tracks)
        self._done_count  = 0
        self._err_count   = 0

        self.worker = PipelineWorker(self.tracks, self.out_dir, params, self.sig)
        self.worker.start()

    def _stop(self):
        if self.worker:
            self.worker.stop()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._log("⏹  Остановлено.")

    # ── Слоты сигналов ────────────────────────────────────────────────────────

    def _on_log(self, msg: str):
        self.log_box.append(msg)

    def _on_track_start(self, name: str):
        self._log(f"\n▶  {name}")
        # Подсветить текущий элемент
        item = self.track_list.item(self._current_idx)
        if item:
            item.setForeground(QColor("#89b4fa"))  # синий = в процессе

    def _on_track_done(self, name: str):
        item = self.track_list.item(self._current_idx)
        if item:
            item.setForeground(QColor("#a6e3a1"))  # зелёный = готово
        self._done_count += 1
        self._current_idx += 1
        self._log(f"✅  {name} — готово")

    def _on_track_error(self, name: str):
        item = self.track_list.item(self._current_idx)
        if item:
            item.setForeground(QColor("#f38ba8"))  # красный = ошибка
        self._err_count += 1
        self._current_idx += 1
        self._log(f"✗  {name} — ошибка")

    def _on_progress(self, current: int, total: int):
        pct = int(current / total * 100)
        self.pbar.setValue(pct)
        self.prog_lbl.setText(f"[{current}/{total}]")
        self.prog_stats.setText(f"✓ {self._done_count}  ✗ {self._err_count}")

    def _on_finished(self):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.pbar.setValue(100)
        self._log("═" * 50)
        if self._err_count == 0:
            self._log(f"✅  Все {self._done_count} треков готовы → {self.out_dir}")
        else:
            self._log(f"⚠  Готово: {self._done_count} ок, {self._err_count} ошибок")
        self._log("═" * 50)
        QMessageBox.information(self, "Готово",
            f"Обработано: {self._done_count} треков\n"
            f"Ошибок: {self._err_count}\n\n"
            f"Результат:\n{self.out_dir}")

    def _log(self, msg: str):
        self.log_box.append(msg)


# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if not SCRIPT.exists():
        alt = Path.cwd() / "full_pipeline.py"
        if alt.exists():
            SCRIPT = alt
        else:
            print(f"[WARN] full_pipeline.py не найден рядом с gui_pipeline.py")

    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())
