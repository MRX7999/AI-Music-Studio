"""Плеер: QMediaPlayer, если доступен QtMultimedia; иначе afplay (macOS) / ffplay."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PyQt5.QtCore import QObject, QUrl, pyqtSignal

try:
    from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer
    _HAVE_QTMM = True
except Exception:  # нет libpulse/кодеков — используем внешний плеер
    _HAVE_QTMM = False


class Player(QObject):
    state_changed = pyqtSignal(bool, str)   # играет?, файл

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: subprocess.Popen | None = None
        self._mp = None
        self.current: str = ""
        if _HAVE_QTMM:
            try:
                self._mp = QMediaPlayer(self)
                self._mp.stateChanged.connect(self._on_state)
            except Exception:
                self._mp = None

    @property
    def backend(self) -> str:
        if self._mp is not None:
            return "QtMultimedia"
        if sys.platform == "darwin" and shutil.which("afplay"):
            return "afplay"
        if shutil.which("ffplay"):
            return "ffplay"
        return "нет"

    def play(self, path: str | Path):
        self.stop()
        self.current = str(path)
        if self._mp is not None:
            self._mp.setMedia(QMediaContent(QUrl.fromLocalFile(self.current)))
            self._mp.play()
            return
        if self.backend == "afplay":
            cmd = ["afplay", self.current]
        elif self.backend == "ffplay":
            cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", self.current]
        else:
            self.state_changed.emit(False, "нет плеера (установите ffmpeg)")
            return
        self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.state_changed.emit(True, self.current)

    def stop(self):
        if self._mp is not None:
            self._mp.stop()
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
        self._proc = None
        self.state_changed.emit(False, self.current)

    def is_playing(self) -> bool:
        if self._mp is not None:
            return self._mp.state() == QMediaPlayer.PlayingState
        return bool(self._proc and self._proc.poll() is None)

    def _on_state(self, st):
        self.state_changed.emit(st == QMediaPlayer.PlayingState, self.current)
