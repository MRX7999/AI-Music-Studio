"""Cover art: local image model (Z-Image Turbo on MLX via mflux) or a procedural cover drawn from
the audio itself; both end as 3000×3000 RGB (distributor format) plus small variants.

Z-Image Turbo is Apache-2.0, 9 steps; the pre-quantised 4-bit build keeps memory use modest.
Upscaling to 3000 px uses `sips` (built into macOS) or ffmpeg (Lanczos).

The model (~5.9 GB) is downloaded by the studio itself before the first generation
(ml_scripts/hf_download.py in mflux's own Python, with progress), then mflux runs offline. Letting
mflux download on its own broke on slow connections: huggingface_hub cannot continue a partial
file, so every interruption left gigabytes of dead `*.incomplete` files and an incomplete snapshot.
"""
from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from . import dsp, spectrum, tools
from .audio_io import read_audio

MFLUX_MODEL = "filipstrand/Z-Image-Turbo-mflux-4bit"
MFLUX_MODEL_BYTES = 5_910_000_000      # all files of the repo, for messages before the size is known
MFLUX_COMPONENTS = ("transformer", "text_encoder", "vae")
SIZE = 3000


def hf_cache_dir() -> Path:
    """The Hugging Face hub cache, resolved the way huggingface_hub does it."""
    for var in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        if os.environ.get(var):
            return Path(os.environ[var]).expanduser()
    if os.environ.get("HF_HOME"):
        return Path(os.environ["HF_HOME"]).expanduser() / "hub"
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "huggingface" / "hub"


def _snapshot_missing(snap: Path) -> list[str]:
    """Files of an mflux snapshot that are not there (shards listed in each index json + tokenizer)."""
    missing = []
    for comp in MFLUX_COMPONENTS:
        d = snap / comp
        shards: list[str] = []
        idx = d / "model.safetensors.index.json"
        if idx.is_file():
            try:
                shards = sorted(set((json.loads(idx.read_text("utf-8")).get("weight_map") or {}).values()))
            except (OSError, ValueError, AttributeError):
                shards = []
        if not shards:
            shards = sorted(x.name for x in d.glob("*.safetensors")) if d.is_dir() else []
        if not shards:
            missing.append(f"{comp}/")
            continue
        # is_file() follows the snapshot symlink: a link to a blob that never finished is missing
        missing += [f"{comp}/{sh}" for sh in shards if not (d / sh).is_file()]
    if not any((snap / "tokenizer" / f).is_file() for f in ("tokenizer.json", "tokenizer_config.json")):
        missing.append("tokenizer/")
    return missing


