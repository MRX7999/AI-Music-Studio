"""Фоновые задачи: threading.Thread + Qt-сигналы (тот же подход, что в gui_pipeline.py)."""
from __future__ import annotations

import threading
import traceback

from PyQt5.QtCore import QObject, pyqtSignal


class TaskSignals(QObject):
    progress = pyqtSignal(float, str)
    done = pyqtSignal(object)
    error = pyqtSignal(str)
    log = pyqtSignal(str)


class Task(threading.Thread):
    """fn(progress, cancel) → результат. Сигналы приходят в GUI-поток через Qt."""

    def __init__(self, fn, *, name: str = "task"):
        super().__init__(daemon=True, name=name)
        self.fn = fn
        self.sig = TaskSignals()
        self._stop = threading.Event()

    def cancel(self):
        self._stop.set()

    def cancelled(self) -> bool:
        return self._stop.is_set()

    def run(self):
        try:
            res = self.fn(lambda f, m="": self.sig.progress.emit(float(f), str(m)), self.cancelled)
            self.sig.done.emit(res)
        except Exception as e:  # ошибки показываем в интерфейсе, а не роняем приложение
            tb = traceback.format_exc(limit=4)
            self.sig.error.emit(f"{e}\n\n{tb}" if not str(e) else str(e) + "\n\n" + tb)
