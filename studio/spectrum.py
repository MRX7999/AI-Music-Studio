"""Spectrum analysis: long-term spectrum, bandwidth (cutoff) detection, spectrogram images.

Pure numpy/scipy, no plotting libraries: images are written with a minimal PNG encoder so the
engine keeps its four dependencies.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np
from scipy.signal import stft, welch

from . import dsp


def long_term_spectrum(audio: np.ndarray, sr: int, nperseg: int = 8192, max_seconds: float = 240.0):
    """→ (freqs Hz, level dB) averaged over the track (mono sum, Welch)."""
    mono = dsp.to_stereo(audio).mean(axis=0)
    mono = mono[: int(max_seconds * sr)]
    if mono.size < nperseg:
        mono = np.pad(mono, (0, nperseg - mono.size))
    f, p = welch(mono, fs=sr, nperseg=nperseg, noverlap=nperseg // 2, window="hann", scaling="spectrum")
    return f, 10 * np.log10(np.maximum(p, 1e-20))


def detect_cutoff(audio: np.ndarray, sr: int, drop_db: float = 30.0) -> dict:
    """Effective bandwidth of a recording.

    The level of the musical band (500 Hz–4 kHz, 90th percentile) is the reference. The cutoff is
    the highest frequency whose smoothed level is still within `drop_db` of a line interpolated
    between that reference and the usual natural roll-off (-6 dB/octave of real music), and
    above which the spectrum stays low. A brickwall at 16 kHz (MP3 128k, many AI vocoders) and a
    natural 20 kHz top end are separated reliably; noise above the wall is tolerated.
    """
    f, db = long_term_spectrum(audio, sr)
    nyq = sr / 2
    # smoothing over ~1/12 octave equivalent at HF (≈ 30 bins at 8192 points)
    k = 31
    pad = np.pad(db, (k // 2, k // 2), mode="edge")
    smooth = np.convolve(pad, np.ones(k) / k, mode="valid")
    band = (f >= 500) & (f <= 4000)
    if not band.any():
        return {"cutoff_hz": nyq, "nyquist_hz": nyq, "ratio": 1.0, "reference_db": float(db.max())}
    ref = float(np.percentile(smooth[band], 90))
    octaves = np.log2(np.maximum(f, 1.0) / 4000.0)
    expected = ref - np.clip(octaves, 0, None) * 6.0
    alive = smooth > (expected - drop_db)
    alive[f < 4000] = True
    # the last "alive" bin after which at least 85 % of the remaining bins are dead
    idx = np.nonzero(alive)[0]
    cutoff_bin = len(f) - 1
    for i in idx[::-1]:
        tail = alive[i + 1:]
        if tail.size == 0 or tail.mean() < 0.15:
            cutoff_bin = i
            break
    cutoff = float(f[cutoff_bin])
    return {"cutoff_hz": round(cutoff, 1), "nyquist_hz": nyq, "ratio": round(cutoff / nyq, 4),
            "reference_db": round(ref, 2)}


def needs_superres(cutoff_hz: float, export_sr: int, margin: float = 0.88) -> bool:
    """SR is useful when the real bandwidth is clearly narrower than the export format offers
    (capped at 20 kHz: nothing above that is audible, so 96 kHz export does not force SR)."""
    target = min(export_sr / 2.0, 20000.0)
    return cutoff_hz < target * margin


# ---------------------------------------------------------------------------- images

_STOPS = np.array([  # "magma"-like: black → purple → orange → pale yellow
    [0.00, 0, 0, 4], [0.15, 28, 16, 68], [0.35, 101, 26, 128], [0.55, 183, 55, 121],
    [0.72, 241, 96, 93], [0.88, 254, 175, 120], [1.00, 252, 253, 191]], dtype=np.float64)


def colormap(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0, 1)
    out = np.empty(x.shape + (3,), dtype=np.uint8)
    for c in range(3):
        out[..., c] = np.interp(x, _STOPS[:, 0], _STOPS[:, c + 1]).astype(np.uint8)
    return out


def write_png(path: str | Path, rgb: np.ndarray) -> Path:
    """Minimal PNG encoder for an (H, W, 3) uint8 array."""
    path = Path(path)
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) \
        + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return path


def spectrogram_image(audio: np.ndarray, sr: int, width: int = 1200, height: int = 360,
                      max_hz: float | None = None, floor_db: float = -100.0, log_freq: bool = False,
                      cutoff_hz: float | None = None) -> np.ndarray:
    """→ RGB uint8 (height, width, 3). Linear frequency axis by default: brickwall cut-offs are
    easiest to see that way. A dashed line marks `cutoff_hz` when given."""
    mono = dsp.to_stereo(audio).mean(axis=0).astype(np.float64)
    nper = 4096 if sr > 32000 else 2048
    hop = max(nper // 4, int(np.ceil(mono.size / max(width, 1))))
    nover = max(0, nper - hop) if hop < nper else 0
    if mono.size < nper:
        mono = np.pad(mono, (0, nper - mono.size))
    f, _, Z = stft(mono, fs=sr, nperseg=nper, noverlap=nover, boundary=None, padded=True)
    S = 20 * np.log10(np.abs(Z) + 1e-12)
    S -= S.max()
    top = max_hz or sr / 2
    rows = np.geomspace(30, top, height) if log_freq else np.linspace(0, top, height)
    fi = np.clip(np.searchsorted(f, rows), 0, len(f) - 1)
    img = S[fi][::-1]                                  # high frequencies on top
    cols = np.linspace(0, img.shape[1] - 1, width).astype(int)
    img = img[:, cols]
    rgb = colormap((img - floor_db) / -floor_db)
    if cutoff_hz and cutoff_hz < top:
        y = int(round((1 - cutoff_hz / top) * (height - 1))) if not log_freq else \
            int(round((1 - np.log(cutoff_hz / 30) / np.log(top / 30)) * (height - 1)))
        if 0 <= y < height:
            dash = (np.arange(width) // 8) % 2 == 0
            rgb[y, dash] = (90, 200, 255)
    return rgb


def spectrogram_png(src: str | Path, dst: str | Path, **kw) -> dict:
    from .audio_io import read_audio
    a, sr = read_audio(src)
    cut = detect_cutoff(a, sr)
    rgb = spectrogram_image(a, sr, cutoff_hz=cut["cutoff_hz"], **kw)
    write_png(dst, rgb)
    return {"path": str(dst), "sr": sr, **cut}
