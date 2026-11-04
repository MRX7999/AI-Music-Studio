"""Engine server for the native macOS app: JSON-lines protocol over a real subprocess."""
import itertools
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]


class Client:
    def __init__(self, tmp: Path):
        env = {**os.environ, "AMS_LANG": "en", "PYTHONPATH": str(ROOT), "TMPDIR": str(tmp)}
        for k in ("ACESTEP_API_URL", "ACESTEP_API_KEY", "GPTUNNEL_API_KEY"):
            env.pop(k, None)
        self.p = subprocess.Popen([sys.executable, "-m", "studio.engine_server"], cwd=str(ROOT), env=env,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.q: "queue.Queue[dict]" = queue.Queue()
        self.raw: list = []
        self.ids = itertools.count(1)
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._drain_err, daemon=True).start()
        self.ready = self.next_message(30)

    def _read(self):
        for line in self.p.stdout:
            self.raw.append(line)
            self.q.put(json.loads(line))

    def _drain_err(self):
        for _ in self.p.stderr:
            pass

    def next_message(self, timeout):
        return self.q.get(timeout=timeout)

    def send(self, method, params=None, rid=None):
        rid = next(self.ids) if rid is None else rid
        self.p.stdin.write((json.dumps({"id": rid, "method": method, "params": params or {}}) + "\n").encode())
        self.p.stdin.flush()
        return rid

    def wait(self, rid, timeout=120, events=None):
        pending = []
        deadline = time.time() + timeout
        try:
            while True:
                m = self.q.get(timeout=max(0.1, deadline - time.time()))
                if m.get("id") == rid and "event" not in m:
                    return m
                if m.get("event") == "progress" and m.get("id") == rid and events is not None:
                    events.append(m)
                elif m.get("id") != rid:
                    pending.append(m)
        finally:
            for m in pending:
                self.q.put(m)

    def call(self, method, params=None, timeout=120, events=None):
        m = self.wait(self.send(method, params), timeout, events)
        if "error" in m:
            raise RuntimeError(f"{m['error']['type']}: {m['error']['message']}")
        return m["result"]

    def close(self):
        try:
            self.call("shutdown", timeout=20)
            self.p.wait(timeout=30)
        finally:
            if self.p.poll() is None:
                self.p.kill()


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    c = Client(tmp_path_factory.mktemp("srv-tmp"))
    yield c
    c.close()
    assert c.p.returncode == 0


@pytest.fixture(scope="module")
def project(client, tmp_path_factory):
    root = tmp_path_factory.mktemp("project")
    events = []
    res = client.call("generate", {"engine": "demo", "root": str(root),
                                   "request": {"title": "Server Song", "duration": 10, "bpm": 100, "seed": 5}},
                      events=events)
    return root, res, events


def test_ready_and_ping(client):
    assert client.ready["event"] == "ready"
    r = client.call("ping")
    assert r["ok"] and r["version"] == "1.2.3" and r["lang"] == "en"


def test_info_lists_catalogs_in_english(client):
    info = client.call("info", {"lang": "en"})
    scenes = {s["id"]: s for s in info["scenes"]}
    assert len(scenes) >= 10 and scenes["dry"]["name"].startswith("Dry")
    assert {t["id"] for t in info["techniques"]} == {"ab", "xy", "ortf", "nos", "blumlein"}
    assert any(m["id"] == "ldc_studio" for m in info["mics"])
    assert info["defaults"]["channel"]["comp_mode"] == "auto"
    assert info["defaults"]["recording"]["mp3_bitrate"] == 320
    assert all(not any("а" <= ch <= "я" for ch in s["name"].lower()) for s in info["scenes"])


def test_protocol_errors(client):
    m = client.wait(client.send("no.such.method"))
    assert m["error"]["type"] == "MethodNotFound"
    client.p.stdin.write(b"{not json\n")
    client.p.stdin.flush()
    bad = client.next_message(10)
    assert bad["id"] is None and bad["error"]["type"] == "ProtocolError"
    with pytest.raises(RuntimeError, match="root"):
        client.call("library.scan", {})


def test_generate_demo_reports_progress(project):
    root, res, events = project
    (t,) = res["tracks"]
    assert Path(t["path"]).exists() and set(t["stems"]) == {"drums", "bass", "keys", "lead"}
    assert events and all(0 <= e["frac"] <= 1.0 for e in events)


