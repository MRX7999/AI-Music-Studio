"""Громкость по ITU-R BS.1770-4 / EBU R128, true peak и прозрачный лимитер."""
from __future__ import annotations

import numpy as np
from scipy.ndimage import maximum_filter1d
from scipy.signal import lfilter, resample_poly

from .dsp import as_2d, db_to_gain


def _k_weighting(sr: int):
    """Коэффициенты K-фильтра для произвольной частоты (формулы как в pyloudnorm)."""
    # Stage 1: high shelf (~+4 дБ выше 1.5 кГц)
    G, Q, fc = 3.999843853973347, 0.7071752369554196, 1681.974450955533
    A = 10 ** (G / 40.0)
    w0 = 2 * np.pi * fc / sr
    alpha = np.sin(w0) / (2 * Q)
    b1 = np.array([A * ((A + 1) + (A - 1) * np.cos(w0) + 2 * np.sqrt(A) * alpha),
                   -2 * A * ((A - 1) + (A + 1) * np.cos(w0)),
                   A * ((A + 1) + (A - 1) * np.cos(w0) - 2 * np.sqrt(A) * alpha)])
    a1 = np.array([(A + 1) - (A - 1) * np.cos(w0) + 2 * np.sqrt(A) * alpha,
                   2 * ((A - 1) - (A + 1) * np.cos(w0)),
                   (A + 1) - (A - 1) * np.cos(w0) - 2 * np.sqrt(A) * alpha])
    # Stage 2: high-pass (RLB, ~38 Гц)
    Q2, fc2 = 0.5003270373238773, 38.13547087602444
    w0 = 2 * np.pi * fc2 / sr
    alpha = np.sin(w0) / (2 * Q2)
    b2 = np.array([(1 + np.cos(w0)) / 2, -(1 + np.cos(w0)), (1 + np.cos(w0)) / 2])
    a2 = np.array([1 + alpha, -2 * np.cos(w0), 1 - alpha])
    return (b1 / a1[0], a1 / a1[0]), (b2 / a2[0], a2 / a2[0])


def integrated_lufs(audio: np.ndarray, sr: int) -> float:
    a = as_2d(audio)
    if a.shape[1] < int(0.4 * sr):
        a = np.pad(a, ((0, 0), (0, int(0.4 * sr) - a.shape[1])))
    (b1, a1), (b2, a2) = _k_weighting(sr)
    y = lfilter(b2, a2, lfilter(b1, a1, a, axis=-1), axis=-1)
    block = int(0.4 * sr)
    hop = int(0.1 * sr)
    n_blocks = 1 + (y.shape[1] - block) // hop
    if n_blocks <= 0:
        return -70.0
    sq = np.square(y)
    cs = np.concatenate([np.zeros((sq.shape[0], 1)), np.cumsum(sq, axis=1)], axis=1)
    starts = np.arange(n_blocks) * hop
    z = (cs[:, starts + block] - cs[:, starts]) / block  # (ch, blocks)
    # Весовые коэффициенты каналов: L/R/C = 1.0 (5.1 не поддерживаем)
    zsum = np.sum(z, axis=0)
    lk = -0.691 + 10 * np.log10(zsum + 1e-12)
    abs_gate = lk > -70.0
    if not np.any(abs_gate):
        return -70.0
    rel_thr = -0.691 + 10 * np.log10(np.mean(zsum[abs_gate]) + 1e-12) - 10.0
    gated = abs_gate & (lk > rel_thr)
    if not np.any(gated):
        return -70.0
    return float(-0.691 + 10 * np.log10(np.mean(zsum[gated]) + 1e-12))


def true_peak_db(audio: np.ndarray, oversample: int = 4) -> float:
    a = as_2d(audio)
    if a.size == 0:
        return -120.0
    up = resample_poly(a, oversample, 1, axis=-1)
    return float(20 * np.log10(np.max(np.abs(up)) + 1e-12))


def limiter(audio: np.ndarray, sr: int, ceiling_db: float = -1.0, lookahead_ms: float = 5.0,
            release_ms: float = 80.0) -> np.ndarray:
    """Look-ahead brickwall-лимитер со сглаживанием усиления (без щелчков)."""
    a = as_2d(audio)
    n = a.shape[1]
    if n == 0:
        return a
    ceil = db_to_gain(ceiling_db)
    # детектор по true peak: 4x оверсэмплинг, максимум внутри каждого исходного отсчёта
    os_ = 4
    up = np.abs(resample_poly(a, os_, 1, axis=-1))[:, : n * os_]
    if up.shape[1] < n * os_:
        up = np.pad(up, ((0, 0), (0, n * os_ - up.shape[1])))
    peak = np.maximum(np.max(np.abs(a), axis=0), up.max(axis=0).reshape(n, os_).max(axis=1))
    la = max(1, int(sr * lookahead_ms / 1000.0))
    # пик на окне look-ahead, центрованный вперёд
    win_peak = maximum_filter1d(peak, size=2 * la + 1, mode="nearest")
    need = np.minimum(1.0, ceil / np.maximum(win_peak, 1e-12))
    # плавное восстановление: блочная однополюсная фильтрация «вверх», мгновенно «вниз»
    bs = max(1, int(sr * 0.0005))
    nb = int(np.ceil(n / bs))
    nb_pad = np.pad(need, (0, nb * bs - n), constant_values=1.0).reshape(nb, bs).min(axis=1)
    coef = np.exp(-(bs / sr) / (release_ms / 1000.0))
    g = np.empty(nb)
    prev = 1.0
    for i, x in enumerate(nb_pad):
        prev = x if x < prev else x + coef * (prev - x)
        g[i] = prev
    gain = np.minimum(np.interp(np.arange(n), (np.arange(nb) + 0.5) * bs, g), need)
    out = a * gain[np.newaxis, :]
    # страховочный клип на остатки интерполяции
    return np.clip(out, -ceil, ceil)


def normalize_loudness(audio: np.ndarray, sr: int, target_lufs: float = -14.0,
                       ceiling_db: float = -1.0, use_limiter: bool = True) -> tuple[np.ndarray, dict]:
    """Приводит к целевой громкости, затем лимитирует до ceiling. Возвращает (audio, отчёт)."""
    a = as_2d(audio)
    before = integrated_lufs(a, sr)
    gain_db = float(np.clip(target_lufs - before, -30.0, 30.0)) if before > -70 else 0.0
    out = a * db_to_gain(gain_db)
    if use_limiter:
        out = limiter(out, sr, ceiling_db=ceiling_db - 0.3)
    after = integrated_lufs(out, sr)
    # лимитер «съедает» громкость на плотном материале — догоняем цель (до 2 доп. проходов)
    for _ in range(2):
        if not use_limiter or after < -70 or abs(target_lufs - after) < 0.3:
            break
        extra = float(np.clip(target_lufs - after, -6.0, 6.0))
        gain_db += extra
        out = limiter(out * db_to_gain(extra), sr, ceiling_db=ceiling_db - 0.3)
        after = integrated_lufs(out, sr)
    return out, {
        "lufs_before": round(before, 2),
        "lufs_after": round(after, 2),
        "gain_db": round(gain_db, 2),
        "true_peak_db": round(true_peak_db(out), 2),
    }
