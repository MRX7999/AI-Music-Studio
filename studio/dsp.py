"""Базовый DSP на numpy/scipy — без librosa и нативных плагинов.

Соглашение по форме массивов: audio.shape == (channels, samples), float64.
"""
from __future__ import annotations

from math import gcd

import numpy as np
from scipy.signal import resample_poly, sosfilt


# ──────────────────────────────────────────────────────────────
#  Форма и уровни
# ──────────────────────────────────────────────────────────────

def as_2d(audio: np.ndarray) -> np.ndarray:
    """(n,) → (1, n); (n, ch) → (ch, n) если похоже на soundfile-формат."""
    a = np.asarray(audio, dtype=np.float64)
    if a.ndim == 1:
        return a[np.newaxis, :]
    if a.ndim == 2 and a.shape[0] > a.shape[1]:
        return a.T.copy()
    return a


def to_stereo(audio: np.ndarray) -> np.ndarray:
    a = as_2d(audio)
    if a.shape[0] == 1:
        return np.vstack([a, a])
    return a[:2]


def to_mono(audio: np.ndarray) -> np.ndarray:
    a = as_2d(audio)
    return a.mean(axis=0)


def db_to_gain(db: float) -> float:
    return float(10.0 ** (db / 20.0))


def gain_to_db(g: float) -> float:
    return float(20.0 * np.log10(max(abs(g), 1e-12)))


def peak_db(audio: np.ndarray) -> float:
    return gain_to_db(float(np.max(np.abs(audio))) if audio.size else 0.0)


def rms_db(audio: np.ndarray) -> float:
    if audio.size == 0:
        return -120.0
    return gain_to_db(float(np.sqrt(np.mean(np.square(audio)))))


def resample(audio: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out:
        return audio
    g = gcd(int(sr_in), int(sr_out))
    up, down = int(sr_out) // g, int(sr_in) // g
    return resample_poly(audio, up, down, axis=-1)


def match_length(audio: np.ndarray, n: int) -> np.ndarray:
    a = as_2d(audio)
    if a.shape[1] >= n:
        return a[:, :n]
    return np.pad(a, ((0, 0), (0, n - a.shape[1])))


# ──────────────────────────────────────────────────────────────
#  Биквады (RBJ Audio EQ Cookbook) → SOS
# ──────────────────────────────────────────────────────────────

def _norm(b, a) -> np.ndarray:
    b = np.asarray(b, dtype=np.float64) / a[0]
    a = np.asarray(a, dtype=np.float64) / a[0]
    return np.array([[b[0], b[1], b[2], 1.0, a[1], a[2]]])


def _w0(freq: float, sr: int) -> float:
    f = float(np.clip(freq, 5.0, sr * 0.49))
    return 2.0 * np.pi * f / sr


def biquad(kind: str, freq: float, sr: int, gain_db: float = 0.0, q: float = 0.707) -> np.ndarray:
    """kind: peak | lowshelf | highshelf | highpass | lowpass | bandpass."""
    w0 = _w0(freq, sr)
    cw, sw = np.cos(w0), np.sin(w0)
    q = max(float(q), 0.05)
    alpha = sw / (2.0 * q)
    A = 10.0 ** (gain_db / 40.0)
    if kind == "peak":
        b = [1 + alpha * A, -2 * cw, 1 - alpha * A]
        a = [1 + alpha / A, -2 * cw, 1 - alpha / A]
    elif kind == "lowshelf":
        sa = 2 * np.sqrt(A) * alpha
        b = [A * ((A + 1) - (A - 1) * cw + sa), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - sa)]
        a = [(A + 1) + (A - 1) * cw + sa, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - sa]
    elif kind == "highshelf":
        sa = 2 * np.sqrt(A) * alpha
        b = [A * ((A + 1) + (A - 1) * cw + sa), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - sa)]
        a = [(A + 1) - (A - 1) * cw + sa, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sa]
    elif kind == "highpass":
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "lowpass":
        b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "bandpass":
        b = [alpha, 0.0, -alpha]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    else:
        raise ValueError(f"неизвестный тип фильтра: {kind}")
    return _norm(b, np.asarray(a, dtype=np.float64))


