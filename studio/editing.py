"""Timeline edits of a finished song: splice a regenerated region back into the original.

ACE-Step repaint returns the whole song re-decoded by its VAE, so even the untouched parts change
slightly (and a Suno/GPTunneL MP3 would be replaced by a 48 kHz re-synthesis). `splice` keeps the
original bit-exact outside the region and crossfades the new material in with equal-power fades.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from . import dsp
from .audio_io import read_audio, write_audio


def align_offset(ref: np.ndarray, new: np.ndarray, sr: int, start: float, max_shift_ms: float = 60.0) -> int:
    """Sample offset of `new` against `ref` measured just before the region (cross-correlation)."""
    win = int(sr * 2.0)
    a0 = max(0, int(start * sr) - win - int(sr * 0.25))
    a1 = a0 + win
    if a1 > ref.shape[1] or a1 > new.shape[1] or a0 >= a1:
        return 0
    x = ref[:, a0:a1].mean(axis=0)
    y = new[:, a0:a1].mean(axis=0)
    m = int(sr * max_shift_ms / 1000)
    n = 1 << int(np.ceil(np.log2(2 * x.size)))
    c = np.fft.irfft(np.fft.rfft(y, n) * np.conj(np.fft.rfft(x, n)), n)
    c = np.concatenate([c[-m:], c[: m + 1]])
    return int(np.argmax(c) - m)


def splice(original: str | Path, edited: str | Path, out: str | Path, start: float, end: float,
           xfade: float = 0.35, align: bool = True) -> dict:
    """original outside [start, end], edited inside, equal-power crossfades of `xfade` seconds."""
    a, sr = read_audio(original)
    b, sr_b = read_audio(edited)
    a, b = dsp.to_stereo(a), dsp.to_stereo(b)
    if sr_b != sr:
        b = dsp.resample(b, sr_b, sr)
    n = a.shape[1]
    end = n / sr if end is None or end < 0 else min(end, n / sr)
    start = max(0.0, min(start, end))
    shift = align_offset(a, b, sr, start) if align else 0
    if shift > 0:
        b = b[:, shift:]
    elif shift < 0:
        b = np.pad(b, ((0, 0), (-shift, 0)))
    b = dsp.match_length(b, n)
    i0, i1 = int(start * sr), int(end * sr)
    f = max(1, int(xfade * sr))
    t = np.zeros(n)
    t[i0:i1] = 1.0
    # equal-power ramps centred on the region borders
    r0, r1 = max(0, i0 - f // 2), min(n, i0 + f // 2)
    if r1 > r0:
        t[r0:r1] = np.sin(np.linspace(0, np.pi / 2, r1 - r0)) ** 2
    q0, q1 = max(0, i1 - f // 2), min(n, i1 + f // 2)
    if q1 > q0 and i1 < n:
        t[q0:q1] = np.cos(np.linspace(0, np.pi / 2, q1 - q0)) ** 2
    g_new = np.sqrt(t)
    g_old = np.sqrt(1.0 - t)
    out_audio = a * g_old + b * g_new
    path = write_audio(out, out_audio, sr, 24, "wav")
    return {"path": str(path), "start": start, "end": end, "shift_samples": shift, "sr": sr}