def model_status(repo: str = MFLUX_MODEL) -> dict:
    """Offline check of the Z-Image model in the HF cache → {complete, missing, bytes, stale_bytes, ...}.

    `bytes` = finished files, `stale_bytes` = partial files of interrupted downloads (deleted by the
    next download), `total_bytes` = size of the whole repo."""
    root = hf_cache_dir() / ("models--" + repo.replace("/", "--"))
    st = {"repo": repo, "complete": False, "missing": [], "bytes": 0, "stale_bytes": 0,
          "total_bytes": MFLUX_MODEL_BYTES, "path": "", "cache": str(hf_cache_dir())}
    blobs = root / "blobs"
    if blobs.is_dir():
        for b in blobs.iterdir():
            try:
                n = b.stat().st_size
            except OSError:
                continue
            if b.name.endswith(".incomplete"):
                st["stale_bytes"] += n
            else:
                st["bytes"] += n
    snaps = root / "snapshots"
    candidates: list[Path] = []
    ref = root / "refs" / "main"
    if ref.is_file():
        try:
            candidates.append(snaps / ref.read_text("utf-8").strip())
        except OSError:
            pass
    if snaps.is_dir():
        candidates += sorted((d for d in snaps.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime, reverse=True)
    best: tuple[Path, list[str]] | None = None
    for snap in candidates:
        if not snap.is_dir():
            continue
        miss = _snapshot_missing(snap)
        if best is None or len(miss) < len(best[1]):
            best = (snap, miss)
        if not miss:
            break
    if best is None:
        st["missing"] = ["(not downloaded)"]
        return st
    st["path"], st["missing"], st["complete"] = str(best[0]), best[1], not best[1]
    return st


def _gb(n: float) -> str:
    return f"{n / 1e9:.1f} GB"


def _download_error(out: str, st: dict) -> str:
    low = out.lower()
    got = f"{_gb(st['bytes'])} of {_gb(st['total_bytes'])} are downloaded"
    if "not enough disk space" in low or "no space left" in low:
        line = next((ln for ln in out.splitlines() if "disk space" in ln.lower()), "").replace("ERROR ", "")
        return f"Z-Image Turbo download stopped: {line or 'not enough disk space'}. Free some space and press Generate again."
    if "no connection" in low or "exited with code 2" in low:
        return (f"Z-Image Turbo download stopped: no connection to huggingface.co ({got}). Press Generate again "
                "when you are online; unfinished files are removed and the download starts over. "
                "Or use the procedural cover.")
    if "cancelled" in low:
        return "Cancelled"
    tail = [ln for ln in out.splitlines() if ln.strip()][-4:]
    return f"Z-Image Turbo download failed ({got}):\n" + "\n".join(tail)


def ensure_mflux_model(exe: str, progress=None, cancel=None, lo: float = 0.0, hi: float = 1.0) -> dict:
    """Downloads the Z-Image model with mflux's own huggingface_hub unless the cache is complete."""
    st = model_status()
    if st["complete"]:
        return st
    if progress:
        left = max(0, st["total_bytes"] - st["bytes"])
        progress(lo, f"Z-Image Turbo: downloading the model once (~{_gb(left)})")
    argv = [tools.tool_python(exe), str(tools.SCRIPTS_DIR / "hf_download.py"), MFLUX_MODEL, "--label", "Z-Image Turbo"]
    try:
        tools.run(argv, progress=progress, cancel=cancel, lo=lo, hi=hi, label="Z-Image Turbo download",
                  timeout=6 * 3600)
    except RuntimeError as e:
        raise RuntimeError(_download_error(str(e), model_status())) from None
    st = model_status()
    if not st["complete"]:
        raise RuntimeError("Z-Image Turbo download finished, but files are still missing: " + ", ".join(st["missing"]))
    return st


def _mflux_error(out: str) -> str:
    low = out.lower()
    if "insufficient memory" in low or "out of memory" in low or "outofmemory" in low or "kiogpucommandbuffer" in low:
        return ("Not enough memory for Z-Image Turbo. Close other heavy apps (the ACE-Step server, browsers) "
                "and try again, or use the procedural cover.")
    if "incompletesnapshot" in low or "localentrynotfound" in low or "offline" in low:
        return "Z-Image Turbo model files are incomplete. Press Generate again to finish the download."
    tail = [ln for ln in out.splitlines() if ln.strip()][-6:]
    return "mflux failed:\n" + "\n".join(tail)


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
        exe = tools.find_executable("mflux")
        if not exe:
            raise tools.ToolMissing("mflux")
        downloaded = not model_status()["complete"]
        ensure_mflux_model(exe, progress=progress, cancel=cancel, lo=0.02, hi=0.55)
        lo = 0.55 if downloaded else 0.05
        with tempfile.TemporaryDirectory(prefix="ams_cover_") as td:
            raw = Path(td) / "cover.png"
            argv = tools.build_argv("mflux", {"model": MFLUX_MODEL, "prompt": prompt, "width": 1024, "height": 1024,
                                              "steps": steps, "seed": seed, "output": str(raw)}, exe=exe)
            if progress:
                progress(lo, "Z-Image Turbo (MLX): generating")
            try:
                # the model is complete in the cache: no network round trips, no half-downloads
                tools.run(argv, progress=progress, cancel=cancel, lo=lo, hi=0.9, label="Cover", timeout=1800,
                          env_extra={"HF_HUB_OFFLINE": "1"})
            except RuntimeError as e:
                msg = str(e)
                if msg == "Cancelled" or msg.endswith("timeout after 1800 s"):
                    raise
                if "offline" in msg.lower() or "localentrynotfound" in msg.lower():
                    # a future mflux may need files outside this repo: one online attempt
                    try:
                        tools.run(argv, progress=progress, cancel=cancel, lo=lo, hi=0.9, label="Cover", timeout=1800)
                    except RuntimeError as e2:
                        raise RuntimeError(_mflux_error(str(e2))) from None
                else:
                    raise RuntimeError(_mflux_error(msg)) from None
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
