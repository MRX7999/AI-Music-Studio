"""1.2.1 fixes: ACE-Step "N/A" metadata, tools installed in pyenv/venv, Z-Image model download."""
from __future__ import annotations

import json
import os
import stat
import struct
import subprocess
import sys
import textwrap
import time
import zlib
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from studio import cover, library, lyrics, tools
from studio.generators.acestep import AceStepGenerator, _seed_of
from studio.generators.base import meta_number, meta_text

SR = 44100
HF_SCRIPT = Path(tools.SCRIPTS_DIR) / "hf_download.py"


def fake_cli(path: Path, body: str, interpreter: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!{interpreter or sys.executable}\n" + textwrap.dedent(body), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.fixture(autouse=True)
def clean_tool_config():
    old = (dict(tools.CONFIG.overrides), dict(tools.CONFIG.backends))
    yield
    tools.CONFIG.overrides, tools.CONFIG.backends = old


# ------------------------------------------------------------------ bug 1: ACE-Step cover metadata

def test_meta_number_and_text():
    assert meta_number("N/A") is None and meta_number("") is None and meta_number(None) is None
    assert meta_number(True) is None and meta_number(0) is None and meta_number(float("nan")) is None
    assert meta_number(120) == 120.0 and meta_number("183.4") == 183.4 and meta_number("120 bpm") == 120.0
    assert meta_number("95,5") == 95.5
    assert meta_text("N/A") is None and meta_text(" none ") is None and meta_text("C major") == "C major"


def test_seed_of_batch_string():
    assert _seed_of("2846061422,3163210317", 0) == 2846061422
    assert _seed_of("2846061422,3163210317", 1) == 3163210317
    assert _seed_of("2846061422,3163210317", 7) == 2846061422
    assert _seed_of(5, 3) == 5 and _seed_of(None, 0) is None and _seed_of("", 0) is None


def test_acestep_cover_with_na_metas(tmp_path, monkeypatch):
    """ACE-Step cover/repaint runs without the LM and reports bpm/duration/key as "N/A" (real 1.5 output)."""
    import studio.generators.acestep as mod

    src = tmp_path / "src.wav"
    sf.write(src, np.zeros((SR * 2, 2), np.float32), SR)
    g = AceStepGenerator(base_url="http://127.0.0.1:1")
    na = {"bpm": "N/A", "duration": "N/A", "genres": "N/A", "keyscale": "N/A", "timesignature": "N/A"}
    res = [{"file": f"/v1/audio?path=%2Ftmp%2F{i}.flac", "status": 1, "prompt": "jazz", "lyrics": "",
            "metas": na, "seed_value": "2846061422,3163210317"} for i in range(2)]
    monkeypatch.setattr(g, "is_available", lambda: (True, "ok"))
    monkeypatch.setattr(g, "_post_form", lambda path, payload, files: {"data": {"task_id": "t9"}})
    monkeypatch.setattr(g, "_post", lambda path, body: {"data": [{"task_id": "t9", "status": 1,
                                                                    "result": json.dumps(res)}]})
    monkeypatch.setattr(mod, "download",
                        lambda url, dst, headers=None, cancel=None: sf.write(str(dst), np.zeros((SR * 3, 2)), SR,
                                                                             format="FLAC"))
    tracks = g.edit(src, "cover", tmp_path / "generated" / "edits", title="Song", prompt="jazz", strength=0.6)
    assert len(tracks) == 2
    m0, m1 = tracks[0].meta, tracks[1].meta
    assert m0["duration"] is None and m0["bpm"] is None and m0["key"] is None and m0["time_signature"] is None
    assert m0["seed"] == 2846061422 and m1["seed"] == 3163210317
    e = library.track_entry(tracks[0])
    assert e["duration"] == pytest.approx(3.0, abs=0.01)
    songs = library.scan(tmp_path)["songs"]
    assert len(songs) == 2 and all(s["duration"] == pytest.approx(3.0, abs=0.01) for s in songs)


def test_library_shows_sidecars_written_by_120(tmp_path):
    """Covers made with 1.2.0 have "N/A" in their sidecars and were hidden from the library."""
    folder = tmp_path / "generated" / "edits"
    folder.mkdir(parents=True)
    audio = folder / "Song — кавер — вариант 1.flac"
    sf.write(audio, np.zeros((SR * 4, 2)), SR, format="FLAC")
    side = audio.with_suffix(".json")
    side.write_text(json.dumps({"path": audio.name, "title": audio.stem, "engine": "acestep",
                                "meta": {"bpm": "N/A", "key": "N/A", "duration": "N/A",
                                         "seed": "2846061422,3163210317", "task_type": "cover"}},
                               ensure_ascii=False), encoding="utf-8")
    songs = library.scan(tmp_path)["songs"]
    assert len(songs) == 1
    s = songs[0]
    assert s["duration"] == pytest.approx(4.0, abs=0.01)
    assert s["meta"]["bpm"] is None and s["meta"]["key"] is None
    assert json.loads(side.read_text(encoding="utf-8"))["meta"]["duration"] == "N/A"   # files are not rewritten


# ------------------------------------------------------------------ bug 2: tools in pyenv / venv

def test_finds_whisper_in_pyenv_version(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", str(home / ".pyenv" / "shims") + os.pathsep + "/usr/bin" + os.pathsep + "/bin")
    good = fake_cli(home / ".pyenv/versions/3.11.6/bin/whisper", "print('ok')\n")
    # a newer version whose interpreter is gone (moved/deleted venv) must be skipped
    fake_cli(home / ".pyenv/versions/3.12.1/bin/whisper", "print('dead')\n", interpreter="/nonexistent/python3.12")
    # pyenv shims only work for the active version: never picked
    fake_cli(home / ".pyenv/shims/whisper", "print('shim')\n")
    dirs = [str(d) for d in tools.search_dirs()]
    assert str(home / ".pyenv/versions/3.12.1/bin") in dirs
    assert dirs.index(str(home / ".pyenv/versions/3.12.1/bin")) < dirs.index(str(home / ".pyenv/versions/3.11.6/bin"))
    assert str(Path(sys.executable).parent) in dirs
    assert tools.find_executable("whisper") == str(good)


def test_finds_tool_in_venv_and_conda(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", "/usr/bin" + os.pathsep + "/bin")
    v = fake_cli(home / ".virtualenvs/music/bin/audiosr", "print('ok')\n")
    assert tools.find_executable("audiosr") == str(v)
    v.unlink()
    c = fake_cli(home / "miniforge3/envs/sr/bin/audiosr", "print('ok')\n")
    assert tools.find_executable("audiosr") == str(c)


def test_chosen_tool_missing_falls_back_to_installed_one(tmp_path):
    exe = fake_cli(tmp_path / "whisper", "")
    tools.CONFIG.update({"backends": {"lyrics": "mlx_whisper"},
                         "tools": {"mlx_whisper": {"path": str(tmp_path / "nope")}, "whisper": {"path": str(exe)}}})
    assert tools.resolve_backend("lyrics") == "whisper"
    d = tools.doctor()
    f = d["features"]["lyrics"]
    assert f["backend"] == "whisper" and f["wanted"] == "mlx_whisper" and f["fallback"] is True
    assert d["tools"]["whisper"]["model"]["name"]
    assert isinstance(d["search_dirs"], list) and str(Path(sys.executable).parent) in d["search_dirs"]
    tools.CONFIG.update({"tools": {"whisper": {"path": str(tmp_path / "nope2")}}})
    assert tools.resolve_backend("lyrics") == "missing:mlx_whisper"
    assert tools.doctor()["features"]["lyrics"]["fallback"] is False      # missing is not a fallback
    tools.CONFIG.update({"tools": {"whisper": {"path": str(exe), "enabled": False}}})
    assert tools.resolve_backend("lyrics") == "missing:mlx_whisper"   # disabled tools are not used


def test_whisper_uses_already_downloaded_model(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert lyrics.torch_model() == ("turbo", False)
    (tmp_path / "whisper").mkdir()
    (tmp_path / "whisper" / "medium.pt").write_bytes(b"x")
    assert lyrics.torch_model() == ("medium", True)
    (tmp_path / "whisper" / "large-v3.pt").write_bytes(b"x")
    assert lyrics.torch_model() == ("large-v3", True)
    (tmp_path / "whisper" / "large-v3-turbo.pt").write_bytes(b"x")
    assert lyrics.torch_model() == ("turbo", True)


def test_whisper_cli_gets_cached_model_and_clean_language(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    (tmp_path / "cache" / "whisper").mkdir(parents=True)
    (tmp_path / "cache" / "whisper" / "medium.pt").write_bytes(b"x")
    p = tmp_path / "song.wav"
    sf.write(p, np.zeros((SR * 3, 2), np.float32), SR)
    exe = fake_cli(tmp_path / "whisper", """
        import json, sys
        a = sys.argv[1:]
        out = a[a.index("--output_dir") + 1]
        assert a[a.index("--model") + 1] == "medium", a      # the checkpoint already on disk
        assert "--language" not in a, a                       # "en / ru" → let Whisper detect
        json.dump({"language": "ru", "segments": [{"text": "la", "start": 0.5, "end": 1.0,
                   "words": [{"word": " la", "start": 0.5, "end": 1.0}]}]}, open(out + "/song.json", "w"))
    """)
    tools.CONFIG.update({"tools": {"whisper": {"path": str(exe)}, "mlx_whisper": {"enabled": False}}})
    seen = []
    res = lyrics.transcribe(p, language="en / ru", progress=lambda f, m: seen.append(m))
    assert res["backend"] == "whisper" and res["model"] == "medium"
    assert any("medium" in m for m in seen)
    argv = tools.build_argv("whisper", {"input": "x", "outdir": "o", "name": "n", "model": "m", "model_torch": "medium"})
    assert "medium" in argv
    assert lyrics.whisper_language("en / ru") == "" and lyrics.whisper_language("RU") == "ru"
    assert lyrics.whisper_language("") == "" and lyrics.whisper_language("Russian") == "russian"


def test_run_passes_exact_progress_lines(tmp_path):
    exe = fake_cli(tmp_path / "t", """
        print("@progress 41.5 Z-Image Turbo: 2.43 of 5.91 GB", flush=True)
        print("@progress oops", flush=True)
        print("normal 50%", flush=True)
    """)
    seen = []
    out = tools.run([str(exe)], progress=lambda f, m: seen.append((f, m)), lo=0.0, hi=0.5, label="D")
    assert seen == [(pytest.approx(0.2075), "Z-Image Turbo: 2.43 of 5.91 GB"), (pytest.approx(0.25), "D 50%")]
    assert "@progress" not in out and "normal 50%" in out


def test_run_env_extra(tmp_path):
    exe = fake_cli(tmp_path / "t", "import os; print('OFF=' + os.environ.get('HF_HUB_OFFLINE', '-'))\n")
    assert "OFF=1" in tools.run([str(exe)], env_extra={"HF_HUB_OFFLINE": "1"})


# ------------------------------------------------------------------ bug 3: Z-Image model in the HF cache

REPO = cover.MFLUX_MODEL
FILES = {  # file → (content, LFS)
    "text_encoder/0.safetensors": (b"T0" * 3000, True), "text_encoder/1.safetensors": (b"T1" * 500, True),
    "transformer/0.safetensors": (b"X0" * 4000, True), "transformer/1.safetensors": (b"X1" * 2000, True),
    "vae/0.safetensors": (b"V0" * 700, True),
    "text_encoder/model.safetensors.index.json":
        (json.dumps({"weight_map": {"a": "0.safetensors", "b": "1.safetensors"}}).encode(), False),
    "transformer/model.safetensors.index.json":
        (json.dumps({"weight_map": {"a": "0.safetensors", "b": "1.safetensors"}}).encode(), False),
    "vae/model.safetensors.index.json": (json.dumps({"weight_map": {"a": "0.safetensors"}}).encode(), False),
    "tokenizer/tokenizer.json": (b"{}" * 100, True), "tokenizer/tokenizer_config.json": (b"{}", False),
    "README.md": (b"# z", False), "preview.png": (b"png", False),
}


def _blob(name: str) -> str:
    import hashlib
    data, lfs = FILES[name]
    return hashlib.sha256(data).hexdigest() if lfs else hashlib.sha1(data).hexdigest()


def _put(cache: Path, name: str, commit: str = "c0ffee"):
    root = cache / ("models--" + REPO.replace("/", "--"))
    blob = root / "blobs" / _blob(name)
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(FILES[name][0])
    link = root / "snapshots" / commit / name
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(os.path.relpath(blob, link.parent))
    (root / "refs").mkdir(exist_ok=True)
    (root / "refs" / "main").write_text(commit)


def _stub_hub(dirpath: Path, cache: Path, mode: str = "ok") -> Path:
    """A minimal huggingface_hub with the calls hf_download.py makes (the real one is in mflux's env)."""
    pkg = dirpath / "huggingface_hub"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "constants.py").write_text(f"HF_HUB_CACHE = {str(cache)!r}\n")
    files = {k: [v[0].decode("latin-1"), v[1]] for k, v in FILES.items()}
    (pkg / "__init__.py").write_text(textwrap.dedent(f"""
        import hashlib, os, time
        from pathlib import Path
        FILES = {files!r}
        MODE = {mode!r}
        CACHE = Path({str(cache)!r})
        REPO = {REPO!r}

        class ConnectError(Exception):
            pass

        def _blob(name):
            data, lfs = FILES[name]
            data = data.encode("latin-1")
            return hashlib.sha256(data).hexdigest() if lfs else hashlib.sha1(data).hexdigest()

        class _S:
            def __init__(self, name):
                data, lfs = FILES[name]
                self.rfilename, self.size = name, len(data.encode("latin-1"))
                self.lfs = {{"sha256": _blob(name), "size": self.size}} if lfs else None
                self.blob_id = hashlib.sha1(name.encode()).hexdigest() if lfs else _blob(name)

        class _Info:
            sha = "c0ffee"
            siblings = [_S(n) for n in FILES]

        class HfApi:
            def model_info(self, repo, revision=None, files_metadata=False):
                assert repo == REPO and files_metadata
                if MODE == "offline":
                    raise ConnectError("[Errno 8] nodename nor servname provided, or not known")
                return _Info()

        def snapshot_download(repo_id, revision=None, ignore_patterns=None):
            assert os.environ.get("HF_HUB_DISABLE_PROGRESS_BARS") == "1"
            root = CACHE / ("models--" + repo_id.replace("/", "--"))
            snap = root / "snapshots" / "c0ffee"
            for name in FILES:
                if any(Path(name).match(p) for p in ignore_patterns or []):
                    continue
                blob = root / "blobs" / _blob(name)
                blob.parent.mkdir(parents=True, exist_ok=True)
                if not blob.exists():
                    tmp = blob.with_name(blob.name + ".1234abcd.incomplete")
                    tmp.write_bytes(FILES[name][0].encode("latin-1"))
                    time.sleep(0.4)
                    if MODE == "drop" and name.startswith("transformer"):
                        raise ConnectError("error sending request: connection reset")
                    tmp.rename(blob)
                link = snap / name
                link.parent.mkdir(parents=True, exist_ok=True)
                if not link.exists():
                    link.symlink_to(os.path.relpath(blob, link.parent))
            (root / "refs").mkdir(exist_ok=True)
            (root / "refs" / "main").write_text("c0ffee")
            return str(snap)
    """))
    return dirpath


def test_model_status_finds_missing_shards_and_stale_parts(tmp_path, monkeypatch):
    cache = tmp_path / "hub"
    monkeypatch.setenv("HF_HUB_CACHE", str(cache))
    assert cover.hf_cache_dir() == cache
    st = cover.model_status()
    assert not st["complete"] and st["missing"] == ["(not downloaded)"]
    for n in ("text_encoder/1.safetensors", "vae/0.safetensors", "text_encoder/model.safetensors.index.json",
              "transformer/model.safetensors.index.json", "vae/model.safetensors.index.json",
              "tokenizer/tokenizer.json", "tokenizer/tokenizer_config.json"):
        _put(cache, n)
    blobs = cache / ("models--" + REPO.replace("/", "--")) / "blobs"
    (blobs / (_blob("transformer/0.safetensors") + ".4f3c2105.incomplete")).write_bytes(b"x" * 1000)
    st = cover.model_status()
    assert not st["complete"]
    assert st["missing"] == ["transformer/0.safetensors", "transformer/1.safetensors", "text_encoder/0.safetensors"]
    assert st["stale_bytes"] == 1000 and st["bytes"] > 0
    for n in ("text_encoder/0.safetensors", "transformer/0.safetensors", "transformer/1.safetensors"):
        _put(cache, n)
    st = cover.model_status()
    assert st["complete"] and st["missing"] == []


def test_model_status_dangling_symlink_is_missing(tmp_path, monkeypatch):
    cache = tmp_path / "hub"
    monkeypatch.setenv("HF_HUB_CACHE", str(cache))
    for n in FILES:
        _put(cache, n)
    assert cover.model_status()["complete"]
    blob = cache / ("models--" + REPO.replace("/", "--")) / "blobs" / _blob("transformer/1.safetensors")
    blob.unlink()
    assert cover.model_status()["missing"] == ["transformer/1.safetensors"]


def _run_hf(tmp_path, cache, mode="ok", *args):
    stub = _stub_hub(tmp_path / f"stub_{mode}", cache, mode)
    env = {**os.environ, "PYTHONPATH": str(stub), "HF_HUB_CACHE": str(cache), "AMS_HF_RETRY_WAIT": "0"}
    return subprocess.run([sys.executable, str(HF_SCRIPT), REPO, "--label", "Z-Image Turbo", *args],
                          capture_output=True, text=True, env=env, timeout=120)


def test_hf_download_cleans_stale_parts_and_reports_progress(tmp_path, monkeypatch):
    cache = tmp_path / "hub"
    _put(cache, "vae/0.safetensors")
    blobs = cache / ("models--" + REPO.replace("/", "--")) / "blobs"
    old = blobs / (_blob("transformer/0.safetensors") + ".9d840e17.incomplete")
    old.write_bytes(b"x" * 5000)
    os.utime(old, (time.time() - 3600, time.time() - 3600))
    fresh = blobs / (_blob("transformer/1.safetensors") + ".deadbeef.incomplete")   # another live download
    fresh.write_bytes(b"y" * 10)
    r = _run_hf(tmp_path, cache)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Removed unfinished files of earlier download attempts" in r.stdout
    assert not old.exists() and fresh.exists()
    prog = [ln for ln in r.stdout.splitlines() if ln.startswith("@progress ")]
    assert len(prog) >= 2 and " of " in prog[0] and prog[-1] == "@progress 100 Z-Image Turbo: downloaded"
    assert r.stdout.strip().splitlines()[-1].startswith("SNAPSHOT ")
    monkeypatch.setenv("HF_HUB_CACHE", str(cache))
    st = cover.model_status()
    assert st["complete"], st
    assert not (cache / ("models--" + REPO.replace("/", "--")) / "snapshots" / "c0ffee" / "preview.png").exists()


def test_hf_download_offline_and_dropped_connection(tmp_path):
    cache = tmp_path / "hub"
    r = _run_hf(tmp_path, cache, "offline")
    assert r.returncode == 2 and "ERROR no connection to huggingface.co" in r.stdout
    r = _run_hf(tmp_path, cache, "drop")
    assert r.returncode == 2 and "retrying" in r.stdout


def _png_bytes() -> bytes:
    raw = b"".join(b"\x00" + bytes([200, 40, 90]) * 16 for _ in range(16))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def test_cover_downloads_model_then_runs_mflux_offline(tmp_path, monkeypatch):
    cache = tmp_path / "hub"
    stub = _stub_hub(tmp_path / "stub", cache)
    monkeypatch.setenv("HF_HUB_CACHE", str(cache))
    monkeypatch.setenv("PYTHONPATH", str(stub))
    png = tmp_path / "img.png"
    png.write_bytes(_png_bytes())
    exe = fake_cli(tmp_path / "mflux-generate-z-image-turbo", f"""
        import os, shutil, sys
        a = sys.argv[1:]
        assert os.environ.get("HF_HUB_OFFLINE") == "1", "mflux must run offline once the model is complete"
        print("100%|##########| 9/9", flush=True)
        shutil.copy({str(png)!r}, a[a.index("--output") + 1])
    """)
    tools.CONFIG.update({"tools": {"mflux": {"path": str(exe)}}})
    seen = []
    res = cover.generate(tmp_path / "cover", "neon city", seed=3, backend="mflux", progress=lambda f, m: seen.append(m))
    from studio.publish.media import image_size
    assert res["backend"] == "mflux" and image_size(res["cover"]) == (3000, 3000)
    assert any("downloading the model once" in m for m in seen)
    assert any(m.startswith("Z-Image Turbo:") and " of " in m and " GB" in m for m in seen)
    assert cover.model_status()["complete"]
    # second cover: no download step at all
    seen.clear()
    cover.generate(tmp_path / "cover2", "neon city", seed=4, backend="mflux", progress=lambda f, m: seen.append(m))
    assert not any("downloading" in m for m in seen)


def test_cover_download_errors_are_plain(tmp_path, monkeypatch):
    cache = tmp_path / "hub"
    stub = _stub_hub(tmp_path / "stub", cache, "offline")
    monkeypatch.setenv("HF_HUB_CACHE", str(cache))
    monkeypatch.setenv("PYTHONPATH", str(stub))
    exe = fake_cli(tmp_path / "mflux-generate-z-image-turbo", "raise SystemExit(9)\n")
    tools.CONFIG.update({"tools": {"mflux": {"path": str(exe)}}})
    with pytest.raises(RuntimeError, match="no connection to huggingface.co"):
        cover.generate(tmp_path / "cover", "x", seed=1, backend="mflux")
    oom = cover._mflux_error("[METAL] Command buffer execution failed: Insufficient Memory (00000008)")
    assert "Not enough memory" in oom
    d = tools.doctor()
    assert d["tools"]["mflux"]["model"]["complete"] is False


def test_new_messages_have_russian():
    from studio.i18n import message
    assert message("Z-Image Turbo: downloading the model once (~5.6 GB)", "ru") == \
        "Z-Image Turbo: модель скачивается один раз (~5.6 ГБ)"
    assert message("Z-Image Turbo: 2.43 of 5.91 GB · 5.3 MB/s · ~11 min left", "ru") == \
        "Z-Image Turbo: 2.43 из 5.91 ГБ · 5.3 МБ/с · осталось ~11 мин"
    assert message("Z-Image Turbo: 0.30 of 5.91 GB", "ru") == "Z-Image Turbo: 0.30 из 5.91 ГБ"
    st = {"bytes": 0.31e9, "total_bytes": 5.91e9}
    offline = cover._download_error("python exited with code 2:\nERROR no connection to huggingface.co: ConnectError", st)
    assert offline.startswith("Z-Image Turbo download stopped: no connection to huggingface.co (0.3 GB of 5.9 GB")
    ru = message(offline, "ru")
    assert ru.startswith("Загрузка Z-Image Turbo остановлена: нет связи с huggingface.co (скачано 0.3 из 5.9 ГБ)")
    disk = cover._download_error("ERROR not enough disk space: 5.60 GB to download, 1.20 GB free", st)
    assert message(disk, "ru").startswith("Загрузка Z-Image Turbo остановлена: не хватает места на диске — нужно 5.60 ГБ")
    assert message(cover._mflux_error("Insufficient Memory"), "ru").startswith("Не хватает памяти для Z-Image Turbo")
    assert message("Whisper (OpenAI Whisper (PyTorch), turbo — first run downloads the model)", "ru") == \
        "Whisper (OpenAI Whisper (PyTorch), turbo — модель скачается при первом запуске)"
    assert message(offline, "en") == offline
