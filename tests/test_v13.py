"""1.3.0: the humanize step (the user's own humanize.py since 1.0.0) in the release pipeline."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from studio import humanize
from studio.publish import pipeline, release

SR = 48000


def piano(seconds=20.0, sr=SR):
    t = np.arange(int(sr * seconds)) / sr
    note = np.sin(2 * np.pi * 220 * t) + 0.4 * np.sin(2 * np.pi * 440 * t) + 0.2 * np.sin(2 * np.pi * 660 * t)
    env = 0.6 + 0.4 * np.sin(2 * np.pi * 0.25 * t)          # amplitude movement, so jitter has onsets
    x = (0.3 * note * env).astype(np.float32)
    return np.vstack([x, 0.8 * x]).T


@pytest.fixture
def made_release(tmp_path):
    src = tmp_path / "mix.wav"
    sf.write(src, piano(), SR, subtype="FLOAT")
    rel = release.create(tmp_path, src, "T", "A", "[Verse]\nhello\n\n[Chorus]\nworld", {"genre": "pop"})
    return tmp_path, rel


def test_presets_unchanged():
    assert humanize.PRESETS["ultra-low"]["pitch_cents"] == 0.0
    assert humanize.PRESETS["ultra-low"]["sat_mix"] == 0.03
    assert set(humanize.PRESETS) == {"ultra-low", "low", "medium", "high"}


def test_step_writes_humanized_master(made_release):
    root, rel = made_release
    rel = pipeline.run_step(root, rel, "humanize", {"preset": "ultra-low", "seed": 7}, {})
    h = rel.meta["humanize"]
    out = Path(h["output"])
    assert out.exists() and out.name == "master_humanized.wav" and rel.master == str(out)
    assert h["preset"] == "ultra-low" and h["seed"] == 7 and h["input"] != h["output"]
    assert "humanization: ultra-low" in rel.meta["ai"]["tools"]
    # audio: same length, still stereo, changed but not destroyed
    before, _ = sf.read(h["input"], always_2d=True)
    after, sr2 = sf.read(out, always_2d=True)
    assert sr2 == SR and after.shape == before.shape
    assert not np.allclose(after, before, atol=1e-4)
    assert np.max(np.abs(after)) <= 1.0 and np.max(np.abs(after)) > 0.2


def test_step_runs_before_detect_and_package_uses_it(made_release):
    root, rel = made_release
    rel = pipeline.run_step(root, rel, "humanize", {"preset": "low", "seed": 3}, {})
    rel = pipeline.run_step(root, rel, "detect", {"detectors": ["sightengine"]}, {})  # key absent → skipped
    rel = pipeline.run_step(root, rel, "package", {}, {})
    assert rel.meta["package"]["wav"].endswith(".wav")
    # the packaged master is the humanized one (the package resamples to 44.1 kHz)
    packaged, sp = sf.read(rel.meta["package"]["audio"], always_2d=True)
    humanized, sh = sf.read(rel.meta["humanize"]["output"], always_2d=True)
    assert sp == 44100 and sh == SR
    assert abs(len(packaged) / sp - len(humanized) / sh) < 0.1


def test_seed_reproducible_and_preset_bad_falls_back(made_release):
    root, rel = made_release
    a = pipeline.run_step(root, rel, "humanize", {"preset": "ultra-low", "seed": 11}, {})
    b = pipeline.run_step(root, rel, "humanize", {"preset": "ultra-low", "seed": 11}, {})
    c = pipeline.run_step(root, rel, "humanize", {"preset": "no-such-preset", "seed": 11}, {})
    assert Path(a.meta["humanize"]["output"]).read_bytes() == Path(b.meta["humanize"]["output"]).read_bytes()
    assert c.meta["humanize"]["preset"] == "ultra-low"


def test_restore_returns_previous_master(made_release):
    root, rel = made_release
    before = rel.master
    rel = pipeline.run_step(root, rel, "humanize", {"preset": "ultra-low", "seed": 1}, {})
    assert rel.master != before
    rel = pipeline.run_step(root, rel, "humanize", {"restore": True}, {})
    assert rel.master == before and rel.meta["humanize"]["restored"] is True


def test_skip_noise_and_librosa_hint(made_release):
    root, rel = made_release
    rel = pipeline.run_step(root, rel, "humanize", {"preset": "ultra-low", "seed": 5, "skip_noise": True}, {})
    assert rel.meta["humanize"]["skipped_noise"] is True
    assert pipeline.STEPS.index("humanize") == pipeline.STEPS.index("detect") - 1


def test_module_error_without_librosa(tmp_path, monkeypatch, made_release):
    root, rel = made_release
    wav = tmp_path / "x.wav"
    sf.write(wav, piano(2.0), SR, subtype="FLOAT")
    monkeypatch.setattr(humanize, "librosa", None)
    with pytest.raises(RuntimeError, match="librosa is required"):
        humanize.humanize(wav, tmp_path / "y.wav", preset="ultra-low")
