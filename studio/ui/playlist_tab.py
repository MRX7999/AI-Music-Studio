"""Вкладка «Плейлист»: интерфейс к download_playlist.py (скачивание плейлиста Suno/GPTunneL)."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLineEdit,
                             QPushButton, QSpinBox, QTextEdit, QVBoxLayout, QWidget)

from .paths import project_root

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "download_playlist.py"


class _Sig(QObject):
    line = pyqtSignal(str)
    done = pyqtSignal(int)


class PlaylistTab(QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.proc: subprocess.Popen | None = None
        self.sig = _Sig()
        self.sig.line.connect(self._log)
        self.sig.done.connect(self._done)
        v = QVBoxLayout(self)
        g = QGroupBox("Плейлист GPTunneL / Suno")
        f = QFormLayout(g)
        self.url = QLineEdit(os.environ.get("GPTUNNEL_PLAYLIST_URL", "") or self.settings.value("playlist_url", ""))
        self.url.setPlaceholderText("https://app.gptunnel.ai/app/ipod?playlist=…  или id")
        f.addRow("Ссылка", self.url)
        self.album = QLineEdit(self.settings.value("playlist_album", ""))
        self.album.setPlaceholderText("Название альбома в тегах")
        f.addRow("Альбом", self.album)
        row = QHBoxLayout()
        self.out = QLineEdit(self.settings.value("playlist_out", str(project_root(self.settings) / "Suno")))
        row.addWidget(self.out, 1)
        b = QPushButton("…")
        b.clicked.connect(self._choose)
        row.addWidget(b)
        f.addRow("Папка", row)
        self.fmt = QComboBox()
        for k, t in (("", "MP3 (как есть)"), ("--alac", "ALAC .m4a (Apple Music)"), ("--flac", "FLAC")):
            self.fmt.addItem(t, k)
        f.addRow("Формат", self.fmt)
        self.master = QCheckBox("Тех-мастеринг ffmpeg (EBU R128 + лимитер)")
        f.addRow(self.master)
        self.upscale = QCheckBox("AI-апскейлинг AudioSR (нужен pip install audiosr)")
        f.addRow(self.upscale)
        self.steps = QSpinBox()
        self.steps.setRange(10, 200)
        self.steps.setValue(50)
        f.addRow("Шаги AudioSR", self.steps)
        self.lyrics = QCheckBox("Распознать текст whisper.cpp (.lrc)")
        f.addRow(self.lyrics)
        self.keep = QCheckBox("Сохранить исходный MP3")
        f.addRow(self.keep)
        v.addWidget(g)
        row = QHBoxLayout()
        self.go = QPushButton("Скачать")
        self.go.setObjectName("start")
        self.go.clicked.connect(self.start)
        row.addWidget(self.go)
        self.stop_btn = QPushButton("Стоп")
        self.stop_btn.setObjectName("stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        row.addWidget(self.stop_btn)
        v.addLayout(row)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        v.addWidget(self.log, 1)

    def _choose(self):
        d = QFileDialog.getExistingDirectory(self, "Папка для плейлиста", self.out.text())
        if d:
            self.out.setText(d)

    def build_cmd(self) -> list[str]:
        cmd = [sys.executable, "-u", str(SCRIPT), "--url", self.url.text().strip(), "--out", self.out.text().strip()]
        if self.album.text().strip():
            cmd += ["--album", self.album.text().strip()]
        if self.fmt.currentData():
            cmd.append(self.fmt.currentData())
        if self.master.isChecked():
            cmd.append("--master")
        if self.upscale.isChecked():
            cmd += ["--upscale", "--ddim-steps", str(self.steps.value())]
        if self.lyrics.isChecked():
            cmd.append("--lyrics")
        if self.keep.isChecked() and self.fmt.currentData():
            cmd.append("--keep-mp3")
        return cmd

    def start(self):
        if not self.url.text().strip():
            self._log("Укажите ссылку на плейлист.")
            return
        for k, w in (("playlist_url", self.url), ("playlist_album", self.album), ("playlist_out", self.out)):
            self.settings.setValue(k, w.text())
        cmd = self.build_cmd()
        self._log("$ " + " ".join(cmd[2:]))
        self.go.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, bufsize=1)

        def pump():
            for line in self.proc.stdout:
                self.sig.line.emit(line.rstrip())
            self.sig.done.emit(self.proc.wait())

        threading.Thread(target=pump, daemon=True).start()

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()

    def _log(self, s: str):
        self.log.append(s)

    def _done(self, code: int):
        self.go.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._log("Готово." if code == 0 else f"Завершено с кодом {code}")
