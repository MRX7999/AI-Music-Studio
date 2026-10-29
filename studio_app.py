#!/usr/bin/env python3
"""AI Music Studio — генерация песен и виртуальная студия записи.

Запуск:  python studio_app.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> int:
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName("AI Music Studio")
    app.setOrganizationName("AI-Music-Studio")
    from studio.ui.main_window import MainWindow

    win = MainWindow()
    win.show()
    if os.environ.get("AMS_SMOKE"):          # самопроверка запуска: окно открылось и закрылось
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(int(os.environ.get("AMS_SMOKE_MS", "1500")), app.quit)
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
