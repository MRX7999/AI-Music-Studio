"""Embedded tags for delivered audio: title, artists, album, credits, codes, lyrics and the cover.

Pure Python, no tagging library needed:
  WAV   RIFF LIST/INFO (basic fields, read by every player) + an "id3 " chunk with ID3v2.3
        (Apple Music, Finder, Mp3tag, foobar2000, Rekordbox read it; it carries the cover and lyrics)
  MP3   ID3v2.3 in front of the audio (replaces any tag the encoder wrote)
  FLAC  VORBIS_COMMENT + PICTURE (front cover) metadata blocks
  ALAC  ffmpeg -metadata keys (see ffmpeg_metadata); the cover is attached by ffmpeg

`fields` is the dict made by `tag_fields()`.
"""
from __future__ import annotations

import os
import re
import shutil
import struct
import tempfile
from pathlib import Path

from . import __version__

LANG3 = {
    "en": "eng", "ru": "rus", "uk": "ukr", "be": "bel", "kk": "kaz", "de": "deu", "fr": "fra", "es": "spa",
    "it": "ita", "pt": "por", "pl": "pol", "cs": "ces", "nl": "nld", "sv": "swe", "no": "nor", "da": "dan",
    "fi": "fin", "tr": "tur", "ar": "ara", "he": "heb", "hi": "hin", "ja": "jpn", "ko": "kor", "zh": "zho",
    "el": "ell", "hu": "hun", "ro": "ron", "bg": "bul", "sr": "srp", "hr": "hrv", "ka": "kat", "hy": "hye",
    "az": "aze", "uz": "uzb", "id": "ind", "vi": "vie", "th": "tha", "fa": "fas", "la": "lat",
}
_NAMES = {"english": "eng", "russian": "rus", "русский": "rus", "английский": "eng", "ukrainian": "ukr",
          "українська": "ukr", "german": "deu", "french": "fra", "spanish": "spa", "italian": "ita",
          "japanese": "jpn", "korean": "kor", "chinese": "zho", "instrumental": "zxx"}


def lang3(value: str) -> str:
    """ISO 639-2 code for "en", "eng", "English", "ru-RU"…; "" when unknown. "en / ru" → "eng"."""
    for tok in re.split(r"[\s,/;|+]+", (value or "").strip().lower()):
        tok = tok.split("-")[0].split("_")[0]
        if not tok:
            continue
        if tok in _NAMES:
            return _NAMES[tok]
        if len(tok) == 2 and tok in LANG3:
            return LANG3[tok]
        if len(tok) == 3 and tok.isalpha() and tok.isascii():
            return tok
    return ""


def year_of(date: str) -> str:
    m = re.search(r"(19|20|21)\d\d", date or "")
    return m.group(0) if m else ""


def tag_fields(meta: dict, title: str, artist: str, ai_note: str = "") -> dict:
    """Normalised tag values from release metadata (empty values are dropped)."""
    date = str(meta.get("release_date") or "").strip()
    f = {
        "title": title, "artist": artist, "album": meta.get("album") or title,
        "album_artist": meta.get("album_artist") or artist, "genre": meta.get("genre", ""),
        "date": date, "year": year_of(date) or str(meta.get("year") or ""),
        "composer": meta.get("composer", ""), "lyricist": meta.get("lyricist", ""),
        "producer": meta.get("producer", ""), "label": meta.get("label", ""),
        "copyright": meta.get("copyright", ""), "isrc": str(meta.get("isrc") or "").replace("-", "").upper(),
        "upc": str(meta.get("upc") or "").strip(), "language": lang3(str(meta.get("language") or "")),
        "explicit": "1" if meta.get("explicit") else "", "comment": ai_note,
        "track": "1/1", "encoder": f"AI Music Studio {__version__}",
    }
    return {k: str(v).strip() for k, v in f.items() if str(v or "").strip()}


