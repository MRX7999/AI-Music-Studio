"""Distributor package: what DistroKid / TuneCore / CD Baby / Onerpm / Zvonko / Believe and the
like ask for. They deliver to Spotify, Apple Music, Yandex Music, VK Music, Deezer; those stores
accept music only through distributors.

Layout:
  <out>/<Artist> - <Title>/
      <Artist> - <Title>.<wav|flac|m4a|mp3>
                                 format, sample rate and bit depth (or MP3 bitrate) chosen like in
                                 Export; default WAV 44.1 kHz / 24-bit with TPDF dither. Tags are
                                 embedded: title, artists, album, genre, date, credits, label,
                                 copyright, ISRC/UPC, language, lyrics, cover, AI note
      cover.jpg                  3000×3000 RGB
      lyrics.txt, lyrics.lrc     plain lyrics (no section tags) and synced lyrics (if available)
      metadata.json              title, artists, genre, language, explicit, credits, AI disclosure
      ai_check.json              detector report (if the check was run)
      checks.json                technical validation (format, peak, loudness, cover size)
      SHA256SUMS                 checksums of every file
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from .. import dsp, loudness, tags
from ..audio_io import read_audio
from ..generators.base import safe_name
from .media import ffmpeg, image_size

DIST_SR = 44100
DIST_BITS = 24
COVER_MIN = 3000
FORMATS = ("wav", "flac", "alac", "mp3")
RATES = (44100, 48000, 88200, 96000)
MP3_RATES = (128, 192, 256, 320)
EXT = {"wav": ".wav", "flac": ".flac", "alac": ".m4a", "mp3": ".mp3"}
SUBTYPE = {16: "PCM_16", 24: "PCM_24", 32: "FLOAT"}
# what the M4A (iTunes) atoms written by ffmpeg can hold
ALAC_FIELDS = ("title", "artist", "album", "genre", "date", "year", "composer", "copyright")


def options(opts: dict | None) -> dict:
    """Package options with Export-like defaults and limits of each format."""
    o = dict(opts or {})
    fmt = str(o.get("format") or "wav").lower()
    fmt = fmt if fmt in FORMATS else "wav"
    try:
        sr = int(float(o.get("sample_rate") or DIST_SR))
    except (TypeError, ValueError):
        sr = DIST_SR
    sr = sr if sr in RATES else DIST_SR
    try:
        bits = int(float(o.get("bit_depth") or DIST_BITS))
    except (TypeError, ValueError):
        bits = DIST_BITS
    bits = bits if bits in (16, 24, 32) else DIST_BITS
    try:
        kbps = int(float(o.get("mp3_bitrate") or 320))
    except (TypeError, ValueError):
        kbps = 320
    kbps = kbps if kbps in MP3_RATES else 320
    if fmt in ("flac", "alac"):
        bits = min(bits, 24)                      # integer formats; 32-bit float is WAV only
    if fmt == "mp3":
        sr = min(sr, 48000)                       # MPEG-1 Layer III tops out at 48 kHz
        bits = 32                                 # the encoder gets the float signal, no dither
    dither = str(o.get("dither") or "tpdf").lower()
    return {"format": fmt, "sample_rate": sr, "bit_depth": bits, "mp3_bitrate": kbps,
            "dither": "off" if dither == "off" else "tpdf",
            "embed_cover": bool(o.get("embed_cover", True)), "embed_lyrics": bool(o.get("embed_lyrics", True))}


def describe(o: dict) -> str:
    sr = f"{o['sample_rate'] / 1000:g} kHz"
    if o["format"] == "mp3":
        return f"MP3 {o['mp3_bitrate']} kbps / {sr}"
    depth = "32-bit float" if o["bit_depth"] == 32 else f"{o['bit_depth']}-bit"
    return f"{o['format'].upper()} {sr} / {depth}"


def validate(audio: np.ndarray, sr: int, cover: Path | None, meta: dict, opts: dict | None = None,
             embedded: list[str] | None = None) -> list[dict]:
    checks = []
    o = options(opts)

    def add(key, ok, msg, level="error"):
        checks.append({"check": key, "ok": bool(ok), "level": "ok" if ok else level, "message": msg})

    if o["format"] == "mp3":
        add("format", False, f"Format {describe(o)} — lossy; distributors ask for WAV or FLAC", "warning")
    elif o["bit_depth"] == 32:
        add("format", False, f"Format {describe(o)} — many distributors accept only 16/24-bit", "warning")
    else:
        add("format", True, f"Format {describe(o)}")
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
    if embedded is not None:
        add("tags", bool(embedded), "Tags in the file: " + (", ".join(embedded) if embedded else "none"), "warning")
    return checks


def _encode(a: np.ndarray, sr: int, dst: Path, o: dict, fields: dict, lyrics: str, cover: Path | None) -> Path:
    """Writes the audio in the chosen format and embeds the tags. Returns the written path."""
    fmt, bits = o["format"], o["bit_depth"]
    dst = dst.with_suffix(EXT[fmt])
    if fmt == "wav":
        sf.write(str(dst), a.T, sr, subtype=SUBTYPE[bits], format="WAV")
        return tags.embed_wav(dst, fields, lyrics, cover)
    if fmt == "flac":
        sf.write(str(dst), a.T, sr, subtype=SUBTYPE[bits], format="FLAC")
        return tags.embed_flac(dst, fields, lyrics, cover)
    exe = ffmpeg()
    with tempfile.TemporaryDirectory(prefix="ams_pkg_") as td:
        tmp = Path(td) / "in.wav"
        sf.write(str(tmp), a.T, sr, subtype="FLOAT" if fmt == "mp3" else SUBTYPE[bits], format="WAV")
        cmd = [exe, "-y", "-hide_banner", "-loglevel", "error", "-i", str(tmp)]
        if fmt == "mp3":
            cmd += ["-map", "0:a", "-c:a", "libmp3lame", "-b:a", f"{o['mp3_bitrate']}k", "-id3v2_version", "0",
                    "-write_id3v1", "0", str(dst)]
            subprocess.run(cmd, check=True, capture_output=True)
            return tags.embed_mp3(dst, fields, lyrics, cover)
        if cover:
            cmd += ["-i", str(cover), "-map", "0:a", "-map", "1:v", "-c:v", "copy", "-disposition:v", "attached_pic"]
        else:
            cmd += ["-map", "0:a"]
        cmd += ["-c:a", "alac", "-sample_fmt", "s16p" if bits == 16 else "s32p"]
        for k, v in tags.ffmpeg_metadata(fields, lyrics).items():
            cmd += ["-metadata", f"{k}={v}"]
        subprocess.run(cmd + [str(dst)], check=True, capture_output=True)
        return dst


def build(master: str | Path, out_root: str | Path, meta: dict, cover: str | Path | None = None,
          lyrics_text: str = "", lrc_path: str | Path | None = None, ai_report: dict | None = None,
          progress=None, opts: dict | None = None) -> dict:
    master = Path(master)
    o = options(opts)
    artist = (meta.get("artist") or "Unknown Artist").strip()
    title = (meta.get("title") or master.stem).strip()
    folder = Path(out_root) / safe_name(f"{artist} - {title}", "release")
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    if progress:
        progress(0.1, f"Package: {describe(o)}")
    a, sr = read_audio(master)
    a = dsp.to_stereo(a)
    out_sr = o["sample_rate"]
    if sr != out_sr:
        a = dsp.resample(a, sr, out_sr)
    if o["bit_depth"] < 32 and o["dither"] != "off":
        a = dsp.tpdf_dither(a, o["bit_depth"])
    a = np.clip(a, -1.0, 1.0)
    cov = None
    if cover and Path(cover).exists():
        cov = folder / ("cover" + Path(cover).suffix.lower().replace(".jpeg", ".jpg"))
        shutil.copy2(cover, cov)
    lrc_text = Path(lrc_path).read_text(encoding="utf-8", errors="replace") \
        if lrc_path and Path(lrc_path).exists() else ""
    plain = tags.clean_lyrics(lyrics_text, lrc_text)
    if plain:
        (folder / "lyrics.txt").write_text(plain + "\n", encoding="utf-8")
    if lrc_text:
        shutil.copy2(lrc_path, folder / "lyrics.lrc")
    ai = dict(meta.get("ai") or {})
    if ai_report:
        ai["detection"] = {"verdict": ai_report.get("verdict"), "max_score": ai_report.get("max_score"),
                           "flagged_by": ai_report.get("flagged_by"), "time": ai_report.get("time")}
        (folder / "ai_check.json").write_text(json.dumps(ai_report, ensure_ascii=False, indent=2), encoding="utf-8")
    ai_note = ""
    if ai.get("generated", True):
        used = ", ".join(ai.get("tools") or [])
        ai_note = "Made with AI" + (f" ({used})" if used else "")
    fields = tags.tag_fields({**meta, "title": title, "artist": artist}, title, artist, ai_note)
    tag_lyrics = plain if o["embed_lyrics"] else ""
    tag_cover = cov if o["embed_cover"] else None
    if progress:
        progress(0.5, f"Package: writing {o['format'].upper()} with tags")
    audio = _encode(a, out_sr, folder / safe_name(f"{artist} - {title}", "track"), o, fields, tag_lyrics, tag_cover)
    stored = ALAC_FIELDS if o["format"] == "alac" else ("title", "artist", "album", "genre", "date", "year",
                                                         "composer", "lyricist", "producer", "label", "copyright",
                                                         "isrc", "upc", "language")
    embedded = [k for k in stored if fields.get(k)]
    if "date" in embedded and "year" in embedded:
        embedded.remove("year")
    if tag_lyrics:
        embedded.append("lyrics")
    if tag_cover:
        embedded.append("cover")
    full = {
        "title": title, "artist": artist, "featuring": meta.get("featuring", ""),
        "album": meta.get("album") or title, "release_type": meta.get("release_type", "single"),
        "genre": meta.get("genre", ""), "subgenre": meta.get("subgenre", ""),
        "language": meta.get("language", ""), "explicit": bool(meta.get("explicit", False)),
        "release_date": meta.get("release_date", ""), "isrc": meta.get("isrc", ""), "upc": meta.get("upc", ""),
        "composer": meta.get("composer", ""), "lyricist": meta.get("lyricist", ""),
        "producer": meta.get("producer", ""), "label": meta.get("label", ""), "copyright": meta.get("copyright", ""),
        "file": audio.name, "format": o["format"], "duration_s": round(a.shape[1] / out_sr, 3),
        "sample_rate": out_sr, "bit_depth": None if o["format"] == "mp3" else o["bit_depth"],
        "mp3_bitrate_kbps": o["mp3_bitrate"] if o["format"] == "mp3" else None,
        "dither": o["dither"] if o["bit_depth"] < 32 else "off", "embedded_tags": embedded,
        "loudness_lufs": round(loudness.integrated_lufs(a, out_sr), 2),
        "true_peak_dbtp": round(loudness.true_peak_db(a), 2),
        "ai": ai, "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "tool": "AI Music Studio",
    }
    (folder / "metadata.json").write_text(json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8")
    checks = validate(a, out_sr, cov, full, o, embedded)
    (folder / "checks.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")
    sums = []
    for p in sorted(folder.iterdir()):
        if p.is_file() and p.name != "SHA256SUMS":
            h = hashlib.sha256()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            sums.append(f"{h.hexdigest()}  {p.name}")
    (folder / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    if progress:
        progress(1.0, f"Package ready: {folder.name}")
    return {"folder": str(folder), "audio": str(audio), "wav": str(audio), "format": o["format"],
            "options": o, "cover": str(cov) if cov else "", "embedded": embedded, "checks": checks,
            "ok": all(c["ok"] or c["level"] != "error" for c in checks)}