def test_open_track_describe_and_ops(client, project):
    root, res, _ = project
    t = res["tracks"][0]
    o = client.call("session.open_track", {"path": t["sidecar"] or t["path"], "root": str(root)})
    assert o["created"] and Path(o["path"]).exists()
    s = o["session"]
    assert len(s["channels"]) == 4 and s["version"] == 2
    # the engine runs in English here: preset channel names follow the interface language
    assert {c["name"] for c in s["channels"]} == {"Drums", "Bass", "Piano / keys", "Synth / pad"}
    again = client.call("session.open_track", {"path": t["path"], "root": str(root)})
    assert not again["created"] and again["path"] == o["path"]

    d = client.call("session.describe", {"session": s})
    assert set(d["channels"]) == {c["id"] for c in s["channels"]} and len(d["pair"]) == 2

    s2 = client.call("session.op", {"session": s, "op": "set_scene", "args": {"scene": "cathedral"}})["session"]
    assert s2["scene"] == "cathedral"
    s3 = client.call("session.op", {"session": s2, "op": "set_room_size",
                                    "args": {"width": 30, "depth": 50, "height": 20}})["session"]
    assert s3["room_width"] == 30
    cid = s3["channels"][0]["id"]
    s4 = client.call("session.op", {"session": s3, "op": "duplicate_channel", "args": {"channel": cid}})["session"]
    assert len(s4["channels"]) == 5
    s5 = client.call("session.op", {"session": s4, "op": "remove_channel", "args": {"channel": cid}})["session"]
    assert len(s5["channels"]) == 4 and cid not in {c["id"] for c in s5["channels"]}
    with pytest.raises(RuntimeError, match="unknown session op"):
        client.call("session.op", {"session": s5, "op": "explode"})


def test_preview_final_analyze_and_library(client, project):
    root, res, _ = project
    t = res["tracks"][0]
    o = client.call("session.open_track", {"path": t["path"], "root": str(root)})
    s = o["session"]
    pv = client.call("render.preview", {"session": s, "start_s": 1.0, "duration_s": 3.0})
    a, sr = sf.read(pv["path"])
    assert abs(len(a) / sr - 3.0) < 0.6
    meters = pv["report"]["meters"]
    assert set(meters["channels"]) == {c["id"] for c in s["channels"]} and meters["hop_s"] == 0.05

    s["recording"]["output_format"] = "flac"
    fin = client.call("render.final", {"session": s, "session_path": o["path"], "export_stems": True})
    out = Path(fin["path"])
    assert out.exists() and out.suffix == ".flac" and out.parent.name == "renders"
    assert Path(fin["report_path"]).exists() and Path(fin["stems_dir"]).is_dir()
    assert abs(fin["report"]["master"]["lufs_after"] - s["recording"]["target_lufs"]) < 1.0

    an = client.call("analyze", {"path": str(out), "points": 400})
    assert an["points"] <= 400 and len(an["peaks"]) == 2 and "lufs" in an
    assert client.call("analyze", {"path": str(out), "points": 400}) == an          # cached

    lib = client.call("library.scan", {"root": str(root)})
    assert any(x["title"] == "Server Song" for x in lib["songs"])
    assert lib["sessions"] and lib["renders"]


def test_group_replaces_previous_preview(client, project):
    root, res, _ = project
    s = client.call("session.open_track", {"path": res["tracks"][0]["path"], "root": str(root)})["session"]
    first = client.send("render.preview", {"session": s, "duration_s": 10.0, "_group": "live"})
    second = client.send("render.preview", {"session": s, "duration_s": 1.0, "_group": "live"})
    m1 = client.wait(first)
    m2 = client.wait(second)
    assert "result" in m2
    assert m1["error"]["type"] == "Cancelled"


def test_explicit_cancel(client, project):
    root, res, _ = project
    s = client.call("session.open_track", {"path": res["tracks"][0]["path"], "root": str(root)})["session"]
    s["recording"]["sample_rate"] = 96000
    rid = client.send("render.final", {"session": s, "out_path": str(root / "cancel-me")})
    assert client.call("cancel", {"target": rid})["ok"] is True
    m = client.wait(rid)
    assert m["error"]["type"] == "Cancelled"
    assert not list(root.glob("cancel-me*"))


def test_stdout_is_pure_protocol(client):
    client.call("ping")
    assert client.raw and all(json.loads(line) is not None for line in client.raw)


def test_session_json_from_native_app_is_coerced(client, project):
    root, res, _ = project
    s = client.call("session.open_track", {"path": res["tracks"][0]["path"], "root": str(root)})["session"]
    s["recording"]["sample_rate"] = 44100.0          # Swift JSONEncoder may send whole doubles
    s["recording"]["limiter"] = 1
    s["channels"][0]["gain_db"] = -3                 # and ints for float fields
    d = client.call("session.describe", {"session": s})
    assert d["scene"]["id"] == s["scene"] and not any("а" <= ch <= "я" for ch in d["scene"]["name"].lower())
    pv = client.call("render.preview", {"session": s, "duration_s": 1.0})
    assert pv["report"]["sample_rate"] == 44100


def test_new_session_names_follow_language(client, project):
    root, res, _ = project
    stems = res["tracks"][0]["stems"]
    src = stems["bass"] if isinstance(stems, dict) else next(iter(stems))
    try:
        client.call("config.set", {"lang": "ru"})
        s = client.call("session.new", {"sources": [src]})["session"]
        assert s["name"] == "Новая сессия" and s["channels"][0]["name"] == "Бас"
        s = client.call("session.op", {"session": s, "op": "add_channel",
                                       "args": {"source": src, "name": "Мой бас"}})["session"]
        assert s["channels"][-1]["name"] == "Мой бас"
    finally:
        client.call("config.set", {"lang": "en"})
    s = client.call("session.new", {"sources": [src]})["session"]
    assert s["name"] == "New session" and s["channels"][0]["name"] == "Bass"


