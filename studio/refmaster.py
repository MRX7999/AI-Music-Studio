"""Reference mastering: Matchering 2.0 (optional plugin, GPL-3.0, separate process) or built in.

The engine (MIT) only starts `ml_scripts/matchering_run.py` with the interpreter of a dedicated
venv; Matchering is never imported or shipped here.

The built-in matcher works without any plugin: it compares the long-term spectra of the mix and
the reference (Welch, 1/3-octave smoothing, level-neutral between 100 Hz and 8 kHz), applies the
difference as a linear-phase FIR EQ clamped to ±max_db and scaled by `strength`, then matches the
integrated loudness of the reference (ITU-R BS.1770) with the true-peak limiter at −1 dBTP.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from . import dsp, tools
from .audio_io import read_audio, write_audio
from .loudness import integrated_lufs, normalize_loudness, true_peak_db


def available() -> bool:
    return bool(tools.find_executable("matchering"))


def _smooth_octave(f: np.ndarray, db: np.ndarray, frac: float = 3.0) -> np.ndarray:
    """1/frac-octave moving average of a dB curve on a linear frequency grid."""
    out = np.zeros_like(db)
    k = 2 ** (1 / (2 * frac))
    c = np.concatenate([[0.0], np.cumsum(db)])
    for i, fi in enumerate(f):
        lo, hi = np.searchsorted(f, fi / k), np.searchsorted(f, fi * k, side="right")
        hi = max(hi, lo + 1)
        out[i] = (c[hi] - c[lo]) / (hi - lo)
    return out


def eq_curve(target: np.ndarray, reference: np.ndarray, sr: int, max_db: float = 6.0,
             strength: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """(freqs, gain_db) that moves the tonal balance of `target` toward `reference`."""
    from scipy.signal import welch
    n = 8192
    f, pt = welch(dsp.to_mono(target), sr, nperseg=n)
    _, pr = welch(dsp.to_mono(reference), sr, nperseg=n)
    floor = 1e-14
    dt, dr = 10 * np.log10(pt + floor), 10 * np.log10(pr + floor)
    diff = _smooth_octave(f, dr) - _smooth_octave(f, dt)
    mid = (f >= 100) & (f <= 8000)
    diff -= float(np.mean(diff[mid])) if mid.any() else 0.0            # tonal balance only, not level
    # no boosting where either side has no content (cutoff of a 32 kHz/MP3 mix, rumble below 20 Hz)
    silent = (dt < dt.max() - 80) | (dr < dr.max() - 80) | (f < 20)
    diff[silent] = 0.0
    g = np.clip(diff, -max_db, max_db) * float(np.clip(strength, 0.0, 1.0))
    return f, g


def builtin_match(target: str | Path, reference: str | Path, output: str | Path, bits: int = 24,
                  use_limiter: bool = True, strength: float = 1.0, max_db: float = 6.0,
                  progress=None, cancel=None) -> dict:
    from scipy.signal import fftconvolve, firwin2
    a, sr = read_audio(target)
    r, rsr = read_audio(reference)
    if rsr != sr:
        r = dsp.resample(r, rsr, sr)
    if progress:
        progress(0.15, "Reference match: comparing spectra")
    f, g = eq_curve(a, r, sr, max_db=max_db, strength=strength)
    if cancel and cancel():
        raise RuntimeError("Cancelled")
    taps = 4097
    nyq = sr / 2
    grid = np.concatenate([[0.0], f[1:-1] / nyq, [1.0]])
    gains = 10 ** (np.concatenate([[g[1]], g[1:-1], [g[-2]]]) / 20)
    fir = firwin2(taps, grid, gains)
    if progress:
        progress(0.45, "Reference match: EQ")
    y = np.stack([fftconvolve(ch, fir, mode="same") for ch in dsp.as_2d(a)])
    if cancel and cancel():
        raise RuntimeError("Cancelled")
    ref_lufs = integrated_lufs(r, sr)
    before = integrated_lufs(a, sr)
    if progress:
        progress(0.75, "Reference match: loudness")
    target_lufs = ref_lufs if ref_lufs > -70 else -14.0
    y, rep = normalize_loudness(y, sr, target_lufs=target_lufs, ceiling_db=-1.0, use_limiter=use_limiter)
    out = write_audio(Path(output).with_suffix(".wav"), y, sr, bit_depth=bits)
    centers = [31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
    eq = [[c, round(float(np.interp(c, f, g)), 2)] for c in centers if c < nyq]
    if progress:
        progress(1.0, "Reference master ready")
    return {"output": str(out), "backend": "builtin", "eq_db": eq,
            "lufs_before": round(before, 2), "lufs_after": round(integrated_lufs(y, sr), 2),
            "reference_lufs": round(ref_lufs, 2), "true_peak_db": round(true_peak_db(y), 2),
            "log": [f"EQ toward reference, ±{max_db:g} dB, strength {strength:g}",
                    f"loudness {before:.1f} → {target_lufs:.1f} LUFS"]}


def master(target: str | Path, reference: str | Path, output: str | Path, bits: int = 24,
           use_limiter: bool = True, progress=None, cancel=None, backend: str | None = None,
           strength: float = 1.0, max_db: float = 6.0) -> dict:
    target, reference, output = Path(target), Path(reference), Path(output)
    for p in (target, reference):
        if not p.exists():
            raise FileNotFoundError(p)
    output.parent.mkdir(parents=True, exist_ok=True)
    backend = backend or tools.resolve_backend("refmaster")
    if backend == "off":
        raise RuntimeError("Reference mastering is off in Settings → AI Models")
    if backend != "matchering":
        rep = builtin_match(target, reference, output, bits, use_limiter, strength, max_db, progress, cancel)
        if backend.startswith("missing:"):
            rep["note"] = "Matchering is not installed, the built-in matcher was used"
        return rep
    argv = tools.build_argv("matchering", {"input": str(target), "reference": str(reference),
                                           "output": str(output.with_suffix(".wav"))})
    argv += ["--bits", str(bits)] + ([] if use_limiter else ["--no-limiter"])
    if progress:
        progress(0.05, "Matchering: analysing the reference")
    log = tools.run(argv, progress=progress, cancel=cancel, lo=0.05, hi=0.95, label="Matchering", timeout=1800)
    out = output.with_suffix(".wav")
    if not out.exists():
        raise RuntimeError("Matchering wrote no file:\n" + log[-800:])
    if progress:
        progress(1.0, "Reference master ready")
    return {"output": str(out), "backend": "matchering", "log": log.splitlines()[-12:]}