def eq_chain(bands, sr: int) -> np.ndarray | None:
    """bands: iterable of (kind, freq, gain_db, q). Пропускает «пустые» полосы."""
    sos = []
    for kind, freq, gain, q in bands:
        if kind in ("peak", "lowshelf", "highshelf") and abs(gain) < 0.05:
            continue
        if kind in ("highpass", "lowpass") and (freq <= 0 or freq >= sr * 0.49):
            continue
        sos.append(biquad(kind, freq, sr, gain, q))
    if not sos:
        return None
    return np.vstack(sos)


def apply_sos(audio: np.ndarray, sos: np.ndarray | None) -> np.ndarray:
    if sos is None:
        return audio
    return sosfilt(sos, audio, axis=-1)


def apply_eq(audio: np.ndarray, sr: int, bands) -> np.ndarray:
    return apply_sos(audio, eq_chain(bands, sr))


def sos_response_db(sos: np.ndarray, freqs, sr: int) -> np.ndarray:
    """АЧХ каскада SOS на заданных частотах (для тестов и графиков)."""
    from scipy.signal import sosfreqz
    _, h = sosfreqz(sos, worN=np.asarray(freqs, dtype=np.float64), fs=sr)
    return 20 * np.log10(np.abs(h) + 1e-12)


# ──────────────────────────────────────────────────────────────
#  Динамика (блочная огибающая — быстро на длинных треках)
# ──────────────────────────────────────────────────────────────

def _smooth_env(level_db: np.ndarray, block_s: float, attack_ms: float, release_ms: float) -> np.ndarray:
    a_att = np.exp(-block_s / max(attack_ms / 1000.0, 1e-4))
    a_rel = np.exp(-block_s / max(release_ms / 1000.0, 1e-4))
    out = np.empty_like(level_db)
    prev = level_db[0] if level_db.size else 0.0
    for i, x in enumerate(level_db):
        c = a_att if x > prev else a_rel
        prev = x + c * (prev - x)
        out[i] = prev
    return out


def compressor(audio: np.ndarray, sr: int, threshold_db: float = -18.0, ratio: float = 3.0,
               attack_ms: float = 10.0, release_ms: float = 120.0, knee_db: float = 6.0,
               makeup_db: float | None = None, block_ms: float = 1.0) -> np.ndarray:
    """Feed-forward компрессор с мягким коленом, связанные каналы.

    makeup_db=None → автоматическая компенсация половины среднего снижения усиления.
    """
    a = as_2d(audio)
    n = a.shape[1]
    if n == 0 or ratio <= 1.0:
        return a
    bs = max(1, int(sr * block_ms / 1000.0))
    nb = int(np.ceil(n / bs))
    pad = nb * bs - n
    sq = np.pad(np.max(np.square(a), axis=0), (0, pad)).reshape(nb, bs)
    lvl = 10.0 * np.log10(np.mean(sq, axis=1) + 1e-12)  # RMS блока, dB
    env = _smooth_env(lvl, bs / sr, attack_ms, release_ms)

    over = env - threshold_db
    gr = np.zeros_like(env)
    k = max(knee_db, 1e-6)
    hard = over > k / 2
    soft = np.abs(over) <= k / 2
    gr[hard] = -over[hard] * (1 - 1 / ratio)
    gr[soft] = -((over[soft] + k / 2) ** 2) / (2 * k) * (1 - 1 / ratio)

    if makeup_db is None:
        makeup_db = -0.5 * float(np.mean(gr))
    gain_blocks = 10 ** ((gr + makeup_db) / 20.0)
    centers = (np.arange(nb) + 0.5) * bs
    gain = np.interp(np.arange(n), centers, gain_blocks)
    return a * gain[np.newaxis, :]


def gate(audio: np.ndarray, sr: int, threshold_db: float = -60.0, range_db: float = 40.0,
         release_ms: float = 80.0) -> np.ndarray:
    a = as_2d(audio)
    n = a.shape[1]
    if n == 0:
        return a
    bs = max(1, int(sr * 0.002))
    nb = int(np.ceil(n / bs))
    sq = np.pad(np.max(np.square(a), axis=0), (0, nb * bs - n)).reshape(nb, bs)
    lvl = 10.0 * np.log10(np.mean(sq, axis=1) + 1e-12)
    target = np.where(lvl > threshold_db, 0.0, -range_db)
    sm = _smooth_env(target, bs / sr, 1.0, release_ms)
    gain = np.interp(np.arange(n), (np.arange(nb) + 0.5) * bs, 10 ** (sm / 20.0))
    return a * gain


