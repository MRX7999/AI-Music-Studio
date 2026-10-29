"""Разделение готовой песни на дорожки для виртуальной студии.

Методы:
  demucs — нейросетевое разделение (htdemucs_6s: vocals/drums/bass/guitar/piano/other),
           ставится отдельно: pip install -r requirements-ml.txt
  hpss   — встроенный быстрый метод без моделей: гармоника/перкуссия (median-filter HPSS)
           + центр/края стереобазы + НЧ < 160 Гц → 4 псевдо-стема
  none   — песня целиком одним каналом «Готовый микс»
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy.ndimage import median_filter
from scipy.signal import istft, sosfiltfilt, stft

from . import dsp
from .audio_io import read_audio, write_audio

METHODS = {
    "hpss": "Встроенный (быстро, без моделей)",
    "demucs": "Demucs htdemucs_6s (нейросеть, точнее)",
    "none": "Не разделять (один канал)",
}


def demucs_available() -> bool:
    return importlib.util.find_spec("demucs") is not None


def available_methods() -> dict:
    m = dict(METHODS)
    if not demucs_available():
        m["demucs"] += " — не установлен"
    return m


def separate(path: str | Path, out_dir: str | Path, method: str = "hpss", progress=None,
             cancel=None, demucs_model: str = "htdemucs_6s") -> dict:
    """→ {stem_name: Path}. Файлы пишутся в out_dir."""
    path = Path(path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if method == "none":
        dst = out_dir / f"mix{path.suffix.lower() if path.suffix.lower() in ('.wav', '.flac') else '.wav'}"
        if path.suffix.lower() in (".wav", ".flac"):
            shutil.copy2(path, dst)
        else:
            a, sr = read_audio(path)
            dst = write_audio(dst, a, sr, 24, "wav")
        return {"mix": dst}
    if method == "demucs":
        return _demucs(path, out_dir, demucs_model, progress, cancel)
    return _hpss(path, out_dir, progress, cancel)


def _demucs(path: Path, out_dir: Path, model: str, progress, cancel) -> dict:
    if not demucs_available():
        raise RuntimeError("Demucs не установлен: pip install -r requirements-ml.txt "
                           "или выберите встроенный метод")
    if progress:
        progress(0.05, f"Demucs {model}: разделение (может занять несколько минут)")
    cmd = [sys.executable, "-m", "demucs", "-n", model, "-o", str(out_dir), str(path)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    tail = []
    for line in proc.stdout:
        tail = (tail + [line.rstrip()])[-20:]
        if cancel and cancel():
            proc.terminate()
            raise RuntimeError("Разделение отменено")
        if progress and "%" in line:
            try:
                pct = float(line.split("%")[0].split()[-1])
                progress(0.05 + 0.9 * pct / 100.0, f"Demucs: {pct:.0f}%")
            except (ValueError, IndexError):
                pass
    if proc.wait() != 0:
        raise RuntimeError("Demucs завершился с ошибкой:\n" + "\n".join(tail))
    res_dir = out_dir / model / path.stem
    stems = {p.stem: p for p in sorted(res_dir.glob("*.wav"))}
    if not stems:
        raise RuntimeError(f"Demucs не создал стемы в {res_dir}")
    # пустые стемы (например, нет гитары) не нужны на пульте
    keep = {}
    for name, p in stems.items():
        a, _ = read_audio(p)
        if dsp.rms_db(a) > -55:
            keep[name] = p
    if progress:
        progress(1.0, f"Готово: {', '.join(keep)}")
    return keep or stems


def _hpss(path: Path, out_dir: Path, progress, cancel) -> dict:
    audio, sr = read_audio(path)
    audio = dsp.to_stereo(audio)
    if progress:
        progress(0.05, "Встроенное разделение: НЧ")
    # 1. Бас: всё ниже 160 Гц (линейная фаза через filtfilt → суммируется без фазовых проблем)
    sos_lp = dsp.biquad("lowpass", 160.0, sr, q=0.707)
    low = sosfiltfilt(sos_lp, sosfiltfilt(sos_lp, audio, axis=-1), axis=-1)
    rest = audio - low

    nper = 4096 if sr > 32000 else 2048
    hop = nper // 4
    harm = np.zeros_like(rest)
    perc = np.zeros_like(rest)
    for c in range(2):
        if cancel and cancel():
            raise RuntimeError("Разделение отменено")
        if progress:
            progress(0.15 + 0.35 * c, f"Встроенное разделение: HPSS, канал {c + 1}/2")
        _, _, Z = stft(rest[c], fs=sr, nperseg=nper, noverlap=nper - hop)
        mag = np.abs(Z)
        h = median_filter(mag, size=(1, 17))     # гладко по времени → гармоники
        p = median_filter(mag, size=(17, 1))     # гладко по частоте → удары
        mask_h = h ** 2 / (h ** 2 + p ** 2 + 1e-12)
        _, xh = istft(Z * mask_h, fs=sr, nperseg=nper, noverlap=nper - hop)
        _, xp = istft(Z * (1 - mask_h), fs=sr, nperseg=nper, noverlap=nper - hop)
        harm[c] = dsp.match_length(xh[np.newaxis, :], rest.shape[1])[0]
        perc[c] = dsp.match_length(xp[np.newaxis, :], rest.shape[1])[0]

    if progress:
        progress(0.85, "Встроенное разделение: центр / края")
    # 2. Гармоническая часть: центр (обычно вокал/лид) и края (гармония, пэды)
    mid = (harm[0] + harm[1]) / 2
    side_l, side_r = harm[0] - mid, harm[1] - mid
    center = np.vstack([mid, mid])
    sides = np.vstack([side_l, side_r])

    stems = {"bass": low, "drums": perc, "center": center, "sides": sides}
    out = {}
    for name, a in stems.items():
        out[name] = write_audio(out_dir / f"{name}.wav", a, sr, 32, "wav")
    if progress:
        progress(1.0, "Готово: bass, drums, center, sides")
    return out
