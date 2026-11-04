"""1.2.2: distributor package format (like Export) with tags, cover and lyrics inside the audio file."""
from __future__ import annotations

import json
import shutil
import struct
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from studio import tags
from studio.publish import package, pipeline, release

SR = 48000
LYRICS = "[Verse]\nНеоновые реки\nCity lights\n\n[Chorus]\nNight drive"
META = {"genre": "synthpop", "language": "en / ru", "release_date": "2026-12-01", "composer": "Андрей",
        "lyricist": "Andrei", "producer": "AMS", "label": "Night Label", "copyright": "2026 Andrei",
        "isrc": "us-s1z-26-00001", "upc": "123456789012", "explicit": True}
HAS_FFMPEG = shutil.which("ffmpeg") is not None


def tone(seconds=35.0, sr=SR):
    t = np.arange(int(sr * seconds)) / sr
    x = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    return np.vstack([x, 0.8 * x])


@pytest.fixture
def made_release(tmp_path):
    src = tmp_path / "mix.wav"
    sf.write(src, tone().T, SR, subtype="FLOAT")
    rel = release.create(tmp_path, src, "Night Drive", "Andrei", LYRICS, dict(META))
    rel = pipeline.run_step(tmp_path, rel, "cover", {"backend": "builtin", "seed": 3}, {})
    assert rel.cover and Path(rel.cover).exists()
    return tmp_path, rel


def test_options_defaults_and_limits():
    assert package.options(None) == {"format": "wav", "sample_rate": 44100, "bit_depth": 24, "mp3_bitrate": 320,
                                     "dither": "tpdf", "embed_cover": True, "embed_lyrics": True}
    assert package.options({"format": "flac", "bit_depth": 32})["bit_depth"] == 24
    assert package.options({"format": "alac", "bit_depth": 32})["bit_depth"] == 24
    m = package.options({"format": "mp3", "sample_rate": 96000, "mp3_bitrate": 999})
    assert m["sample_rate"] == 48000 and m["mp3_bitrate"] == 320
    assert package.options({"format": "ogg", "sample_rate": 12345})["format"] == "wav"
    assert package.options({"sample_rate": "96000.0", "bit_depth": 16.0})["sample_rate"] == 96000
    assert package.describe(package.options({"format": "wav", "bit_depth": 32})) == "WAV 44.1 kHz / 32-bit float"


def test_lang3_and_clean_lyrics():
    assert tags.lang3("en / ru") == "eng"
    assert tags.lang3("Русский") == "rus"
    assert tags.lang3("ru-RU") == "rus"
    assert tags.lang3("") == ""
    assert tags.clean_lyrics(LYRICS) == "Неоновые реки\nCity lights\n\nNight drive"
    assert tags.clean_lyrics("", "[00:01.00]Hello\n[00:02.00]World\n") == "Hello\nWorld"
    f = tags.tag_fields(META, "T", "A", "Made with AI")
    assert f["isrc"] == "USS1Z2600001" and f["year"] == "2026" and f["album"] == "T" and f["explicit"] == "1"


def _wav_chunks(path: Path) -> dict:
    data = path.read_bytes()
    assert data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    assert struct.unpack("<I", data[4:8])[0] == len(data) - 8
    out, i = {}, 12
    while i + 8 <= len(data):
        cid, size = data[i:i + 4], struct.unpack("<I", data[i + 4:i + 8])[0]
        out[cid] = data[i + 8:i + 8 + size]
        i += 8 + size + (size & 1)
    return out


def test_wav_default_has_info_and_id3(made_release):
    root, rel = made_release
    rel = pipeline.run_step(root, rel, "package", {}, {})
    pk = rel.meta["package"]
    path = Path(pk["audio"])
    assert path.suffix == ".wav" and pk["wav"] == pk["audio"] and pk["format"] == "wav"
    info = sf.info(path)
    assert info.samplerate == 44100 and info.subtype == "PCM_24"
    ch = _wav_chunks(path)
    assert b"LIST" in ch and ch[b"LIST"].startswith(b"INFO") and b"Night Drive" in ch[b"LIST"]
    assert b"id3 " in ch and ch[b"id3 "].startswith(b"ID3")
    for k in ("title", "artist", "isrc", "lyrics", "cover"):
        assert k in pk["embedded"]
    folder = Path(pk["folder"])
    assert (folder / "lyrics.txt").read_text(encoding="utf-8").startswith("Неоновые реки")
    md = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    assert md["format"] == "wav" and md["file"] == path.name and md["embedded_tags"] == pk["embedded"]
    checks = {c["check"]: c for c in pk["checks"]}
    assert checks["format"]["ok"] and checks["tags"]["ok"]
    assert rel.meta["package_options"]["format"] == "wav"