# ──────────────────────────────────────────────────────────────
#  Сатурация и аналоговые цепи
# ──────────────────────────────────────────────────────────────

PREAMPS = {
    "clean":       dict(name="Чистый (транзисторный)", even=0.00, odd=1.0, warmth_db=0.0, hf_db=0.0),
    "tube":        dict(name="Ламповый (в духе 1950-х)", even=0.35, odd=0.6, warmth_db=0.8, hf_db=-0.6),
    "transformer": dict(name="Трансформаторный (в духе Neve 1073)", even=0.18, odd=0.9, warmth_db=1.2, hf_db=0.5),
    "opto":        dict(name="Оптический (в духе LA-2A)", even=0.22, odd=0.7, warmth_db=0.4, hf_db=-0.3),
}


def saturate(audio: np.ndarray, drive_db: float = 6.0, even: float = 0.2, mix: float = 1.0) -> np.ndarray:
    """Мягкое ограничение tanh + чётные гармоники через асимметрию. drive 0 → прозрачно."""
    if drive_db <= 0.01 or mix <= 0.0:
        return audio
    g = db_to_gain(drive_db)
    x = audio * g
    bias = 0.25 * even
    y = np.tanh(x + bias) - np.tanh(bias)
    y = y / g * (1.0 + 0.1 * drive_db / 12.0)  # почти сохраняем уровень
    # убираем DC, возникший из-за асимметрии
    y = y - np.mean(y, axis=-1, keepdims=True)
    return audio * (1 - mix) + y * mix


def preamp(audio: np.ndarray, sr: int, kind: str = "clean", drive_db: float = 0.0) -> np.ndarray:
    p = PREAMPS.get(kind, PREAMPS["clean"])
    out = audio
    if drive_db > 0:
        out = saturate(out, drive_db=drive_db, even=p["even"])
    bands = [("lowshelf", 120.0, p["warmth_db"] * min(1.0, 0.3 + drive_db / 12), 0.7),
             ("highshelf", 9000.0, p["hf_db"], 0.7)]
    return apply_eq(out, sr, bands)


TAPES = {
    "off":      dict(name="Без ленты", sat=0.0, bump_db=0.0, bump_f=0, hf_cut=0, wow=0.0, flutter=0.0, hiss_db=-200),
    "tape15":   dict(name="Лента 15 ips (тёплая)", sat=4.0, bump_db=1.5, bump_f=70, hf_cut=17000, wow=0.0006, flutter=0.00025, hiss_db=-72),
    "tape30":   dict(name="Лента 30 ips (чистая)", sat=2.5, bump_db=0.8, bump_f=45, hf_cut=21000, wow=0.0003, flutter=0.00012, hiss_db=-78),
    "cassette": dict(name="Кассета (lo-fi)", sat=7.0, bump_db=2.5, bump_f=90, hf_cut=11000, wow=0.0025, flutter=0.0009, hiss_db=-58),
    "vinyl":    dict(name="Винил (тёплый, с треском)", sat=2.0, bump_db=1.0, bump_f=60, hf_cut=15000, wow=0.0009, flutter=0.0, hiss_db=-66),
}


def wow_flutter(audio: np.ndarray, sr: int, wow_depth: float, flutter_depth: float, seed: int = 0) -> np.ndarray:
    """Модуляция скорости ленты: wow ~0.5 Гц, flutter ~6–10 Гц. depth — доля скорости."""
    if wow_depth <= 0 and flutter_depth <= 0:
        return audio
    a = as_2d(audio)
    n = a.shape[1]
    rng = np.random.default_rng(seed)
    t = np.arange(n) / sr
    ph1, ph2, ph3 = rng.uniform(0, 2 * np.pi, 3)
    speed = (wow_depth * (np.sin(2 * np.pi * 0.55 * t + ph1) + 0.4 * np.sin(2 * np.pi * 0.23 * t + ph2))
             + flutter_depth * np.sin(2 * np.pi * 7.3 * t + ph3))
    offset = np.cumsum(speed)  # в сэмплах
    offset -= offset.mean()
    pos = np.clip(np.arange(n) + offset, 0, n - 1)
    idx = np.arange(n)
    return np.vstack([np.interp(pos, idx, ch) for ch in a])


