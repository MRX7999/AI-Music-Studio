import numpy as np
import pytest

from studio import dsp
from studio.loudness import integrated_lufs, normalize_loudness, true_peak_db
from studio.mics import MICS, color, polar_gain, proximity_boost_db

SR = 48000


def sine(f, db=-20.0, sec=3.0, ch=2):
    t = np.arange(int(SR * sec)) / SR
    x = np.sin(2 * np.pi * f * t) * 10 ** (db / 20)
    return np.tile(x, (ch, 1)) if ch > 1 else x[np.newaxis, :]


@pytest.mark.parametrize("kind,freq,probe,expect", [
    ("highpass", 200, 50, -24), ("lowpass", 1000, 4000, -24), ("peak", 1000, 1000, 6),
    ("lowshelf", 100, 30, 6), ("highshelf", 8000, 16000, 6),
])
def test_biquad_response(kind, freq, probe, expect):
    sos = dsp.biquad(kind, freq, SR, gain_db=6.0)
    r = dsp.sos_response_db(sos, [probe], SR)[0]
    if expect < 0:
        assert r < expect + 3
    else:
        assert abs(r - expect) < 1.0


def test_lufs_reference_sine():
    # 1 кГц синус −20 dBFS в обоих каналах: K-weighting почти 0 дБ на 1 кГц, стерео даёт +3 дБ → ≈ −20 LUFS·
    mono_ref = integrated_lufs(sine(1000, -20, ch=1), SR)
    stereo = integrated_lufs(sine(1000, -20, ch=2), SR)
    assert abs(stereo - mono_ref - 3.01) < 0.2
    assert abs(stereo - (-20.0 + 3.01 - 3.01 - 0.0)) < 3.5


def test_normalize_hits_target_and_ceiling():
    rng = np.random.default_rng(0)
    x = rng.standard_normal((2, SR * 5)) * 0.1
    y, rep = normalize_loudness(x, SR, -14.0, -1.0, True)
    assert abs(rep["lufs_after"] + 14.0) < 0.8
    assert true_peak_db(y) <= -0.7


def test_compressor_reduces_peaks():
    x = sine(200, -3)
    y = dsp.compressor(x, SR, threshold_db=-20, ratio=6, makeup_db=0)
    assert dsp.rms_db(y) < dsp.rms_db(x) - 6


def test_mics_polar_and_proximity():
    assert polar_gain("cardioid", 0) == pytest.approx(1.0)
    assert polar_gain("cardioid", 180) == pytest.approx(0.0316, rel=0.05)
    assert polar_gain("figure8", 90) == pytest.approx(0.0316, rel=0.05)
    m = MICS["dyn_vocal"]
    assert proximity_boost_db(m, 0.02) > proximity_boost_db(m, 0.3) > 0
    assert proximity_boost_db(MICS["omni_measure"], 0.02) == 0


def test_mic_color_keeps_shape_and_level():
    x = sine(1000, -20)
    for mid, m in MICS.items():
        y, info = color(x, SR, m, 0.3, 0)
        assert y.shape == x.shape
        assert abs(dsp.rms_db(y) - dsp.rms_db(x)) < 12, mid


def test_tape_and_preamps_finite():
    x = sine(440, -10, sec=1)
    for k in dsp.PREAMPS:
        assert np.isfinite(dsp.preamp(x, SR, k, 6)).all()
    for k in dsp.TAPES:
        y = dsp.tape(x, SR, k)
        assert np.isfinite(y).all() and y.shape == x.shape