def clean_lyrics(text: str, lrc_text: str = "") -> str:
    """Plain lyrics for stores and tags: section tags removed, a blank line between sections.
    Falls back to the lines of an LRC file."""
    from .lyrics import parse_lrc, parse_lyrics
    lines = parse_lyrics(text or "")
    if not lines and lrc_text:
        lines = [{"text": ln["text"], "section": ""} for ln in parse_lrc(lrc_text) if ln["text"]
                 and not ln["text"].startswith("[")]
    out, prev = [], None
    for ln in lines:
        if prev is not None and ln.get("section") != prev and out:
            out.append("")
        out.append(ln["text"])
        prev = ln.get("section")
    return "\n".join(out).strip()


def picture_info(cover: str | Path | None) -> tuple[bytes, str, int, int] | None:
    if not cover or not Path(cover).exists():
        return None
    from .publish.media import image_size
    data = Path(cover).read_bytes()
    mime = "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
    try:
        w, h = image_size(cover)
    except ValueError:
        return None
    return data, mime, w, h


# ── ID3v2.3 ──────────────────────────────────────────────────

def _u16(s: str) -> bytes:
    return s.encode("utf-16")                       # with BOM, as ID3v2.3 encoding 1 requires


def _frame(fid: str, body: bytes) -> bytes:
    return fid.encode("ascii") + struct.pack(">I", len(body)) + b"\x00\x00" + body


def _text(fid: str, value: str) -> bytes:
    return _frame(fid, b"\x01" + _u16(value))


def _txxx(desc: str, value: str) -> bytes:
    return _frame("TXXX", b"\x01" + _u16(desc) + b"\x00\x00" + _u16(value))


def _syncsafe(n: int) -> bytes:
    return bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F])


ID3_TEXT = (("title", "TIT2"), ("artist", "TPE1"), ("album_artist", "TPE2"), ("album", "TALB"),
            ("genre", "TCON"), ("year", "TYER"), ("composer", "TCOM"), ("lyricist", "TEXT"),
            ("label", "TPUB"), ("copyright", "TCOP"), ("isrc", "TSRC"), ("language", "TLAN"),
            ("track", "TRCK"), ("encoder", "TSSE"))


def id3v23(fields: dict, lyrics: str = "", cover: str | Path | None = None, padding: int = 1024) -> bytes:
    frames = [_text(fid, fields[k]) for k, fid in ID3_TEXT if fields.get(k)]
    for desc, key in (("BARCODE", "upc"), ("PRODUCER", "producer"), ("ITUNESADVISORY", "explicit"),
                      ("RELEASEDATE", "date")):
        if fields.get(key):
            frames.append(_txxx(desc, fields[key]))
    lang = (fields.get("language") or "xxx")[:3].encode("ascii", "replace").ljust(3, b"x")
    if fields.get("comment"):
        frames.append(_frame("COMM", b"\x01" + lang + _u16("") + b"\x00\x00" + _u16(fields["comment"])))
    if lyrics:
        frames.append(_frame("USLT", b"\x01" + lang + _u16("") + b"\x00\x00" + _u16(lyrics)))
    pic = picture_info(cover)
    if pic:
        data, mime, _, _ = pic
        frames.append(_frame("APIC", b"\x00" + mime.encode("ascii") + b"\x00" + b"\x03" + b"\x00" + data))
    body = b"".join(frames) + b"\x00" * padding
    return b"ID3\x03\x00\x00" + _syncsafe(len(body)) + body


def _id3_len(head: bytes) -> int:
    """Length of an ID3v2 tag at the start of `head` (0 if none)."""
    if len(head) >= 10 and head[:3] == b"ID3" and all(b < 0x80 for b in head[6:10]):
        size = (head[6] << 21) | (head[7] << 14) | (head[8] << 7) | head[9]
        return 10 + size + (10 if head[5] & 0x10 else 0)
    return 0


