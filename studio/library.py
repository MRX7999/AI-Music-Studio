"""Project folder index: generated songs, studio sessions and finished mixes.

Layout (shared by the PyQt app, the CLI and the native macOS app):
    <root>/generated/<title>/<title>.wav + <title>.json (sidecar) + stems/
    <song folder>/session.studio.json               — session of a song that came with stems
    <root>/sessions/<name>/session.studio.json + stems/   — imported songs
    <session folder>/renders/<mix>.<ext> + <mix>.report.json
"""
from __future__ import annotations

import json
from pathlib import Path

from .audio_io import audio_info
from .generators.base import GeneratedTrack, meta_number, meta_text

AUDIO_EXTS = (".wav", ".flac", ".m4a", ".mp3", ".aiff", ".aif", ".ogg")
MAX_ITEMS = 400


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def _in_stems(p: Path) -> bool:
    return any(part == "stems" or part.endswith(" — stems") for part in p.parts)


def track_entry(t: GeneratedTrack, sidecar: Path | None = None) -> dict:
    d = t.to_dict(None)
    d["sidecar"] = str(sidecar or t.path.with_suffix(".json"))
    d["mtime"] = _mtime(Path(t.path))
    # sidecars written by 1.2.0 hold "N/A" from ACE-Step covers: read the file instead of failing
    meta = d.get("meta") if isinstance(d.get("meta"), dict) else {}
    for k in ("bpm", "duration"):
        if k in meta:
            meta[k] = meta_number(meta[k])
    for k in ("key", "time_signature"):
        if k in meta:
            meta[k] = meta_text(meta[k])
    dur = meta.get("duration") or meta_number(audio_info(t.path).get("duration"))
    d["duration"] = dur
    return d


def scan(root: str | Path) -> dict:
    """→ {"root", "songs": [...], "sessions": [...], "renders": [...]} — newest first."""
    root = Path(root).expanduser()
    out = {"root": str(root), "songs": [], "sessions": [], "renders": []}
    if not root.is_dir():
        return out
    files = sorted((p for p in root.glob("**/*.json") if not _in_stems(p.relative_to(root))),
                   key=_mtime, reverse=True)[: MAX_ITEMS * 3]
    for side in files:
        name = side.name
        try:
            if name.endswith(".studio.json"):
                d = json.loads(side.read_text(encoding="utf-8"))
                meta = d.get("meta") or {}
                out["sessions"].append({
                    "path": str(side), "name": meta.get("title") or d.get("name") or side.parent.name,
                    "scene": d.get("scene"), "channels": len(d.get("channels") or []),
                    "mtime": _mtime(side), "folder": str(side.parent),
                })
            elif name.endswith(".report.json"):
                base = name[: -len(".report.json")]
                audio = next((side.with_name(base + ext) for ext in AUDIO_EXTS
                              if side.with_name(base + ext).exists()), None)
                if audio is None:
                    continue
                rep = json.loads(side.read_text(encoding="utf-8"))
                m = rep.get("master") or {}
                out["renders"].append({
                    "path": str(audio), "report_path": str(side), "name": base, "mtime": _mtime(audio),
                    "format": audio.suffix.lstrip(".").lower(), "duration_s": rep.get("duration_s"),
                    "lufs": m.get("lufs_after", m.get("lufs")), "true_peak_db": m.get("true_peak_db"),
                    "scene": (rep.get("scene") or {}).get("name"), "sample_rate": rep.get("sample_rate"),
                    "scene_id": (rep.get("scene") or {}).get("id"),
                })
            else:
                t = GeneratedTrack.from_sidecar(side)
                if not Path(t.path).exists() or Path(t.path).suffix.lower() not in AUDIO_EXTS:
                    continue
                out["songs"].append(track_entry(t, side))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    for k in ("songs", "sessions", "renders"):
        out[k] = out[k][:MAX_ITEMS]
    return out
