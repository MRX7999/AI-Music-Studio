"""Smoke-тест интерфейса без дисплея: окно строится, демо-трек уходит в студию, превью рендерится."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt5")


def test_main_window_flow(tmp_path, qapp_settings):
    from PyQt5.QtWidgets import QApplication

    from studio.generators import DemoGenerator, GenerationRequest
    from studio.render import render_preview
    from studio.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    win = MainWindow(qapp_settings)
    win.show()
    app.processEvents()
    assert win.tabs.count() == 4
    t = DemoGenerator().generate(GenerationRequest(title="GUI", duration=12, seed=2), tmp_path)[0]
    win.gen._add_result(t, top=True)
    win.open_in_studio(t)
    s = win.studio
    assert len(s.session.channels) == 4 and len(s.strips) == 4
    # перемещение значка на сцене обновляет модель
    cid = s.session.channels[0].id
    tok = s.stage.tokens[cid]
    tok.setPos(tok.pos().x() + 100, tok.pos().y())
    app.processEvents()
    assert abs(s.session.channels[0].x * 100 - tok.pos().x()) < 1
    # смена помещения и микрофона через виджеты
    s.scene_combo.setCurrentIndex(s.scene_combo.findData("concert_hall"))
    assert s.session.scene == "concert_hall"
    s.select_channel(cid)
    s.ch_mic.setCurrentIndex(s.ch_mic.findData("ribbon"))
    s._mic_changed(0)
    assert s.session.channels[0].mic == "ribbon"
    s.ch_dist.spin.setValue(120)          # как пользователь вводит число
    assert s.session.channels[0].mic_distance_cm == 120
    r = render_preview(s.session, 0, 4)
    s._show_report(r.report)
    path = s.save_session()
    assert path.exists()
    win.close()


@pytest.fixture
def qapp_settings(tmp_path):
    from PyQt5.QtCore import QSettings
    st = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    st.setValue("output_dir", str(tmp_path / "proj"))
    return st


def test_project_root_fallback(tmp_path, monkeypatch):
    """Нет доступа к выбранной папке (как ~/Music под TCC) → берётся запасная, без падения."""
    from studio.ui import paths
    paths._cache.clear()
    locked = tmp_path / "locked"
    good = tmp_path / "fallback"
    monkeypatch.setattr(paths, "DEFAULT_ROOT", tmp_path / "also_locked")
    monkeypatch.setattr(paths, "FALLBACKS", (good,))
    real = paths._usable
    monkeypatch.setattr(paths, "_usable", lambda p: False if "locked" in p.name else real(p))
    root, note = paths.resolve_root(locked)
    assert root == good and good.is_dir() and "locked" in note
    paths._cache.clear()
    root, note = paths.resolve_root(good)
    assert root == good and note == ""
