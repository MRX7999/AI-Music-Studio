"""Cover art: local image model (Z-Image Turbo on MLX via mflux) or a procedural cover drawn from
the audio itself; both end as 3000×3000 RGB (distributor format) plus small variants.

Z-Image Turbo is Apache-2.0, 9 steps; the pre-quantised 4-bit build keeps memory use modest.
Upscaling to 3000 px uses `sips` (built into macOS) or ffmpeg (Lanczos).
"""
from __future__ import annotations

import random
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from . import dsp, spectrum, tools
from .audio_io import read_audio

MFLUX_MODEL = "filipstrand/Z-Image-Turbo-mflux-4bit"
SIZE = 3000


def build_prompt(title: str = "", style: str = "", mood: str = "", extra: str = "") -> str:
    parts = ["album cover art, square composition, high detail, no text, no letters, no watermark"]
    if style:
        parts.append(f"music genre: {style}")
    if mood:
        parts.append(f"mood: {mood}")
    if title:
        parts.append(f"inspired by the song title \"{title}\"")
    if extra:
        parts.append(extra)
    return ", ".join(parts)


def image_convert(src: str | Path, dst: str | Path, size: int, fmt: str = "jpeg", quality: int = 92) -> Path:
    """Square resize + format conversion with sips (macOS) or ffmpeg. Returns the written path."""
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    sips = shutil.which("sips")
    if sips:
        cmd = [sips, "-s", "format", fmt, "-z", str(size), str(size)]
        if fmt == "jpeg":
            cmd += ["-s", "formatOptions", str(quality)]
        r = subprocess.run(cmd + [str(src), "--out", str(dst)], capture_output=True, text=True)
        if r.returncode == 0 and dst.exists():
            return dst
    ff = shutil.which("ffmpeg") or tools.find_executable("ffmpeg")
    if not ff:
        if src.suffix.lower() == dst.suffix.lower():
            shutil.copy2(src, dst)
            return dst
        raise RuntimeError("Image conversion needs sips (macOS) or ffmpeg")
    q = str(max(2, min(31, int(round((100 - quality) / 3.2)))))
    cmd = [ff, "-y", "-loglevel", "error", "-i", str(src), "-vf",
           f"scale={size}:{size}:flags=lanczos,format=rgb24" if fmt != "jpeg" else
           f"scale={size}:{size}:flags=lanczos,format=yuvj444p"]
    if fmt == "jpeg":
        cmd += ["-q:v", q]
    subprocess.run(cmd + ["-frames:v", "1", str(dst)], check=True)
    return dst


def procedural(audio_path: str | Path | None, dst: str | Path, seed: int | None = None, title: str = "",
               size: int = SIZE) -> Path:
    """Gradient field + polar spectrogram of the song. Deterministic for a given seed and audio."""
    rng = np.random.default_rng(seed if seed is not None else random.randint(0, 2**31 - 1))
    n = 1000                                   # drawn at 1000 px, scaled to `size`
    y, x = np.mgrid[0:n, 0:n] / n
    hues = rng.uniform(0, 1, 3)
    base = np.zeros((n, n, 3))
    for c in range(3):
        base[..., c] = 0.15 + 0.35 * (0.5 + 0.5 * np.sin(2 * np.pi * (x * (1 + hues[c]) + y * (2 - hues[c]) + hues[c])))
    if audio_path and Path(audio_path).exists():
        a, sr = read_audio(audio_path)
        mono = dsp.to_stereo(a).mean(axis=0)
        img = spectrum.spectrogram_image(mono[np.newaxis, :], sr, width=720, height=256, max_hz=min(16000, sr / 2),
                                         floor_db=-80)
        lum = img.mean(axis=2) / 255.0          # (256 freq, 720 time)
        cy, cx = y - 0.5, x - 0.5
        r = np.sqrt(cx ** 2 + cy ** 2)
        th = (np.arctan2(cy, cx) + np.pi) / (2 * np.pi)
        ring = (r > 0.12) & (r < 0.46)
        fi = np.clip(((r - 0.12) / 0.34 * 255).astype(int), 0, 255)
        ti = np.clip((th * 719).astype(int), 0, 719)
        v = np.where(ring, lum[255 - fi, ti], 0.0)
        col = spectrum.colormap(v).astype(np.float64) / 255.0
        base = base * (1 - 0.85 * v[..., None]) + col * (0.85 * v[..., None])
    vign = 1 - 0.55 * np.clip(np.sqrt((x - 0.5) ** 2 + (y - 0.5) ** 2) * 1.6, 0, 1) ** 2
    rgb = (np.clip(base * vign[..., None], 0, 1) * 255).astype(np.uint8)
    dst = Path(dst)
    with tempfile.TemporaryDirectory() as td:
        tmp = spectrum.write_png(Path(td) / "c.png", rgb)
        try:
            return image_convert(tmp, dst.with_suffix(".jpg"), size, "jpeg")
        except (RuntimeError, subprocess.CalledProcessError):
            # no converter: keep the 1000 px PNG (still a valid cover for Telegram / YouTube)
            out = dst.with_suffix(".png")
            shutil.copy2(tmp, out)
            return out


def generate(dst: str | Path, prompt: str, seed: int | None = None, backend: str | None = None,
             steps: int = 9, audio_path: str | Path | None = None, progress=None, cancel=None) -> dict:
    """→ {"cover": path (3000×3000 JPEG), "thumb": 320 px JPEG, "backend", "prompt", "seed"}."""
    dst = Path(dst)
    seed = seed if seed is not None else random.randint(0, 2**31 - 1)
    backend = backend or tools.resolve_backend("cover")
    res = {"prompt": prompt, "seed": seed}
    if backend == "mflux":
        with tempfile.TemporaryDirectory(prefix="ams_cover_") as td:
            raw = Path(td) / "cover.png"
            argv = tools.build_argv("mflux", {"model": MFLUX_MODEL, "prompt": prompt, "width": 1024, "height": 1024,
                                              "steps": steps, "seed": seed, "output": str(raw)})
            if progress:
                progress(0.05, "Z-Image Turbo (MLX): generating")
            tools.run(argv, progress=progress, cancel=cancel, lo=0.05, hi=0.9, label="Cover", timeout=1800)
            if not raw.exists():
                found = sorted(Path(td).glob("*.png"))
                if not found:
                    raise RuntimeError("mflux wrote no image")
                raw = found[0]
            cover = image_convert(raw, dst.with_suffix(".jpg"), SIZE, "jpeg")
        res["backend"] = "mflux"
    else:
        if progress:
            progress(0.2, "Procedural cover from the song spectrum")
        cover = procedural(audio_path, dst, seed=seed)
        res["backend"] = "procedural"
    res["cover"] = str(cover)
    try:
        res["thumb"] = str(image_convert(cover, dst.with_name(dst.stem + "_thumb.jpg"), 320, "jpeg", 80))
    except (RuntimeError, subprocess.CalledProcessError):
        res["thumb"] = ""
    if progress:
        progress(1.0, "Cover ready")
    return res
