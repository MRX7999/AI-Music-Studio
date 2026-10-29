#!/usr/bin/env python3
"""Скриншоты интерфейса для README (работает и без дисплея: QT_QPA_PLATFORM=offscreen).

    QT_QPA_PLATFORM=offscreen python scripts/make_screenshots.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs" / "screenshots"


def main():
    from PyQt5.QtCore import QSettings, Qt
    from PyQt5.QtWidgets import QApplication

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    from studio.generators import DemoGenerator, GenerationRequest
    from studio.render import render_preview
    from studio.ui.main_window import MainWindow

    tmp = Path(tempfile.mkdtemp(prefix="ams_shots_"))
    settings = QSettings(str(tmp / "settings.ini"), QSettings.IniFormat)
    settings.setValue("output_dir", str(tmp / "projects"))
    settings.setValue("engine", "acestep")
    win = MainWindow(settings)
    win.resize(1440, 920)
    win.show()
    OUT.mkdir(parents=True, exist_ok=True)

    g = win.gen
    g.title_ed.setText("Северный ветер")
    g.style_ed.setPlainText("indie rock, warm analog, live drums, emotional male vocals, 104 bpm")
    g.lyrics_ed.setPlainText("[Intro]\n\n[Verse]\nНочь опускается на крыши домов,\nи город молчит, как забытый альбом\n\n"
                             "[Chorus]\nСеверный ветер, неси меня домой,\nсквозь огни и туман за собой\n\n[Bridge]\n…\n\n[Outro]")
    g.bpm.setValue(104)
    g.key.setCurrentText("A minor")
    tracks = DemoGenerator().generate(GenerationRequest(title="Северный ветер (демо)", duration=40, bpm=104,
                                                        key="A minor", seed=3), tmp / "projects" / "generated")
    for t in tracks:
        g._add_result(t, top=True)
    g.results.setCurrentRow(0)
    win.tabs.setCurrentIndex(0)
    app.processEvents()
    win.grab().save(str(OUT / "generate.png"))

    win.open_in_studio(tracks[0])
    s = win.studio
    s.session.set_scene("live_room")
    s._load_session_into_ui()
    vocal_like = next((c for c in s.session.channels if c.instrument == "piano"), s.session.channels[0])
    s.select_channel(vocal_like.id)
    r = render_preview(s.session, 0, 12)
    s._show_report(r.report)
    s.prog.setValue(1000)
    s.prog_lbl.setText(f"Превью 0–12 с · {r.report['master'].get('lufs_after')} LUFS · рендер {r.report['render_time_s']} с")
    s.side.setCurrentIndex(0)
    win.tabs.setCurrentIndex(1)
    app.processEvents()
    s.stage.fit()
    app.processEvents()
    win.grab().save(str(OUT / "studio.png"))
    s.side.setCurrentIndex(1)
    app.processEvents()
    win.grab().save(str(OUT / "recording.png"))
    s.session.set_scene("arena")
    s._load_session_into_ui()
    s.side.setCurrentIndex(0)
    app.processEvents()
    s.stage.fit()
    app.processEvents()
    win.grab().save(str(OUT / "arena.png"))
    win.tabs.setCurrentIndex(2)
    app.processEvents()
    win.grab().save(str(OUT / "mastering.png"))
    print("\n".join(str(p) for p in sorted(OUT.glob("*.png"))))
    win.close()
    return 0


if __name__ == "__main__":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.exit(main())
