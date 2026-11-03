"""Audio super-resolution to the export format: restore the top octave that AI vocoders and
lossy sources cut off (typically a brickwall near 16 kHz).

Backends (Settings → AI Models):
  flashsr — FlashSR, one diffusion step, MLX port in speech-swift (`speech upsample`),
            48 kHz mono in/out, 5.12 s windows. Default on Apple Silicon.
  audiosr — AudioSR 0.0.7 (PyTorch, MPS), soft settings: 12 DDIM steps, guidance 2.0.
  builtin — no model: a harmonic exciter regenerates the missing octave from the octave below the
            cutoff (rectifier + soft clipper → high-pass at the cutoff), level-matched to the
            spectral density just below the cutoff with a natural −6 dB/oct tilt. Used when no
            model is installed.

Signal path (all modes keep the original below the cutoff — the model only adds the missing band):
  1. detect the real bandwidth; skip when it already fills the export format (unless forced);
  2. resample to 48 kHz; split Mid/Side (or keep L/R);
  3. run the model on Mid (soft, default) or on L and R separately;
     FlashSR windows are processed twice with a half-window offset and blended so that window
     seams never coincide;
  4. hybrid merge: zero-phase crossover at the detected cutoff — low band from the original,
     high band from the model, optional high-band trim;
  5. rebuild stereo, resample to the export rate, report the new bandwidth.
"""
from __future__ import annotations

import shutil
import tempfile
from math import gcd
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

from . import dsp, spectrum, tools
from .audio_io import read_audio, write_audio

MODEL_SR = 48000
FLASHSR_WINDOW = 245760          # 5.12 s at 48 kHz

MODES = {"mid": "Mid only, Side from original (soft)", "lr": "Left and right separately"}