def test_flac_tags_and_publish_reuses_options(made_release):
    root, rel = made_release
    rel = pipeline.run_step(root, rel, "package", {"format": "flac", "sample_rate": 48000, "bit_depth": 16}, {})
    pk = rel.meta["package"]
    path = Path(pk["audio"])
    data = path.read_bytes()
    assert path.suffix == ".flac" and data[:4] == b"fLaC"
    info = sf.info(path)
    assert info.samplerate == 48000 and info.subtype == "PCM_16"
    assert "TITLE=Night Drive".encode() in data and "COMPOSER=Андрей".encode() in data
    assert b"LYRICS=" in data and b"ISRC=USS1Z2600001" in data
    saved = release.Release.load(root, rel.id)
    assert saved.meta["package_options"]["format"] == "flac"
    # the publish queue ("package" service) rebuilds with the same options when none are given
    rel2 = pipeline.run_step(root, saved, "package", {}, {})
    assert Path(rel2.meta["package"]["audio"]).suffix == ".flac"
    assert sf.info(rel2.meta["package"]["audio"]).subtype == "PCM_16"


def test_embed_switches_off(made_release):
    root, rel = made_release
    rel = pipeline.run_step(root, rel, "package", {"format": "flac", "embed_cover": False, "embed_lyrics": False}, {})
    pk = rel.meta["package"]
    data = Path(pk["audio"]).read_bytes()
    assert b"LYRICS=" not in data and "cover" not in pk["embedded"] and "lyrics" not in pk["embedded"]
    assert Path(pk["folder"], "lyrics.txt").exists()             # the side files stay


def test_validate_format_warnings_and_old_signature():
    a = np.zeros((2, SR * 40), np.float32)
    old = {c["check"]: c for c in package.validate(a, SR, None, {"title": "t", "artist": "a", "ai": {}})}
    assert not old["cover_size"]["ok"]
    mp3 = {c["check"]: c for c in package.validate(a, 44100, None, {"title": "t", "artist": "a", "ai": {}},
                                                    package.options({"format": "mp3"}), [])}
    assert mp3["format"]["level"] == "warning" and not mp3["format"]["ok"]
    f32 = {c["check"]: c for c in package.validate(a, 44100, None, {"title": "t", "artist": "a", "ai": {}},
                                                    package.options({"bit_depth": 32}), [])}
    assert f32["format"]["level"] == "warning"


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg is not installed")
def test_mp3_and_alac(made_release):
    root, rel = made_release
    rel = pipeline.run_step(root, rel, "package", {"format": "mp3", "mp3_bitrate": 256}, {})
    pk = rel.meta["package"]
    data = Path(pk["audio"]).read_bytes()
    assert pk["audio"].endswith(".mp3") and data[:3] == b"ID3" and data[3] == 3
    assert b"USLT" in data and b"APIC" in data and b"TSRC" in data
    assert data.count(b"ID3\x03") == 1
    rel = pipeline.run_step(root, rel, "package", {"format": "alac", "bit_depth": 24}, {})
    pk = rel.meta["package"]
    assert pk["audio"].endswith(".m4a") and Path(pk["audio"]).stat().st_size > 10000
    assert "cover" in pk["embedded"]


def test_tags_read_back_with_mutagen(made_release):
    mutagen = pytest.importorskip("mutagen")
    from mutagen.flac import FLAC
    from mutagen.id3 import ID3
    from mutagen.wave import WAVE
    root, rel = made_release
    rel = pipeline.run_step(root, rel, "package", {"format": "flac"}, {})
    fl = FLAC(rel.meta["package"]["audio"])
    assert fl["title"] == ["Night Drive"] and fl["composer"] == ["Андрей"] and fl["language"] == ["eng"]
    assert fl.pictures and fl.pictures[0].type == 3 and fl.pictures[0].width >= 3000
    assert "Night drive" in fl["lyrics"][0]
    rel = pipeline.run_step(root, rel, "package", {"format": "wav"}, {})
    wv = WAVE(rel.meta["package"]["audio"])
    assert str(wv.tags["TIT2"]) == "Night Drive" and wv.tags.getall("APIC") and wv.tags.getall("USLT")
    assert mutagen.version >= (1, 47)
    if HAS_FFMPEG:
        rel = pipeline.run_step(root, rel, "package", {"format": "mp3"}, {})
        id3 = ID3(rel.meta["package"]["audio"])
        assert str(id3["TSRC"]) == "USS1Z2600001" and id3.getall("APIC")[0].type == 3
