"""Distributor package: what DistroKid / TuneCore / CD Baby / Onerpm / Zvonko / Believe and the
like ask for. They deliver to Spotify, Apple Music, Yandex Music, VK Music, Deezer; those stores
accept music only through distributors.

Layout:
  <out>/<Artist> - <Title>/
      <Artist> - <Title>.wav     44.1 kHz / 24-bit PCM (TPDF dither from the float master)
      cover.jpg                  3000×3000 RGB
      lyrics.txt, lyrics.lrc     plain lyrics and synced lyrics (if available)
      metadata.json              title, artists, genre, language, explicit, credits, AI disclosure
      ai_check.json              detector report (if the check was run)
      checks.json                technical validation (sample rate, peak, loudness, cover size)
      SHA256SUMS                 checksums of every file
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path

import numpy as np

from .. import dsp, loudness
from ..audio_io import read_audio, write_audio
from ..generators.base import safe_name
from .media import image_size

DIST_SR = 44100
DIST_BITS = 24
COVER_MIN = 3000


def validate(audio: np.ndarray, sr: int, cover: Path | None, meta: dict) -> list[dict]:
    checks = []

    def add(key, ok, msg, level="error"):
        checks.append({"check": key, "ok": bool(ok), "level": "ok" if ok else level, "message": msg})

    dur = audio.shape[1] / sr
    add("duration", 30 <= dur <= 3600, f"Duration {dur:.1f} s", "warning")
    tp = loudness.true_peak_db(audio)
    lufs = loudness.integrated_lufs(audio, sr)
    add("true_peak", tp <= -1.0, f"True peak {tp:.2f} dBTP (stores recommend ≤ −1 dBTP)", "warning")
    add("loudness", -16.5 <= lufs <= -7.0, f"Integrated {lufs:.1f} LUFS", "warning")
    if cover and cover.exists():
        w, h = image_size(cover)
        add("cover_size", w == h and w >= COVER_MIN, f"Cover {w}×{h} (need square ≥ {COVER_MIN} px)")
    else:
        add("cover_size", False, "No cover")
    add("title", bool((meta.get("title") or "").strip()), "Title")
    add("artist", bool((meta.get("artist") or "").strip()), "Primary artist")
    ai = meta.get("ai") or {}
    add("ai_disclosure", "generated" in ai, "AI disclosure set" if "generated" in ai else
        "AI disclosure missing", "error")
    return checks


def build(master: str | Path, out_root: str | Path, meta: dict, cover: str | Path | None = None,
          lyrics_text: str = "", lrc_path: str | Path | None = None, ai_report: dict | None = None,
          progress=None) -> dict:
    master = Path(master)
    artist = (meta.get("artist") or "Unknown Artist").strip()
    title = (meta.get("title") or master.stem).strip()
    folder = Path(out_root) / safe_name(f"{artist} - {title}", "release")
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    if progress:
        progress(0.1, "Package: 44.1 kHz / 24-bit master")
    a, sr = read_audio(master)
    a = dsp.to_stereo(a)
    if sr != DIST_SR:
        a = dsp.resample(a, sr, DIST_SR)
    a = dsp.tpdf_dither(a, DIST_BITS)
    wav = write_audio(folder / f"{safe_name(f'{artist} - {title}', 'track')}.wav", a, DIST_SR, DIST_BITS, "wav")
    cov = None
    if cover and Path(cover).exists():
        cov = folder / ("cover" + Path(cover).suffix.lower().replace(".jpeg", ".jpg"))
        shutil.copy2(cover, cov)
    if lyrics_text.strip():
        (folder / "lyrics.txt").write_text(lyrics_text.strip() + "\n", encoding="utf-8")
    if lrc_path and Path(lrc_path).exists():
        shutil.copy2(lrc_path, folder / "lyrics.lrc")
    ai = dict(meta.get("ai") or {})
    if ai_report:
        ai["detection"] = {"verdict": ai_report.get("verdict"), "max_score": ai_report.get("max_score"),
                           "flagged_by": ai_report.get("flagged_by"), "time": ai_report.get("time")}
        (folder / "ai_check.json").write_text(json.dumps(ai_report, ensure_ascii=False, indent=2), encoding="utf-8")
    full = {
        "title": title, "artist": artist, "featuring": meta.get("featuring", ""),
        "album": meta.get("album") or title, "release_type": meta.get("release_type", "single"),
        "genre": meta.get("genre", ""), "subgenre": meta.get("subgenre", ""),
        "language": meta.get("language", ""), "explicit": bool(meta.get("explicit", False)),
        "release_date": meta.get("release_date", ""), "isrc": meta.get("isrc", ""), "upc": meta.get("upc", ""),
        "composer": meta.get("composer", ""), "lyricist": meta.get("lyricist", ""),
        "producer": meta.get("producer", ""), "label": meta.get("label", ""), "copyright": meta.get("copyright", ""),
        "duration_s": round(a.shape[1] / DIST_SR, 3), "sample_rate": DIST_SR, "bit_depth": DIST_BITS,
        "loudness_lufs": round(loudness.integrated_lufs(a, DIST_SR), 2),
        "true_peak_dbtp": round(loudness.true_peak_db(a), 2),
        "ai": ai, "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "tool": "AI Music Studio",
    }
    (folder / "metadata.json").write_text(json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8")
    checks = validate(a, DIST_SR, cov, full)
    (folder / "checks.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")
    sums = []
    for p in sorted(folder.iterdir()):
        if p.is_file() and p.name != "SHA256SUMS":
            sums.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}")
    (folder / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    if progress:
        progress(1.0, f"Package ready: {folder.name}")
    return {"folder": str(folder), "wav": str(wav), "cover": str(cov) if cov else "", "checks": checks,
            "ok": all(c["ok"] or c["level"] != "error" for c in checks)}