def pink_noise(n: int, channels: int = 2, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    white = rng.standard_normal((channels, n))
    spec = np.fft.rfft(white, axis=-1)
    f = np.arange(spec.shape[-1], dtype=np.float64)
    f[0] = 1.0
    spec /= np.sqrt(f)
    out = np.fft.irfft(spec, n=n, axis=-1)
    out /= (np.std(out) + 1e-12)
    return out


def vinyl_crackle(n: int, sr: int, density: float = 6.0, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed + 99)
    out = np.zeros((2, n))
    count = int(density * n / sr)
    if count:
        pos = rng.integers(0, n, count)
        amp = rng.pareto(3.0, count) * 0.05
        out[0, pos] = amp * rng.choice([-1, 1], count)
        out[1, pos] = amp * rng.choice([-1, 1], count) * rng.uniform(0.3, 1.0, count)
        sos = biquad("highpass", 1500, sr, q=0.7)
        out = sosfilt(sos, out, axis=-1)
    return out


def tape(audio: np.ndarray, sr: int, kind: str = "off", seed: int = 0) -> np.ndarray:
    p = TAPES.get(kind, TAPES["off"])
    if kind == "off":
        return audio
    out = saturate(audio, drive_db=p["sat"], even=0.12)
    bands = [("lowshelf", p["bump_f"], p["bump_db"], 1.0), ("lowpass", p["hf_cut"], 0, 0.6)]
    out = apply_eq(out, sr, bands)
    out = wow_flutter(out, sr, p["wow"], p["flutter"], seed=seed)
    n = out.shape[1]
    hiss = pink_noise(n, out.shape[0], seed=seed + 7)
    hiss = apply_eq(hiss, sr, [("highpass", 2000, 0, 0.7)])
    out = out + hiss * db_to_gain(p["hiss_db"])
    if kind == "vinyl":
        out = out + vinyl_crackle(n, sr, seed=seed)[: out.shape[0]]
    return out


# ──────────────────────────────────────────────────────────────
#  Пространство
# ──────────────────────────────────────────────────────────────

def pan_gains(pan: float) -> tuple[float, float]:
    """Constant-power, pan ∈ [-1, 1]."""
    p = float(np.clip(pan, -1.0, 1.0))
    ang = (p + 1.0) * np.pi / 4.0
    return float(np.cos(ang)), float(np.sin(ang))


def delay(audio: np.ndarray, samples: int) -> np.ndarray:
    if samples <= 0:
        return audio
    a = as_2d(audio)
    return np.pad(a, ((0, 0), (samples, 0)))[:, : a.shape[1]]


def air_absorption(audio: np.ndarray, sr: int, distance_m: float) -> np.ndarray:
    """Затухание ВЧ в воздухе: ≈ −0.1 дБ/м на 10 кГц (20 °C, 50 % RH), плюс мягкий shelf."""
    d = max(0.0, float(distance_m))
    if d < 2.0:
        return audio
    g = -min(18.0, 0.1 * d)
    return apply_eq(audio, sr, [("highshelf", 7000.0, g, 0.6)])


def tpdf_dither(audio: np.ndarray, bits: int, seed: int = 0) -> np.ndarray:
    if bits >= 32:
        return audio
    rng = np.random.default_rng(seed + 3)
    lsb = 2.0 ** (1 - bits)
    return audio + (rng.uniform(-0.5, 0.5, audio.shape) + rng.uniform(-0.5, 0.5, audio.shape)) * lsb


def fade(audio: np.ndarray, sr: int, fade_in_s: float = 0.0, fade_out_s: float = 0.0) -> np.ndarray:
    a = as_2d(audio).copy()
    n = a.shape[1]
    fi = min(n, int(fade_in_s * sr))
    fo = min(n, int(fade_out_s * sr))
    if fi > 0:
        a[:, :fi] *= np.sin(np.linspace(0, np.pi / 2, fi)) ** 2
    if fo > 0:
        a[:, n - fo:] *= np.cos(np.linspace(0, np.pi / 2, fo)) ** 2
    return a