def _resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out:
        return x
    g = gcd(sr_in, sr_out)
    return resample_poly(x, sr_out // g, sr_in // g, axis=-1)


def analyze(path: str | Path, export_sr: int = 48000) -> dict:
    a, sr = read_audio(path)
    cut = spectrum.detect_cutoff(a, sr)
    return {**cut, "sr": sr, "export_sr": export_sr,
            "needs_superres": spectrum.needs_superres(cut["cutoff_hz"], export_sr),
            "backend": tools.resolve_backend("superres")}


def crossover(low_src: np.ndarray, high_src: np.ndarray, sr: int, fc: float, width_oct: float = 0.15,
              high_gain_db: float = 0.0) -> np.ndarray:
    """Zero-phase complementary crossover (raised cosine in log-frequency): H_low + H_high = 1,
    so identical inputs reconstruct exactly."""
    n = low_src.shape[-1]
    nfft = 1 << int(np.ceil(np.log2(max(n, 2))))
    f = np.fft.rfftfreq(nfft, 1 / sr)
    lo_edge, hi_edge = fc * 2 ** (-width_oct / 2), fc * 2 ** (width_oct / 2)
    t = np.clip((np.log2(np.maximum(f, 1e-9)) - np.log2(lo_edge)) / (np.log2(hi_edge) - np.log2(lo_edge)), 0, 1)
    h_high = 0.5 - 0.5 * np.cos(np.pi * t)
    h_low = 1.0 - h_high
    g = dsp.db_to_gain(high_gain_db)
    L = np.fft.rfft(low_src, nfft, axis=-1) * h_low
    H = np.fft.rfft(high_src[..., :n], nfft, axis=-1) * (h_high * g)
    return np.fft.irfft(L + H, nfft, axis=-1)[..., :n]


def _window_weights(n: int, win: int, offset: int) -> np.ndarray:
    """Triangle weight that is 0 at the window boundaries of a pass starting at `offset`."""
    pos = (np.arange(n) + offset) % win
    d = np.minimum(pos, win - pos).astype(np.float64)
    return d / (win / 2)


def _run_model(backend: str, mono48: np.ndarray, work: Path, tag: str, opts: dict, progress, cancel,
               lo: float, hi: float) -> np.ndarray:
    src = work / f"{tag}_in.wav"
    dst = work / f"{tag}_out.wav"
    write_audio(src, mono48[np.newaxis, :], MODEL_SR, 32, "wav")
    values = {"input": str(src), "output": str(dst), "outdir": str(work), "steps": opts.get("steps", 12),
              "guidance": opts.get("guidance", 2.0), "device": opts.get("device", "auto"),
              "variant": opts.get("variant", "")}
    argv = tools.build_argv(backend, values)
    tools.run(argv, progress=progress, cancel=cancel, lo=lo, hi=hi, label=tools.TOOLS[backend].label,
              timeout=opts.get("timeout", 4 * 3600))
    if not dst.exists():
        cands = sorted(work.rglob("*.wav"), key=lambda p: p.stat().st_mtime)
        cands = [c for c in cands if c != src and not c.name.endswith("_in.wav")]
        if not cands:
            raise RuntimeError(f"{backend}: no output file")
        dst = cands[-1]
    y, sr = read_audio(dst)
    y = _resample(y.mean(axis=0), sr, MODEL_SR)
    return dsp.match_length(y[np.newaxis, :], mono48.size)[0]


def builtin_extend(x: np.ndarray, cutoff_hz: float, sr: int = MODEL_SR, trim_db: float = -4.0) -> np.ndarray:
    """Model-free bandwidth extension of a mono signal: x + level-matched harmonics above the cutoff."""
    from scipy.signal import butter, sosfiltfilt, welch
    nyq = sr / 2
    fc = min(float(cutoff_hz), nyq * 0.9)
    if fc < 2000 or x.size < 4096:
        return x
    lo = max(fc / 2, 1000.0)
    band = sosfiltfilt(butter(4, [lo / nyq, fc * 0.98 / nyq], "bandpass", output="sos"), x)
    gen = np.abs(band) + 0.5 * np.tanh(3.0 * band)          # even + odd harmonics of the top octave
    gen = sosfiltfilt(butter(8, fc / nyq, "highpass", output="sos"), gen)
    gen = sosfiltfilt(butter(1, min(1.5 * fc / nyq, 0.95), "lowpass", output="sos"), gen)   # −6 dB/oct tilt
    f, px = welch(x, sr, nperseg=4096)
    _, pg = welch(gen, sr, nperseg=4096)
    ref_band = (f >= 0.8 * fc) & (f <= 0.95 * fc)
    gen_band = (f >= 1.05 * fc) & (f <= min(1.4 * fc, nyq * 0.95))
    if not ref_band.any() or not gen_band.any():
        return x
    ref, got = float(np.mean(px[ref_band])), float(np.mean(pg[gen_band]))
    if got <= 1e-20 or ref <= 1e-20:
        return x
    g = np.sqrt(ref / got) * dsp.db_to_gain(trim_db)
    return x + g * gen


def _super_mono(backend: str, x: np.ndarray, work: Path, tag: str, opts: dict, progress, cancel,
                lo: float, hi: float) -> np.ndarray:
    if backend == "builtin":
        if cancel and cancel():
            raise RuntimeError("Cancelled")
        if progress:
            progress(hi, "Built-in bandwidth extension")
        return builtin_extend(x, opts["cutoff"])
    if backend != "flashsr" or not opts.get("two_pass", True) or x.size <= FLASHSR_WINDOW:
        return _run_model(backend, x, work, tag, opts, progress, cancel, lo, hi)
    half = FLASHSR_WINDOW // 2
    mid = (lo + hi) / 2
    a = _run_model(backend, x, work, tag + "a", opts, progress, cancel, lo, mid)
    shifted = np.concatenate([x[:half][::-1], x])          # reflect-pad by half a window
    b = _run_model(backend, shifted, work, tag + "b", opts, progress, cancel, mid, hi)[half:]
    wa = _window_weights(x.size, FLASHSR_WINDOW, 0)
    wb = _window_weights(x.size, FLASHSR_WINDOW, half)
    return (a * wa + b * wb) / np.maximum(wa + wb, 1e-9)


def upscale(src: str | Path, dst: str | Path, export_sr: int = 48000, backend: str | None = None,
            mode: str = "mid", force: bool = False, high_gain_db: float = 0.0, steps: int = 12,
            guidance: float = 2.0, two_pass: bool = True, progress=None, cancel=None,
            spectrograms: bool = True) -> dict:
    """→ report dict. Writes a float WAV at `export_sr` to `dst` (or copies when skipped)."""
    src, dst = Path(src), Path(dst)
    audio, sr = read_audio(src)
    audio = dsp.to_stereo(audio)
    before = spectrum.detect_cutoff(audio, sr)
    report = {"input": str(src), "output": str(dst), "sr_in": sr, "export_sr": export_sr,
              "cutoff_before_hz": before["cutoff_hz"], "mode": mode}
    need = spectrum.needs_superres(before["cutoff_hz"], export_sr)
    backend = backend or tools.resolve_backend("superres")
    report["backend"] = backend
    if backend.startswith("missing:"):
        report["note"] = f"{backend[8:]} is not installed, the built-in extension was used"
        backend = report["backend"] = "builtin"
    if (not need and not force) or backend == "off":
        report["skipped"] = ("bandwidth already fills the export format" if not need and not force
                             else "super-resolution is off")
        out = _resample(audio, sr, export_sr)
        write_audio(dst, out, export_sr, 32, "wav")
        report["cutoff_after_hz"] = spectrum.detect_cutoff(out, export_sr)["cutoff_hz"]
        return report

    if progress:
        progress(0.02, "Super-resolution: " + (tools.TOOLS[backend].label if backend in tools.TOOLS
                                                 else "built-in extension"))
    x48 = _resample(audio, sr, MODEL_SR)
    opts = {"steps": steps, "guidance": guidance, "two_pass": two_pass, "cutoff": before["cutoff_hz"]}
    work = Path(tempfile.mkdtemp(prefix="ams_sr_"))
    try:
        if mode == "lr":
            l = _super_mono(backend, x48[0], work, "l", opts, progress, cancel, 0.05, 0.5)
            r = _super_mono(backend, x48[1], work, "r", opts, progress, cancel, 0.5, 0.92)
            model = np.vstack([l, r])
            base = x48
        else:
            m = (x48[0] + x48[1]) / 2
            s = (x48[0] - x48[1]) / 2
            m_sr = _super_mono(backend, m, work, "m", opts, progress, cancel, 0.05, 0.92)
            model = m_sr[np.newaxis, :]
            base = m[np.newaxis, :]
        fc = max(2000.0, before["cutoff_hz"] * 0.97)
        merged = crossover(base, model, MODEL_SR, fc, high_gain_db=high_gain_db)
        if mode != "lr":
            merged = np.vstack([merged[0] + s, merged[0] - s])
        out = _resample(merged, MODEL_SR, export_sr)
        peak = float(np.max(np.abs(out)))
        if peak > 0.999:                      # model energy must never clip the export
            out *= 0.999 / peak
        write_audio(dst, out, export_sr, 32, "wav")
        after = spectrum.detect_cutoff(out, export_sr)
        report["cutoff_after_hz"] = after["cutoff_hz"]
        report["crossover_hz"] = round(fc, 1)
        if spectrograms:
            report["spectrogram_before"] = str(dst.with_name(dst.stem + "_spec_before.png"))
            report["spectrogram_after"] = str(dst.with_name(dst.stem + "_spec_after.png"))
            top = export_sr / 2
            spectrum.write_png(report["spectrogram_before"],
                               spectrum.spectrogram_image(audio, sr, max_hz=top, cutoff_hz=before["cutoff_hz"]))
            spectrum.write_png(report["spectrogram_after"],
                               spectrum.spectrogram_image(out, export_sr, max_hz=top, cutoff_hz=after["cutoff_hz"]))
        if progress:
            progress(1.0, f"Bandwidth {before['cutoff_hz'] / 1000:.1f} → {after['cutoff_hz'] / 1000:.1f} kHz")
        return report
    finally:
        shutil.rmtree(work, ignore_errors=True)
