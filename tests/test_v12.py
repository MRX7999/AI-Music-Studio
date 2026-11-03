"""v1.2: external MLX/PyTorch tools, super-resolution, AI check, lyrics, cover, timeline edits,
releases and publishing. Every model is replaced by a tiny fake CLI, every network call by a mock."""
import json
import os
import stat
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from studio import cover, detect, editing, lyrics, refmaster, spectrum, superres, tools
from studio.loudness import integrated_lufs
from studio.generators.acestep import AceStepGenerator
from studio.generators.base import GenerationError
from studio.i18n import message
from studio.publish import package, pipeline, release, telegram, youtube

SR = 44100


def fake_cli(path: Path, body: str) -> Path:
    path.write_text(f"#!{sys.executable}\n" + textwrap.dedent(body), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def lowpassed_noise(seconds=3.0, cutoff=16000, sr=SR, seed=1):
    rng = np.random.default_rng(seed)
    n = int(seconds * sr)
    x = rng.standard_normal((2, n)) * 0.1
    X = np.fft.rfft(x, axis=1)
    f = np.fft.rfftfreq(n, 1 / sr)
    X[:, f > cutoff] = 0
    return np.fft.irfft(X, n, axis=1).astype(np.float32)


@pytest.fixture(autouse=True)
def clean_tool_config():
    old = (dict(tools.CONFIG.overrides), dict(tools.CONFIG.backends))
    yield
    tools.CONFIG.overrides, tools.CONFIG.backends = old


# ------------------------------------------------------------------ tools

def test_build_argv_keeps_spaces_and_drops_empty_flags(tmp_path):
    exe = fake_cli(tmp_path / "speech", "print('x')\n")
    tools.CONFIG.update({"tools": {"mflux": {"path": str(exe)}}})
    argv = tools.build_argv("mflux", {"model": "m", "prompt": "a \"quoted\" prompt; rm -rf /", "width": 1024,
                                      "height": 1024, "steps": 9, "seed": "", "output": "/tmp/out dir/c.png"})
    assert argv[0] == str(exe)
    assert "a \"quoted\" prompt; rm -rf /" in argv          # one argument, never a shell
    assert "/tmp/out dir/c.png" in argv
    assert "--seed" not in argv                              # empty value removes its flag


def test_custom_template_and_missing_tool(tmp_path):
    exe = fake_cli(tmp_path / "w", "")
    tools.CONFIG.update({"tools": {"whisper": {"path": str(exe), "template": "--in {input} --fixed"}}})
    assert tools.build_argv("whisper", {"input": "a b.wav"}) == [str(exe), "--in", "a b.wav", "--fixed"]
    tools.CONFIG.update({"tools": {"whisper": {"path": str(tmp_path / "nope")}}})
    with pytest.raises(tools.ToolMissing):
        tools.build_argv("whisper", {"input": "x"})


def test_run_reports_progress_and_hides_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_API_KEY", "super-secret")
    exe = fake_cli(tmp_path / "t", """
        import os, sys
        print("loading 10%", flush=True)
        print("step 75%", flush=True)
        print("KEY=" + os.environ.get("MY_API_KEY", "none"))
    """)
    seen = []
    out = tools.run([str(exe)], progress=lambda f, m: seen.append((round(f, 2), m)), label="T")
    assert "KEY=none" in out and "super-secret" not in out
    assert (0.75, "T 75%") in seen
    bad = fake_cli(tmp_path / "bad", "import sys; print('boom'); sys.exit(3)\n")
    with pytest.raises(RuntimeError, match="code 3"):
        tools.run([str(bad)])


def test_backend_resolution_and_doctor(tmp_path):
    exe = fake_cli(tmp_path / "whisper", "")
    tools.CONFIG.update({"tools": {"whisper": {"path": str(exe)}, "mlx_whisper": {"enabled": False}}})
    assert tools.resolve_backend("lyrics") == "whisper"
    tools.CONFIG.update({"backends": {"lyrics": "off"}})
    assert tools.resolve_backend("lyrics") == "off"
    tools.CONFIG.update({"backends": {"superres": "audiosr"},
                         "tools": {"audiosr": {"path": str(tmp_path / "missing")}, "flashsr": {"enabled": False}}})
    assert tools.resolve_backend("superres") == "missing:audiosr"
    d = tools.doctor()
    assert set(d["features"]) >= {"superres", "lyrics", "stems", "cover", "detect", "voice", "refmaster"}
    assert d["tools"]["whisper"]["installed"] and "uv tool install" in d["tools"]["whisper"]["install"]


# ------------------------------------------------------------------ spectrum / super-resolution

def test_cutoff_detection():
    a = lowpassed_noise(cutoff=16000)
    c = spectrum.detect_cutoff(a, SR)["cutoff_hz"]
    assert 15000 < c < 17500
    assert spectrum.needs_superres(c, 48000)
    full = lowpassed_noise(cutoff=30000)
    assert spectrum.detect_cutoff(full, SR)["cutoff_hz"] > 20000
    assert not spectrum.needs_superres(spectrum.detect_cutoff(full, SR)["cutoff_hz"], 44100)


def test_crossover_is_transparent():
    x = np.random.default_rng(3).standard_normal((1, 4800))
    np.testing.assert_allclose(superres.crossover(x, x, 48000, 12000), x, atol=1e-9)


def test_superres_with_fake_model_keeps_low_band(tmp_path):
    a = lowpassed_noise(cutoff=16000)
    src = tmp_path / "in.wav"
    sf.write(src, a.T, SR, subtype="FLOAT")
    # "model": returns the input plus full-band noise, like a generator inventing the top octave
    exe = fake_cli(tmp_path / "speech", """
        import sys, numpy as np, soundfile as sf
        args = sys.argv[1:]
        x, sr = sf.read(args[1], dtype="float32")
        y = x + np.random.default_rng(0).standard_normal(x.shape).astype("float32") * 0.02
        sf.write(args[args.index("--output") + 1], y, sr, subtype="FLOAT")
    """)
    tools.CONFIG.update({"tools": {"flashsr": {"path": str(exe)}}})
    rep = superres.upscale(src, tmp_path / "out.wav", 48000, backend="flashsr")
    assert not rep.get("skipped")
    assert rep["cutoff_after_hz"] > rep["cutoff_before_hz"] + 3000
    y, sr = sf.read(tmp_path / "out.wav", dtype="float64", always_2d=True)
    assert sr == 48000
    lo_in = superres.crossover(superres._resample(a.astype(np.float64), SR, 48000), np.zeros((2, y.shape[0])),
                               48000, 12000)
    lo_out = superres.crossover(y.T, np.zeros_like(y.T), 48000, 12000)
    err = np.sqrt(np.mean((lo_in - lo_out) ** 2)) / np.sqrt(np.mean(lo_in ** 2))
    assert err < 0.02                          # below the cutoff the original is preserved
    assert Path(rep["spectrogram_before"]).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_superres_builtin_extension(tmp_path):
    a = lowpassed_noise(seconds=4, cutoff=11000)          # like an MP3 / 22 kHz generation
    src = tmp_path / "in.wav"
    sf.write(src, a.T, SR, subtype="FLOAT")
    rep = superres.upscale(src, tmp_path / "out.wav", 48000, backend="builtin")
    assert rep["backend"] == "builtin" and not rep.get("skipped")
    assert rep["cutoff_after_hz"] > rep["cutoff_before_hz"] + 3000
    y, _ = sf.read(tmp_path / "out.wav", dtype="float64", always_2d=True)
    lo_in = superres.crossover(superres._resample(a.astype(np.float64), SR, 48000), np.zeros((2, y.shape[0])),
                               48000, 9000)
    lo_out = superres.crossover(y.T, np.zeros_like(y.T), 48000, 9000)
    err = np.sqrt(np.mean((lo_in - lo_out) ** 2)) / np.sqrt(np.mean(lo_in ** 2))
    assert err < 0.02
    # a missing model falls back to the same extension, with a note
    tools.CONFIG.update({"backends": {"superres": "audiosr"}, "tools": {"audiosr": {"path": str(tmp_path / "nope")}}})
    rep2 = superres.upscale(src, tmp_path / "out2.wav", 48000)
    assert rep2["backend"] == "builtin" and "not installed" in rep2["note"]


def _band_db(x, sr, lo, hi):
    from scipy.signal import welch
    f, p = welch(x.mean(axis=0), sr, nperseg=4096)
    m = (f >= lo) & (f <= hi)
    return 10 * np.log10(np.mean(p[m]))


def test_refmaster_builtin_moves_toward_reference(tmp_path):
    from scipy.signal import butter, sosfilt
    rng = np.random.default_rng(3)
    ref = rng.standard_normal((2, SR * 4)) * 0.2                       # bright and loud
    dark = sosfilt(butter(2, 2000 / (SR / 2), "low", output="sos"), rng.standard_normal((2, SR * 4))) * 0.05
    sf.write(tmp_path / "ref.wav", ref.T, SR, subtype="FLOAT")
    sf.write(tmp_path / "mix.wav", dark.T, SR, subtype="FLOAT")
    rep = refmaster.master(tmp_path / "mix.wav", tmp_path / "ref.wav", tmp_path / "out.wav", backend="builtin",
                           use_limiter=True, max_db=12)
    assert rep["backend"] == "builtin"
    y, _ = sf.read(rep["output"], dtype="float64", always_2d=True)
    y = y.T
    tilt = lambda x: _band_db(x, SR, 6000, 10000) - _band_db(x, SR, 300, 1000)   # noqa: E731
    assert tilt(y) > tilt(dark) + 8                                    # brighter, toward the reference
    assert abs(integrated_lufs(y, SR) - integrated_lufs(ref, SR)) < 1.5
    assert np.max(np.abs(y)) <= 10 ** (-1 / 20) + 1e-6
    # strength 0 keeps the tone, only loudness changes
    rep0 = refmaster.master(tmp_path / "mix.wav", tmp_path / "ref.wav", tmp_path / "o0.wav", backend="builtin",
                            strength=0.0)
    y0, _ = sf.read(rep0["output"], dtype="float64", always_2d=True)
    assert abs(tilt(y0.T) - tilt(dark)) < 1.5
    # Matchering missing → built-in with a note
    tools.CONFIG.update({"backends": {"refmaster": "matchering"}, "tools": {"matchering": {"path": str(tmp_path / "x")}}})
    rep2 = refmaster.master(tmp_path / "mix.wav", tmp_path / "ref.wav", tmp_path / "o2.wav")
    assert rep2["backend"] == "builtin" and "not installed" in rep2["note"]


def test_superres_skips_full_band(tmp_path):
    src = tmp_path / "full.wav"
    sf.write(src, lowpassed_noise(cutoff=30000, sr=48000).T, 48000)
    rep = superres.upscale(src, tmp_path / "o.wav", 48000, backend="flashsr")
    assert rep["skipped"].startswith("bandwidth")


# ------------------------------------------------------------------ AI detectors

def test_fakeprint_regression():
    rng = np.random.default_rng(7)
    t = np.arange(SR * 12) / SR
    x = 0.3 * np.sin(2 * np.pi * 220 * t) + 0.05 * rng.standard_normal(t.size)
    r = detect.fakeprint_score(np.vstack([x, x * 0.9]).astype(np.float32), SR)
    assert 0.0 <= r["score"] <= 1.0
    assert abs(r["logit"] - (-24.3069)) < 0.05      # numpy port verified against torch/torchaudio


def test_fakeprint_matches_torchaudio_resample():
    torch = pytest.importorskip("torch")
    ta = pytest.importorskip("torchaudio")
    x = np.random.default_rng(0).standard_normal(44100).astype(np.float32)
    ref = ta.functional.resample(torch.from_numpy(x), 44100, 16000).numpy()
    np.testing.assert_allclose(detect.sinc_resample(x, 44100, 16000), ref, atol=1e-5)


class FakeResp:
    def __init__(self, data, status=200, headers=None):
        self._d, self.status_code, self.headers, self.text = data, status, headers or {}, json.dumps(data)

    def json(self):
        return self._d


class FakeSession:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def _hit(self, method, url, **kw):
        self.calls.append((method, url, kw))
        for (m, frag), fn in self.routes.items():
            if m == method and frag in url:
                return fn(url, kw) if callable(fn) else fn
        raise AssertionError(f"unexpected {method} {url}")

    def post(self, url, **kw):
        return self._hit("POST", url, **kw)

    def get(self, url, **kw):
        return self._hit("GET", url, **kw)

    def put(self, url, **kw):
        return self._hit("PUT", url, **kw)


def test_detect_check_with_cloud_mocks(tmp_path):
    p = tmp_path / "s.wav"
    sf.write(p, lowpassed_noise(seconds=12).T, SR)
    s = FakeSession({
        ("POST", "sightengine"): FakeResp({"status": "success", "type": {"ai_music": 0.93}, "request": {"id": "r1"}}),
        ("POST", "acrcloud"): FakeResp({"data": {"id": 77}}),
        ("GET", "acrcloud"): FakeResp({"data": [{"state": 1, "results": {"ai_detection": [
            {"ai_probability": 88, "prediction": "ai", "likely_source": "suno",
             "source_probabilities": [{"source": "suno", "probability": 80}]}]}}]}),
    })
    keys = {"SIGHTENGINE_API_USER": "u", "SIGHTENGINE_API_SECRET": "s", "ACRCLOUD_TOKEN": "t",
            "ACRCLOUD_CONTAINER_ID": "c"}
    rep = detect.check(p, ["fakeprint", "sightengine", "acrcloud", "aigm"], keys=keys, session=s)
    assert rep["results"]["sightengine"]["score"] == 0.93
    assert rep["results"]["acrcloud"]["score"] == 0.88 and rep["results"]["acrcloud"]["likely_source"] == "suno"
    assert rep["results"]["aigm"]["ok"] is False             # not installed → reported, not fatal
    assert rep["verdict"] in ("mixed", "ai") and rep["recommend_disclosure"] is True
    assert detect.save_report(rep, tmp_path).exists()


# ------------------------------------------------------------------ lyrics / LRC

LYRICS = """[Verse 1]
Hello city lights
Running through the night
[Chorus]
We are alive tonight
"""


def test_lyrics_align_lrc_srt():
    lines = lyrics.parse_lyrics(LYRICS)
    assert [ln["section"] for ln in lines] == ["Verse 1", "Verse 1", "Chorus"]
    words = [{"word": w, "start": s, "end": s + 0.4} for w, s in
             [("Hello", 1.0), ("city", 1.5), ("lights", 2.0), ("Running", 4.0), ("thru", 4.5), ("the", 5.0),
              ("night", 5.5), ("we", 9.0), ("are", 9.4), ("alive", 9.8), ("tonight", 10.3)]]
    al = lyrics.align(lines, words, 20.0)
    assert al[0]["start"] == 1.0 and al[1]["start"] == 4.0 and al[2]["start"] == 9.0
    secs = lyrics.sections(al)
    assert secs[0]["name"] == "Verse 1" and secs[1]["start"] == 9.0
    lrc = lyrics.to_lrc(al, "T", "A", 20.0)
    assert "[00:01.00]Hello city lights" in lrc and "[ti:T]" in lrc
    back = lyrics.parse_lrc(lrc)
    assert [b["start"] for b in back] == [1.0, 4.0, 9.0]
    assert "00:00:01,000 --> " in lyrics.to_srt(al)


def test_lyrics_build_with_fake_whisper(tmp_path):
    p = tmp_path / "song.wav"
    sf.write(p, np.zeros((SR * 5, 2), np.float32), SR)
    exe = fake_cli(tmp_path / "whisper", """
        import json, sys
        a = sys.argv[1:]
        out = a[a.index("--output_dir") + 1]
        w = [{"word": " Hello", "start": 0.5, "end": 0.9}, {"word": " city", "start": 1.0, "end": 1.3},
             {"word": " lights", "start": 1.4, "end": 1.9}]
        json.dump({"language": "en", "segments": [{"text": "Hello city lights", "start": 0.5, "end": 1.9,
                   "words": w}]}, open(out + "/song.json", "w"))
    """)
    tools.CONFIG.update({"tools": {"whisper": {"path": str(exe)}, "mlx_whisper": {"enabled": False}}})
    res = lyrics.build(p, "Hello city lights\nSecond line", tmp_path, "T", "A", duration=5.0)
    assert res["backend"] == "whisper" and res["matched"] == 1 and res["total"] == 2
    assert Path(res["lrc"]).read_text(encoding="utf-8").count("[00:00.50]Hello city lights") == 1


# ------------------------------------------------------------------ cover

def test_procedural_cover(tmp_path):
    p = tmp_path / "s.wav"
    sf.write(p, lowpassed_noise(seconds=4).T, SR)
    res = cover.generate(tmp_path / "cover", "neon city", seed=5, backend="builtin", audio_path=p)
    from studio.publish.media import image_size
    assert image_size(res["cover"]) == (3000, 3000)
    assert image_size(res["thumb"])[0] == 320
    assert res["backend"] == "procedural"


# ------------------------------------------------------------------ timeline edits

def test_ace_edit_payloads():
    e = AceStepGenerator(base_url="http://127.0.0.1:1")
    p = e.build_edit_payload("repaint", start=30, end=52.5, prompt="softer verse", lyrics="[Verse 2]\nla")
    assert p["task_type"] == "repaint" and p["repainting_start"] == 30 and p["repainting_end"] == 52.5
    assert p["chunk_mask_mode"] == "explicit"
    c = e.build_edit_payload("cover", strength=0.7, prompt="jazz")
    assert c["audio_cover_strength"] == 0.7
    x = e.build_edit_payload("extract", track="vocals", model="acestep-v15-base")
    assert x["track_name"] == "vocals"
    with pytest.raises(GenerationError):
        e.build_edit_payload("extract", track="vocals", model="acestep-v15-turbo")
    with pytest.raises(GenerationError):
        e.build_edit_payload("repaint", start=40, end=10)


def test_splice_keeps_outside_bit_exact(tmp_path):
    a = lowpassed_noise(seconds=10, seed=1)
    b = lowpassed_noise(seconds=10, seed=2)
    sf.write(tmp_path / "a.wav", a.T, SR, subtype="FLOAT")
    sf.write(tmp_path / "b.wav", b.T, SR, subtype="FLOAT")
    r = editing.splice(tmp_path / "a.wav", tmp_path / "b.wav", tmp_path / "o.wav", 3.0, 6.0, xfade=0.2,
                       align=False)
    o, sr = sf.read(r["path"], dtype="float32", always_2d=True)
    o = o.T
    q = 1 / 2 ** 23
    np.testing.assert_allclose(o[:, : int(2.8 * SR)], a[:, : int(2.8 * SR)], atol=q)
    np.testing.assert_allclose(o[:, int(6.2 * SR):], a[:, int(6.2 * SR):], atol=q)
    np.testing.assert_allclose(o[:, int(3.2 * SR): int(5.8 * SR)], b[:, int(3.2 * SR): int(5.8 * SR)], atol=q)


def test_splice_aligns_shifted_edit(tmp_path):
    a = lowpassed_noise(seconds=8, seed=4)
    shifted = np.pad(a, ((0, 0), (300, 0)))[:, : a.shape[1]]
    assert editing.align_offset(a, shifted, SR, 4.0) == 300


# ------------------------------------------------------------------ publishing

def test_telegram_caption_and_send(tmp_path):
    cap = telegram.build_caption("Song <1>", "Me & You", "x" * 2000, "Made with AI", ["synthpop", "ai music"])
    assert len(cap) <= 1024 and "&lt;1&gt;" in cap and "#synthpop" in cap
    mp3 = tmp_path / "a.mp3"
    mp3.write_bytes(b"ID3" + b"\0" * 1000)
    with pytest.raises(PermissionError):
        telegram.send_audio("t", "@ch", mp3, "S")
    s = FakeSession({("POST", "sendAudio"): FakeResp({"ok": True, "result": {
        "message_id": 12, "chat": {"id": -100, "username": "mychan"}}})})
    r = telegram.send_audio("t", "@ch", mp3, "S", "Me", 100, cap, session=s, confirmed=True)
    assert r["url"] == "https://t.me/mychan/12"
    assert s.calls[0][2]["data"]["parse_mode"] == "HTML"


def test_youtube_body_and_resumable_upload(tmp_path):
    body = youtube.build_body("T", "d", ["a"], "public", publish_at="2026-12-01T10:00:00Z")
    assert body["status"]["privacyStatus"] == "private" and body["status"]["containsSyntheticMedia"] is True
    assert body["snippet"]["categoryId"] == "10"
    vid = tmp_path / "v.mp4"
    vid.write_bytes(os.urandom(youtube.CHUNK + 1000))
    puts = []

    def put(url, kw):
        puts.append(kw["headers"]["Content-Range"])
        if len(puts) == 1:
            return FakeResp({}, 308, {"Range": f"bytes=0-{youtube.CHUNK - 1}"})
        return FakeResp({"id": "abc123"}, 200)

    s = FakeSession({("POST", "oauth2"): FakeResp({"access_token": "at"}),
                     ("POST", "upload"): FakeResp({}, 200, {"Location": "https://up/session"}),
                     ("PUT", "up/session"): put})
    with pytest.raises(PermissionError):
        youtube.upload(vid, youtube.build_body("T", privacy="public"), "c", "s", "r", session=s, confirmed=True)
    r = youtube.upload(vid, body, "c", "s", "r", session=s, confirmed=True)
    assert r["url"] == "https://youtu.be/abc123"
    assert puts[1].startswith(f"bytes {youtube.CHUNK}-")


def test_youtube_quota_is_not_permanent():
    r = FakeResp({"error": {"message": "q", "errors": [{"reason": "quotaExceeded"}]}}, 403)
    with pytest.raises(youtube.YouTubeError) as e:
        youtube._raise(r)
    assert e.value.permanent is False and "tomorrow" in str(e.value)


def test_queue_backoff_and_log(tmp_path):
    q = release.PublishQueue(tmp_path)
    j = q.add("r1", "telegram", {})
    w = q.fail(j, "net", permanent=False)
    assert w["status"] == "waiting" and w["next_try"] > 0 and not q.due()
    assert q.due(now=w["next_try"] + 1)
    f = q.fail(w, "bad token", permanent=True)
    assert f["status"] == "failed"
    j2 = q.add("r1", "youtube", {})
    q.done(j2, {"url": "https://youtu.be/x"})
    assert q.log()[0]["url"] == "https://youtu.be/x"
    assert q.remove(j["id"]) and len(q.jobs()) == 1


def test_release_pipeline_package(tmp_path):
    t = np.arange(SR * 40) / SR
    x = (0.25 * np.sin(2 * np.pi * 330 * t)).astype(np.float32)
    src = tmp_path / "mix.wav"
    sf.write(src, np.vstack([x, x]).T, SR)
    rel = release.create(tmp_path, src, "Night Drive", "Andrei", LYRICS, {"genre": "synthpop"})
    tools.CONFIG.update({"backends": {"superres": "off"}})
    rel = pipeline.run_step(tmp_path, rel, "superres", {"export_sr": 48000}, {})
    assert rel.superres["skipped"] and Path(rel.master).exists()
    rel = pipeline.run_step(tmp_path, rel, "refmaster", {}, {})
    assert rel.meta["refmaster"]["skipped"]
    refp = tmp_path / "ref.wav"
    sf.write(refp, (np.random.default_rng(5).standard_normal((SR * 5, 2)) * 0.1), SR)
    pre = rel.master
    rel = pipeline.run_step(tmp_path, rel, "refmaster", {"reference": str(refp), "backend": "builtin"}, {})
    assert rel.master.endswith("master_ref.wav") and Path(rel.master).exists()
    rel = pipeline.run_step(tmp_path, rel, "refmaster", {"reference": str(refp), "backend": "builtin", "strength": 0.5}, {})
    assert rel.meta["refmaster"]["input"] == pre                       # re-run starts from the pre-match master
    rel = pipeline.run_step(tmp_path, rel, "cover", {"backend": "builtin", "seed": 3}, {})
    rel = pipeline.run_step(tmp_path, rel, "lyrics", {"lrc_text": "[00:01.00]Hello city lights\n"}, {})
    rel = pipeline.run_step(tmp_path, rel, "detect", {"detectors": ["fakeprint"]}, {})
    rel = pipeline.run_step(tmp_path, rel, "package", {}, {})
    pk = rel.meta["package"]
    folder = Path(pk["folder"])
    meta = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    assert meta["sample_rate"] == 44100 and meta["bit_depth"] == 24 and meta["ai"]["generated"] is True
    assert (folder / "lyrics.lrc").exists() and (folder / "ai_check.json").exists()
    assert sf.info(pk["wav"]).subtype == "PCM_24"
    assert all(c["ok"] for c in pk["checks"] if c["check"] in ("cover_size", "title", "artist", "ai_disclosure"))
    sums = (folder / "SHA256SUMS").read_text().splitlines()
    assert any(s.endswith("metadata.json") for s in sums)
    assert "Made with AI" in pipeline.youtube_description(release.Release.load(tmp_path, rel.id), "en")
    assert release.list_releases(tmp_path)[0]["id"] == rel.id


def test_messages_translate_both_ways():
    assert message("Lyrics: 3/5 lines timed", "ru") == "Текст: 3/5 строк с таймингом"
    assert message("Готово: 2 трек(а)", "en") == "Done: 2 track(s)"
    assert message("Готово", "ru") == "Готово"


def test_package_validate_flags_missing_cover():
    a = np.zeros((2, SR * 40), np.float32)
    checks = {c["check"]: c for c in package.validate(a, SR, None, {"title": "t", "artist": "a", "ai": {}})}
    assert not checks["cover_size"]["ok"] and not checks["ai_disclosure"]["ok"]


def test_engine_edit_run_splices_outside_region(tmp_path):
    """edit.run with a fake ACE-Step: the regenerated file is spliced so the rest stays bit-exact."""
    import io

    from studio.engine_server import Server
    from studio.generators.base import GeneratedTrack

    a = lowpassed_noise(seconds=10, seed=11)
    src = tmp_path / "song.wav"
    sf.write(src, a.T, SR, subtype="FLOAT")

    class FakeAce:
        def edit(self, path, task, out_dir, title="", progress=None, cancel=None, **kw):
            assert task == "repaint" and kw["start"] == 3 and kw["end"] == 6
            b = lowpassed_noise(seconds=10, sr=48000, seed=12)      # ACE returns 48 kHz
            Path(out_dir).mkdir(parents=True, exist_ok=True)
            out = Path(out_dir) / "edit.flac"
            sf.write(out, b.T, 48000)
            t = GeneratedTrack(path=out, title="song — repaint", engine="acestep", meta={"duration": 10.0})
            t.save_sidecar()
            return [t]

    srv = Server(io.StringIO())
    srv._engine = lambda eid: FakeAce()
    r = srv.m_edit_run({"path": str(src), "task": "repaint", "start": 3, "end": 6, "root": str(tmp_path),
                        "xfade": 0.2})
    out = Path(r["tracks"][0]["path"])
    assert out.name.endswith("(splice).wav") and out.with_suffix(".json").exists()
    o, sr = sf.read(out, dtype="float32", always_2d=True)
    assert sr == SR
    np.testing.assert_allclose(o.T[:, : int(2.8 * SR)], a[:, : int(2.8 * SR)], atol=1 / 2 ** 23)
    assert not (tmp_path / "generated" / "edits" / "edit.flac").exists()
