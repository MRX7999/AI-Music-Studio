"""Главное окно: Генерация → Студия → Мастеринг → Плейлист."""
from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QSettings, Qt
from PyQt5.QtWidgets import (QAction, QFileDialog, QLabel, QMainWindow, QMessageBox, QStatusBar, QTabWidget,
                             QWidget)

from .. import APP_NAME, __version__
from ..generators import GeneratedTrack
from .. import stems as stems_mod
from .generate_tab import GenerateTab
from .player import Player
from .playlist_tab import PlaylistTab
from .studio_tab import StudioTab
from .paths import root_warning
from .style import STYLE


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings | None = None):
        super().__init__()
        self.settings = settings or QSettings("AI-Music-Studio", "AI Music Studio")
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1360, 900)
        self.setStyleSheet(STYLE)
        self.player = Player(self)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.gen = GenerateTab(self.player, self.settings)
        self.studio = StudioTab(self.player, self.settings)
        self.tabs.addTab(self.gen, "1 · Генерация")
        self.tabs.addTab(self.studio, "2 · Студия")
        self.tabs.addTab(self._mastering(), "3 · Мастеринг")
        self.tabs.addTab(PlaylistTab(self.settings), "4 · Плейлист")

        sb = QStatusBar()
        self.setStatusBar(sb)
        self.player_lbl = QLabel(f"плеер: {self.player.backend}")
        self.player_lbl.setObjectName("muted")
        sb.addPermanentWidget(self.player_lbl)
        self.gen.status.connect(lambda m: sb.showMessage(m, 8000))
        self.studio.status.connect(lambda m: sb.showMessage(m, 8000))
        self.gen.send_to_studio.connect(self.open_in_studio)
        self.player.state_changed.connect(
            lambda on, f: self.player_lbl.setText(("▶ " + Path(f).name) if on and f else f"плеер: {self.player.backend}"))
        self._menu()
        warn = root_warning(self.settings)
        sb.showMessage(f"Папка проекта: {self.studio.out_root}" + (f" · {warn}" if warn else ""), 20000)

    def _mastering(self) -> QWidget:
        try:
            from gui_pipeline import MainWindow as PipelineWindow
            w = PipelineWindow()
            w.setStyleSheet("")      # общий стиль задаёт главное окно
            return w
        except Exception as e:     # без зависимостей мастеринга студия всё равно работает
            lbl = QLabel(f"Мастеринг-пайплайн недоступен: {e}")
            lbl.setAlignment(Qt.AlignCenter)
            return lbl

    def _menu(self):
        m = self.menuBar().addMenu("Файл")
        for text, slot, sc in (("Новая сессия", self.studio.new_session, "Ctrl+N"),
                               ("Открыть сессию…", self.studio.open_session, "Ctrl+O"),
                               ("Сохранить сессию", self.studio.save_session, "Ctrl+S"),
                               ("Импорт песни в студию…", self.studio.import_song_dialog, "Ctrl+I"),
                               ("Папка проектов…", self.choose_output, None)):
            a = QAction(text, self)
            if sc:
                a.setShortcut(sc)
            a.triggered.connect(slot)
            m.addAction(a)
        h = self.menuBar().addMenu("Справка")
        a = QAction("О программе", self)
        a.triggered.connect(self.about)
        h.addAction(a)

    def choose_output(self):
        d = QFileDialog.getExistingDirectory(self, "Папка проектов", str(self.studio.out_root))
        if d:
            self.settings.setValue("output_dir", d)
            self.statusBar().showMessage(f"Папка проектов: {d}", 8000)

    def open_in_studio(self, t: GeneratedTrack):
        meta = {**t.meta, "title": t.title, "lyrics": t.lyrics, "engine": t.engine}
        if t.cover:
            meta["cover"] = str(t.cover)
        self.tabs.setCurrentWidget(self.studio)
        if t.stems and all(Path(p).exists() for p in t.stems.values()):
            self.studio.import_song(Path(t.path), meta=meta, stems=t.stems)
        else:
            method = self.studio.ask_method()
            if method:
                self.studio.import_song(Path(t.path), meta=meta, method=method)

    def about(self):
        QMessageBox.about(self, APP_NAME,
                          f"<b>{APP_NAME} {__version__}</b><br>Генерация песен (ACE-Step, Suno через GPTunneL) и "
                          f"виртуальная студия записи: помещения, микрофоны, пульт, мастер.<br><br>"
                          f"Разделение на дорожки: {', '.join(stems_mod.available_methods().values())}<br>"
                          f"Плеер: {self.player.backend}<br>Лицензия MIT.")

    def closeEvent(self, e):
        self.player.stop()
        super().closeEvent(e)
