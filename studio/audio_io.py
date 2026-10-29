"""Чтение/запись аудио: soundfile для WAV/FLAC/MP3, ffmpeg для M4A/ALAC/AAC и экспорта."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from .dsp import as_2d, resample

_CACHE: dict = {}
_CACHE_MAX = 24


def have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def read_audio(path: str | Path) -> tuple[np.ndarray, int]:
    """→ (audio (ch, n) float64, sr). M4A/AAC/OGG-Opus идут через ffmpeg."""
    path = Path(path)
    try:
        data, sr = sf.read(str(path), dtype="float64", always_2d=True)
        return data.T.copy(), int(sr)
    except Exception:
        if not have_ffmpeg():
            raise RuntimeError(f"Не удалось прочитать {path.name}: нужен ffmpeg (brew install ffmpeg)")
        with tempfile.TemporaryDirectory(prefix="ams_read_") as td:
            tmp = Path(td) / "decoded.wav"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-vn",
                            "-c:a", "pcm_f32le", str(tmp)], check=True)
            data, sr = sf.read(str(tmp), dtype="float64", always_2d=True)
            return data.T.copy(), int(sr)


def load_cached(path: str | Path, sr: int) -> np.ndarray:
    """Загрузка с ресемплингом и кэшем по (путь, mtime, sr) — превью рендерится мгновенно."""
    p = Path(path)
    key = (str(p.resolve()), p.stat().st_mtime, int(sr))
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    audio, file_sr = read_audio(p)
    audio = resample(audio, file_sr, sr) if file_sr != sr else audio
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = audio
    return audio


def audio_info(path: str | Path) -> dict:
    p = Path(path)
    try:
        i = sf.info(str(p))
        return {"sr": i.samplerate, "channels": i.channels, "duration": i.frames / i.samplerate}
    except Exception:
        if have_ffmpeg() and shutil.which("ffprobe"):
            out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                  "-of", "default=nw=1:nk=1", str(p)], capture_output=True, text=True)
            try:
                return {"sr": None, "channels": None, "duration": float(out.stdout.strip())}
            except ValueError:
                pass
        return {"sr": None, "channels": None, "duration": None}


SUBTYPES = {16: "PCM_16", 24: "PCM_24", 32: "FLOAT"}


def write_audio(path: str | Path, audio: np.ndarray, sr: int, bit_depth: int = 24,
                fmt: str | None = None, metadata: dict | None = None, cover: str | Path | None = None) -> Path:
    """fmt: wav / flac / alac / mp3. Возвращает фактический путь (с правильным расширением)."""
    a = np.clip(as_2d(audio), -1.0, 1.0).T
    path = Path(path)
    fmt = (fmt or path.suffix.lstrip(".") or "wav").lower()
    ext = {"wav": ".wav", "flac": ".flac", "alac": ".m4a", "m4a": ".m4a", "mp3": ".mp3"}.get(fmt, ".wav")
    path = path.with_suffix(ext)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "wav":
        sf.write(str(path), a, sr, subtype=SUBTYPES.get(bit_depth, "PCM_24"))
        return path
    if fmt == "flac" and not metadata and not cover:
        sf.write(str(path), a, sr, subtype=SUBTYPES.get(min(bit_depth, 24), "PCM_24"), format="FLAC")
        return path
    if not have_ffmpeg():
        raise RuntimeError("Для FLAC с тегами, ALAC и MP3 нужен ffmpeg (brew install ffmpeg)")
    with tempfile.TemporaryDirectory(prefix="ams_write_") as td:
        tmp = Path(td) / "mix.wav"
        sf.write(str(tmp), a, sr, subtype="FLOAT" if bit_depth == 32 else SUBTYPES.get(bit_depth, "PCM_24"))
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp)]
        has_cover = cover and Path(cover).exists() and fmt in ("flac", "alac", "m4a", "mp3")
        if has_cover:
            cmd += ["-i", str(cover), "-map", "0:a", "-map", "1:v", "-c:v", "copy" if fmt != "mp3" else "mjpeg",
                    "-disposition:v", "attached_pic"]
        if fmt == "flac":
            cmd += ["-c:a", "flac", "-compression_level", "8",
                    "-sample_fmt", "s16" if bit_depth == 16 else "s32"]
        elif fmt in ("alac", "m4a"):
            cmd += ["-c:a", "alac", "-sample_fmt", "s16p" if bit_depth == 16 else "s32p"]
        elif fmt == "mp3":
            cmd += ["-c:a", "libmp3lame", "-b:a", "320k", "-id3v2_version", "3"]
        for k, v in (metadata or {}).items():
            if v:
                cmd += ["-metadata", f"{k}={v}"]
        cmd.append(str(path))
        subprocess.run(cmd, check=True)
    return path