def test_localize_names_follows_language_switch(client, project):
    root, res, _ = project
    stems = res["tracks"][0]["stems"]
    src = stems["bass"] if isinstance(stems, dict) else next(iter(stems))
    s = client.call("session.new", {"sources": [src]})["session"]
    s = client.call("session.op", {"session": s, "op": "add_channel",
                                   "args": {"source": src, "name": "My bass"}})["session"]
    assert [c["name"] for c in s["channels"]] == ["Bass", "My bass"]
    try:
        client.call("config.set", {"lang": "ru"})
        s = client.call("session.op", {"session": s, "op": "localize_names"})["session"]
        assert [c["name"] for c in s["channels"]] == ["Бас", "My bass"]
    finally:
        client.call("config.set", {"lang": "en"})
    s = client.call("session.op", {"session": s, "op": "localize_names"})["session"]
    assert [c["name"] for c in s["channels"]] == ["Bass", "My bass"]


# ── v1.2: tools, release pipeline, publishing guards, timeline edits ──

def test_tools_doctor_and_config(client):
    d = client.call("tools.doctor")
    assert {"superres", "lyrics", "stems", "cover", "detect", "voice", "refmaster"} <= set(d["features"])
    assert d["detectors"]["fakeprint"] is True and d["detectors"]["sightengine"] is False
    r = client.call("config.set", {"tools": {"backends": {"cover": "builtin"}},
                                   "secrets": {"TELEGRAM_CHAT_ID": "@test", "NOT_ALLOWED": "x"}})
    assert r["secrets_set"] == ["TELEGRAM_CHAT_ID"]
    assert client.call("tools.doctor")["features"]["cover"]["backend"] == "builtin"


def test_release_pipeline_over_protocol(client, project, tmp_path):
    root, res, _ = project
    t = res["tracks"][0]
    a = client.call("superres.analyze", {"path": t["path"], "export_sr": 48000})
    assert a["cutoff_hz"] > 0 and "needs_superres" in a
    png = client.call("spectrum.image", {"path": t["path"], "out": str(tmp_path / "s.png")})
    assert Path(png["path"]).read_bytes()[:4] == b"\x89PNG"
    rel = client.call("release.create", {"root": str(root), "source": t["path"], "title": "Server Song",
                                         "artist": "CI", "lyrics": "[Verse]\nla la"})
    for step, opts in (("cover", {"backend": "builtin", "seed": 1}), ("detect", {"detectors": ["fakeprint"]}),
                       ("package", {})):
        rel = client.call("release.step", {"root": str(root), "id": rel["id"], "step": step, "options": opts},
                          timeout=180)
    assert rel["ready"]["cover"] and rel["ready"]["detect"] and rel["ready"]["package"]
    assert rel["ai_report"]["recommend_disclosure"] is True
    assert client.call("release.list", {"root": str(root)})["releases"][0]["id"] == rel["id"]
    with pytest.raises(RuntimeError, match="confirmation"):
        client.call("publish.submit", {"root": str(root), "id": rel["id"], "services": {"package": {}}})
    with pytest.raises(RuntimeError, match="Public visibility"):
        client.call("publish.submit", {"root": str(root), "id": rel["id"], "confirmed": True,
                                       "services": {"youtube": {"privacy": "public"}}})
    out = client.call("publish.submit", {"root": str(root), "id": rel["id"], "confirmed": True,
                                         "services": {"package": {}, "telegram": {}}}, timeout=180)
    by = {j["service"]: j for j in out["jobs"]}
    assert by["package"]["status"] == "done"
    assert by["telegram"]["status"] == "failed" and "token" in by["telegram"]["error"]
    q = client.call("publish.queue", {"root": str(root)})
    assert len(q["jobs"]) == 2 and q["log"][0]["service"] == "package"
    assert client.call("publish.remove", {"root": str(root), "job_id": by["telegram"]["id"]})["ok"]


def test_edit_needs_acestep_and_splice_works(client, project, tmp_path):
    root, res, _ = project
    t = res["tracks"][0]
    with pytest.raises(RuntimeError, match="ACE-Step"):
        client.call("edit.run", {"path": t["path"], "task": "repaint", "start": 2, "end": 4, "root": str(root)})
    r = client.call("edit.splice", {"original": t["path"], "edited": t["path"], "out": str(tmp_path / "sp.wav"),
                                    "start": 2, "end": 4})
    assert Path(r["path"]).exists() and r["shift_samples"] == 0
    p = client.call("lyrics.parse", {"lrc": "[00:01.00]a\n[00:05.50]b\n"})
    assert [ln["start"] for ln in p["lines"]] == [1.0, 5.5]
