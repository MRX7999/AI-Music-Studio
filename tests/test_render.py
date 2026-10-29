import json

import numpy as np
import pytest
import soundfile as sf

from studio import stems as stems_mod
from studio.generators import DemoGenerator, GenerationRequest
from studio.render import channel_geometry, render_preview, render_session
from studio.scenes import SCENES
from studio.session import Session, session_from_stems


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo")
    t = DemoGenerator().generate(GenerationRequest(title="Тест", duration=16, bpm=120, key="E minor", seed=1), out)[0]
    return t


def test_demo_has_real_stems(demo):
    assert set(demo.stems) == {"drums", "bass", "keys", "lead"}
    for p in demo.stems.values():
        a, sr = sf.read(str(p))
        assert sr == 44100 and np.max(np.abs(a)) > 0.01


@pytest.mark.parametrize("scene", list(SCENES))
def test_render_every_scene(demo, scene, tmp_path):
    s = session_from_stems({k: str(v) for k, v in demo.stems.items()}, "T", scene)
    r = render_session(s, duration_s=6, out_path=tmp_path / "mix", sample_rate=44100)
    assert r.path.exists()
    assert np.isfinite(r.audio).all()
    assert abs(r.report["master"]["lufs_after"] + 14) < 1.5
    assert r.report["master"]["true_peak_db"] <= -0.5


def test_room_changes_sound(demo):
    st = {k: str(v) for k, v in demo.stems.items()}
    dry = render_preview(session_from_stems(st, "a", "dry"), 0, 6).audio
    hall = render_preview(session_from_stems(st, "a", "cathedral"), 0, 6).audio
    n = min(dry.shape[1], hall.shape[1])
    corr = np.corrcoef(dry[0, :n], hall[0, :n])[0, 1]
    assert corr < 0.95          # помещение заметно меняет сигнал


def test_position_drives_pan(demo):
    s = session_from_stems({k: str(v) for k, v in demo.stems.items()}, "a", "studio_a")
    ch = s.channels[0]
    lx, _ = s.listener()
    ch.x = lx - 3
    assert channel_geometry(s, ch)["pan"] < -0.3
    ch.x = lx + 3
    assert channel_geometry(s, ch)["pan"] > 0.3
    ch.pan = 0.0
    assert channel_geometry(s, ch)["pan"] == 0.0


def test_mute_solo(demo):
    s = session_from_stems({k: str(v) for k, v in demo.stems.items()}, "a", "dry")
    for c in s.channels:
        c.mute = True
    with pytest.raises(ValueError):
        render_preview(s, 0, 3)
    s.channels[1].mute = False
    s.channels[1].solo = True
    r = render_preview(s, 0, 3)
    assert len(r.report["channels"]) == 1


def test_session_roundtrip(demo, tmp_path):
    s = session_from_stems({k: str(v) for k, v in demo.stems.items()}, "Круг", "club", meta={"title": "Круг"})
    s.channels[0].mic = "ribbon"
    s.recording.tape = "tape15"
    p = s.save(tmp_path / "x.studio.json")
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["scene"] == "club" and d["channels"][0]["mic"] == "ribbon"
    s2 = Session.load(p)
    assert s2.recording.tape == "tape15" and len(s2.channels) == 4


def test_scene_switch_keeps_layout_inside_room(demo):
    s = session_from_stems({k: str(v) for k, v in demo.stems.items()}, "a", "booth")
    for sid in SCENES:
        s.set_scene(sid)
        sc = SCENES[sid]
        for c in s.channels:
            assert 0 < c.x < sc.width and 0 < c.y < sc.depth


def test_hpss_separation_sums_back(demo, tmp_path):
    st = stems_mod.separate(demo.path, tmp_path / "sep", "hpss")
    assert set(st) == {"bass", "drums", "center", "sides"}
    orig, sr = sf.read(str(demo.path), always_2d=True)
    total = sum(sf.read(str(p), always_2d=True)[0] for p in st.values())
    n = min(len(orig), len(total))
    err = np.sqrt(np.mean((orig[:n] - total[:n]) ** 2)) / (np.sqrt(np.mean(orig[:n] ** 2)) + 1e-9)
    assert err < 0.1


def test_export_formats(demo, tmp_path):
    import shutil
    s = session_from_stems({k: str(v) for k, v in demo.stems.items()}, "f", "studio_a")
    fmts = ["wav", "flac"] + (["alac", "mp3"] if shutil.which("ffmpeg") else [])
    for f in fmts:
        s.recording.output_format = f
        r = render_session(s, duration_s=3, out_path=tmp_path / f"m_{f}", sample_rate=44100)
        assert r.path.exists() and r.path.stat().st_size > 1000