def _replace_file(path: Path, head: bytes, src_offset: int) -> None:
    """Writes head + path[src_offset:] atomically next to path."""
    fd, tmp = tempfile.mkstemp(prefix=".tag_", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as out, open(path, "rb") as src:
            out.write(head)
            src.seek(src_offset)
            shutil.copyfileobj(src, out, 1 << 20)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def embed_mp3(path: str | Path, fields: dict, lyrics: str = "", cover: str | Path | None = None) -> Path:
    path = Path(path)
    with open(path, "rb") as f:
        old = _id3_len(f.read(10))
    _replace_file(path, id3v23(fields, lyrics, cover), old)
    return path


# ── WAV ──────────────────────────────────────────────────────

INFO_KEYS = (("title", "INAM"), ("artist", "IART"), ("album", "IPRD"), ("genre", "IGNR"), ("date", "ICRD"),
             ("comment", "ICMT"), ("copyright", "ICOP"), ("encoder", "ISFT"))


def _chunk(cid: bytes, data: bytes) -> bytes:
    return cid + struct.pack("<I", len(data)) + data + (b"\x00" if len(data) % 2 else b"")


def info_chunk(fields: dict) -> bytes:
    subs = []
    for key, cid in INFO_KEYS:
        v = fields.get(key) or (fields.get("year") if key == "date" else "")
        if v:
            subs.append(_chunk(cid.encode("ascii"), v.encode("utf-8") + b"\x00"))
    if fields.get("track"):
        subs.append(_chunk(b"ITRK", fields["track"].split("/")[0].encode("ascii") + b"\x00"))
    return _chunk(b"LIST", b"INFO" + b"".join(subs))


def embed_wav(path: str | Path, fields: dict, lyrics: str = "", cover: str | Path | None = None) -> Path:
    """Drops existing LIST/INFO and id3 chunks, then appends new ones and fixes the RIFF size."""
    path = Path(path)
    keep: list[tuple[int, int]] = []                   # (offset, total length) of chunks to keep
    with open(path, "rb") as f:
        head = f.read(12)
        if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            raise ValueError(f"not a RIFF/WAVE file: {path.name}")
        end = os.path.getsize(path)
        pos = 12
        while pos + 8 <= end:
            f.seek(pos)
            cid, size = struct.unpack("<4sI", f.read(8))
            total = 8 + size + (size & 1)
            drop = cid in (b"id3 ", b"ID3 ") or (cid == b"LIST" and f.read(4) == b"INFO")
            if not drop:
                keep.append((pos, min(total, end - pos)))
            pos += total
    extra = info_chunk(fields) + _chunk(b"id3 ", id3v23(fields, lyrics, cover))
    body_len = 4 + sum(n for _, n in keep) + len(extra)
    if body_len >= 1 << 32:
        raise ValueError("WAV is larger than 4 GB; tags not written")
    fd, tmp = tempfile.mkstemp(prefix=".tag_", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as out, open(path, "rb") as src:
            out.write(b"RIFF" + struct.pack("<I", body_len) + b"WAVE")
            for off, n in keep:
                src.seek(off)
                left = n
                while left:
                    buf = src.read(min(left, 1 << 20))
                    if not buf:
                        break
                    out.write(buf)
                    left -= len(buf)
            out.write(extra)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


# ── FLAC ─────────────────────────────────────────────────────

VORBIS_KEYS = (("title", "TITLE"), ("artist", "ARTIST"), ("album", "ALBUM"), ("album_artist", "ALBUMARTIST"),
               ("genre", "GENRE"), ("date", "DATE"), ("composer", "COMPOSER"), ("lyricist", "LYRICIST"),
               ("producer", "PRODUCER"), ("label", "LABEL"), ("copyright", "COPYRIGHT"), ("isrc", "ISRC"),
               ("upc", "BARCODE"), ("language", "LANGUAGE"), ("explicit", "ITUNESADVISORY"),
               ("comment", "COMMENT"))


def vorbis_comment(fields: dict, lyrics: str = "") -> bytes:
    items = []
    for key, name in VORBIS_KEYS:
        v = fields.get(key) or (fields.get("year") if key == "date" else "")
        if v:
            items.append(f"{name}={v}")
    if fields.get("track"):
        n, _, tot = fields["track"].partition("/")
        items += [f"TRACKNUMBER={n}"] + ([f"TRACKTOTAL={tot}"] if tot else [])
    if lyrics:
        items.append(f"LYRICS={lyrics}")
    vendor = (fields.get("encoder") or "AI Music Studio").encode("utf-8")
    out = struct.pack("<I", len(vendor)) + vendor + struct.pack("<I", len(items))
    for it in items:
        b = it.encode("utf-8")
        out += struct.pack("<I", len(b)) + b
    return out


def flac_picture(cover: str | Path | None) -> bytes | None:
    pic = picture_info(cover)
    if not pic:
        return None
    data, mime, w, h = pic
    m = mime.encode("ascii")
    return (struct.pack(">II", 3, len(m)) + m + struct.pack(">I", 0)
            + struct.pack(">IIIII", w, h, 24, 0, len(data)) + data)


def embed_flac(path: str | Path, fields: dict, lyrics: str = "", cover: str | Path | None = None) -> Path:
    """Rewrites the metadata blocks: STREAMINFO and other blocks are kept; VORBIS_COMMENT, PICTURE
    and PADDING are replaced."""
    path = Path(path)
    blocks: list[tuple[int, bytes]] = []
    with open(path, "rb") as f:
        if f.read(4) != b"fLaC":
            raise ValueError(f"not a FLAC file: {path.name}")
        last = False
        while not last:
            hdr = f.read(4)
            if len(hdr) < 4:
                raise ValueError("truncated FLAC metadata")
            last = bool(hdr[0] & 0x80)
            btype = hdr[0] & 0x7F
            size = int.from_bytes(hdr[1:4], "big")
            data = f.read(size)
            if btype not in (1, 4, 6):
                blocks.append((btype, data))
        audio_at = f.tell()
    blocks.append((4, vorbis_comment(fields, lyrics)))
    pic = flac_picture(cover)
    if pic:
        blocks.append((6, pic))
    blocks.append((1, b"\x00" * 1024))
    head = b"fLaC"
    for i, (btype, data) in enumerate(blocks):
        if len(data) >= 1 << 24:
            raise ValueError("FLAC metadata block too large (cover over 16 MB?)")
        flag = 0x80 if i == len(blocks) - 1 else 0
        head += bytes([flag | btype]) + len(data).to_bytes(3, "big") + data
    _replace_file(path, head, audio_at)
    return path


# ── ALAC (via ffmpeg) ────────────────────────────────────────

def ffmpeg_metadata(fields: dict, lyrics: str = "") -> dict:
    """Keys the ffmpeg MP4/M4A muxer turns into iTunes atoms."""
    m = {"title": fields.get("title"), "artist": fields.get("artist"), "album_artist": fields.get("album_artist"),
         "album": fields.get("album"), "genre": fields.get("genre"),
         "date": fields.get("date") or fields.get("year"), "composer": fields.get("composer"),
         "copyright": fields.get("copyright"), "comment": fields.get("comment"), "track": fields.get("track"),
         "lyrics": lyrics}
    return {k: v for k, v in m.items() if v}


def embed(path: str | Path, fmt: str, fields: dict, lyrics: str = "", cover: str | Path | None = None) -> Path:
    fmt = fmt.lower()
    if fmt == "wav":
        return embed_wav(path, fields, lyrics, cover)
    if fmt == "flac":
        return embed_flac(path, fields, lyrics, cover)
    if fmt == "mp3":
        return embed_mp3(path, fields, lyrics, cover)
    raise ValueError(f"tags for {fmt} are written by ffmpeg")
