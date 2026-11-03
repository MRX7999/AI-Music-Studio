"""Synced lyrics: LRC / SRT from Whisper word timestamps aligned to the known lyrics.

Whisper on sung vocals mishears words, so the generation lyrics (if any) are the text source and
Whisper only provides timing: word sequences are aligned with difflib, each line starts at its
first matched word, unmatched lines are interpolated. Without lyrics the Whisper segments are used.

Section tags ([Verse 2], [Chorus], [Куплет 2]) become markers on the timeline; the timeline uses
them to select "regenerate the second verse".

Backends: mlx_whisper (MLX, whisper-large-v3-turbo) → whisper (PyTorch). Both are isolated CLIs.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from . import tools

MLX_MODEL = "mlx-community/whisper-large-v3-turbo"
TORCH_MODEL = "turbo"
# openai-whisper checkpoints, best first, with their file names in ~/.cache/whisper
_TORCH_FILES = [("turbo", "large-v3-turbo.pt"), ("large-v3", "large-v3.pt"), ("large-v2", "large-v2.pt"),
                ("large-v1", "large-v1.pt"), ("medium", "medium.pt"), ("small", "small.pt")]


def whisper_language(language: str) -> str:
    """Release language field → Whisper --language. "ru" → "ru"; "en / ru" (bilingual) or junk → ""
    (Whisper detects the language itself; a wrong forced language garbles the words)."""
    parts = [x for x in re.split(r"[\s,/;|+&]+", (language or "").strip().lower()) if x]
    if len(parts) != 1:
        return ""
    code = parts[0]
    return code if re.fullmatch(r"[a-z]{2,3}", code) or code in ("english", "russian") else ""


def whisper_cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "whisper"


def torch_model() -> tuple[str, bool]:
    """openai-whisper model to use → (name, already downloaded).

    turbo when it is downloaded or nothing is; otherwise the best checkpoint already on disk, so a
    user who ran `whisper --model medium` before does not wait for another 1.6 GB download."""
    cache = whisper_cache_dir()
    have = [name for name, f in _TORCH_FILES if (cache / f).is_file()]
    if TORCH_MODEL in have or not have:
        return TORCH_MODEL, TORCH_MODEL in have
    return have[0], True

_TAG = re.compile(r"^\s*\[([^\]]+)\]\s*$")
_INLINE_TAG = re.compile(r"\[[^\]]*\]|\([^)]*\)")
_WORD = re.compile(r"[\w']+", re.UNICODE)


def norm_word(w: str) -> str:
    return w.lower().replace("ё", "е").strip("'")


def parse_lyrics(text: str) -> list[dict]:
    """→ [{"text", "section"}] for every sung line (tags and empty lines removed)."""
    out, section = [], ""
    for raw in (text or "").splitlines():
        m = _TAG.match(raw)
        if m:
            section = m.group(1).strip()
            continue
        line = _INLINE_TAG.sub("", raw).strip()
        if line and _WORD.search(line):
            out.append({"text": line, "section": section})
    return out


def _words_of(text: str) -> list[str]:
    return [norm_word(w) for w in _WORD.findall(text)]


def transcribe(path: str | Path, language: str = "", backend: str | None = None, progress=None,
               cancel=None) -> dict:
    """→ {"words": [{"word","start","end"}], "segments": [...], "language", "backend"}."""
    path = Path(path)
    backend = backend or tools.resolve_backend("lyrics")
    if backend in ("builtin", "off") or backend.startswith("missing:"):
        raise tools.ToolMissing("mlx_whisper" if tools.is_apple_silicon() else "whisper")
    work = Path(tempfile.mkdtemp(prefix="ams_lrc_"))
    try:
        model_torch, cached = torch_model()
        values = {"input": str(path), "outdir": str(work), "name": "lyrics", "model": MLX_MODEL,
                  "model_torch": model_torch}
        argv = tools.build_argv(backend, values)
        lang = whisper_language(language)
        if lang:
            argv += ["--language", lang]
        if progress:
            label = tools.TOOLS[backend].label
            if backend == "whisper":
                label += f", {model_torch}" + ("" if cached else " — first run downloads the model")
            progress(0.05, f"Whisper ({label})")
        tools.run(argv, progress=progress, cancel=cancel, lo=0.05, hi=0.9, label="Whisper", timeout=3 * 3600)
        js = sorted(work.glob("*.json"))
        if not js:
            raise RuntimeError("Whisper wrote no JSON")
        data = json.loads(js[0].read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    words, segs = [], []
    for s in data.get("segments") or []:
        segs.append({"text": (s.get("text") or "").strip(), "start": float(s.get("start", 0)),
                     "end": float(s.get("end", 0))})
        for w in s.get("words") or []:
            t = (w.get("word") or "").strip()
            if t:
                words.append({"word": t, "start": float(w.get("start", 0)), "end": float(w.get("end", 0))})
    return {"words": words, "segments": segs, "language": data.get("language", language), "backend": backend,
            "model": model_torch if backend == "whisper" else MLX_MODEL}


def align(lines: list[dict], words: list[dict], duration: float | None = None) -> list[dict]:
    """Known lyric lines + Whisper words → lines with start/end (seconds)."""
    ref, owner = [], []
    for i, ln in enumerate(lines):
        for w in _words_of(ln["text"]):
            ref.append(w)
            owner.append(i)
    hyp = [norm_word(w["word"]) for w in words]
    hyp_clean, hyp_idx = [], []
    for j, h in enumerate(hyp):
        for part in _WORD.findall(h):
            hyp_clean.append(norm_word(part))
            hyp_idx.append(j)
    starts: list[float | None] = [None] * len(lines)
    ends: list[float | None] = [None] * len(lines)
    sm = difflib.SequenceMatcher(a=ref, b=hyp_clean, autojunk=False)
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            li = owner[blk.a + k]
            wj = words[hyp_idx[blk.b + k]]
            if starts[li] is None or wj["start"] < starts[li]:
                starts[li] = wj["start"]
            if ends[li] is None or wj["end"] > ends[li]:
                ends[li] = wj["end"]
    # monotonic clean-up: a line can not start before the previous one
    last = -1.0
    for i in range(len(lines)):
        if starts[i] is not None and starts[i] < last:
            starts[i] = ends[i] = None
        elif starts[i] is not None:
            last = starts[i]
    total = duration or (words[-1]["end"] if words else 0.0)
    known = [i for i, s in enumerate(starts) if s is not None]
    for i in range(len(lines)):
        if starts[i] is not None:
            continue
        prev = max((k for k in known if k < i), default=None)
        nxt = min((k for k in known if k > i), default=None)
        t0 = ends[prev] if prev is not None else 0.0
        t1 = starts[nxt] if nxt is not None else total
        span_lines = (nxt if nxt is not None else len(lines)) - (prev if prev is not None else -1)
        pos = i - (prev if prev is not None else -1)
        starts[i] = t0 + (t1 - t0) * (pos - 0.5) / max(span_lines, 1)
    out = []
    for i, ln in enumerate(lines):
        nxt = starts[i + 1] if i + 1 < len(lines) else total
        end = ends[i] if ends[i] is not None else nxt
        out.append({"text": ln["text"], "section": ln.get("section", ""), "start": round(starts[i], 2),
                    "end": round(max(min(end, nxt if nxt else end), starts[i] + 0.3), 2),
                    "matched": i in known})
    return out


def lines_from_segments(segments: list[dict]) -> list[dict]:
    return [{"text": s["text"], "section": "", "start": round(s["start"], 2), "end": round(s["end"], 2),
             "matched": True} for s in segments if s["text"]]


def sections(lines: list[dict]) -> list[dict]:
    """Section markers: [{"name", "start", "end", "index"}] — consecutive lines of one tag."""
    out = []
    for ln in lines:
        name = ln.get("section") or ""
        if out and out[-1]["name"] == name:
            out[-1]["end"] = ln["end"]
        else:
            out.append({"name": name or "Section", "start": ln["start"], "end": ln["end"]})
    for i, s in enumerate(out):
        s["index"] = i
    return out


def _ts_lrc(t: float) -> str:
    m, s = divmod(max(t, 0.0), 60)
    return f"{int(m):02d}:{s:05.2f}"


def _ts_srt(t: float) -> str:
    ms = int(round(max(t, 0.0) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_lrc(lines: list[dict], title: str = "", artist: str = "", duration: float | None = None) -> str:
    head = []
    if title:
        head.append(f"[ti:{title}]")
    if artist:
        head.append(f"[ar:{artist}]")
    if duration:
        m, s = divmod(int(duration), 60)
        head.append(f"[length:{m:02d}:{s:02d}]")
    head.append("[re:AI Music Studio]")
    return "\n".join(head + [f"[{_ts_lrc(ln['start'])}]{ln['text']}" for ln in lines]) + "\n"


def to_srt(lines: list[dict]) -> str:
    blocks = []
    for i, ln in enumerate(lines, 1):
        blocks.append(f"{i}\n{_ts_srt(ln['start'])} --> {_ts_srt(ln['end'])}\n{ln['text']}\n")
    return "\n".join(blocks)


def parse_lrc(text: str) -> list[dict]:
    out = []
    for raw in text.splitlines():
        m = re.match(r"^\[(\d+):(\d+(?:\.\d+)?)\](.*)$", raw.strip())
        if m:
            out.append({"text": m.group(3).strip(), "section": "",
                        "start": int(m.group(1)) * 60 + float(m.group(2))})
    for i, ln in enumerate(out):
        ln["end"] = out[i + 1]["start"] if i + 1 < len(out) else ln["start"] + 4.0
    return out


def build(audio_path: str | Path, lyrics_text: str = "", out_dir: str | Path | None = None, title: str = "",
          artist: str = "", language: str = "", duration: float | None = None, progress=None,
          cancel=None) -> dict:
    tr = transcribe(audio_path, language=language, progress=progress, cancel=cancel)
    known = parse_lyrics(lyrics_text)
    lines = align(known, tr["words"], duration) if known else lines_from_segments(tr["segments"])
    res = {"lines": lines, "sections": sections(lines), "backend": tr["backend"],
           "language": tr["language"], "matched": sum(1 for ln in lines if ln.get("matched")),
           "total": len(lines)}
    if out_dir:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(audio_path).stem
        (out_dir / f"{stem}.lrc").write_text(to_lrc(lines, title, artist, duration), encoding="utf-8")
        (out_dir / f"{stem}.srt").write_text(to_srt(lines), encoding="utf-8")
        res["lrc"] = str(out_dir / f"{stem}.lrc")
        res["srt"] = str(out_dir / f"{stem}.srt")
    if progress:
        progress(1.0, f"Lyrics: {res['matched']}/{res['total']} lines timed")
    return res
