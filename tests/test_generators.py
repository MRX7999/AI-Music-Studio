"""Протоколы ACE-Step и GPTunneL проверяются на локальных mock-серверах (без сети и ключей)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from studio.generators import AceStepGenerator, GenerationRequest, GptunnelGenerator


def _wav_bytes(tmp: Path) -> bytes:
    p = tmp / "x.wav"
    sf.write(str(p), np.zeros((4410, 2)), 44100)
    return p.read_bytes()


class _Server:
    def __init__(self, handler):
        self.httpd = HTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()


@pytest.fixture
def ace_server(tmp_path):
    audio = _wav_bytes(tmp_path)
    state = {"polls": 0, "payload": None, "auth": None}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, obj, code=200):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            state["auth"] = self.headers.get("Authorization")
            if self.path == "/health":
                return self._json({"data": {"status": "ok"}, "code": 200, "error": None})
            if self.path == "/v1/models":
                return self._json({"data": {"models": [{"name": "acestep-v15-turbo", "is_default": True}]},
                                   "code": 200})
            if self.path.startswith("/v1/audio"):
                self.send_response(200)
                self.send_header("Content-Length", str(len(audio)))
                self.end_headers()
                self.wfile.write(audio)
                return
            self._json({"error": "nf"}, 404)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/release_task":
                state["payload"] = body
                return self._json({"data": {"task_id": "t1", "status": "queued"}, "code": 200, "error": None})
            if self.path == "/query_result":
                assert body["task_id_list"] == ["t1"]
                state["polls"] += 1
                if state["polls"] < 2:
                    return self._json({"data": [{"task_id": "t1", "status": 0}], "code": 200})
                res = [{"file": f"/v1/audio?path=%2Ftmp%2F{i}.flac", "status": 1, "lyrics": "la",
                        "metas": {"bpm": 120, "duration": 30, "keyscale": "C Major"}, "seed_value": "1"}
                       for i in range(2)]
                return self._json({"data": [{"task_id": "t1", "status": 1, "result": json.dumps(res)}],
                                   "code": 200})
            self._json({"error": "nf"}, 404)

    srv = _Server(H)
    yield srv, state
    srv.close()


def test_acestep_protocol(ace_server, tmp_path, monkeypatch):
    srv, state = ace_server
    import studio.generators.acestep as mod
    monkeypatch.setattr(mod, "sleep_with_cancel", lambda s, c=None: None)
    g = AceStepGenerator(base_url=srv.url, api_key="k123")
    assert g.is_available()[0]
    assert g.models()[0]["id"] == "acestep-v15-turbo"
    req = GenerationRequest(title="Песня", style="pop", lyrics="[Verse]\nla", duration=30, bpm=120,
                            key="C major", variations=2, seed=5, model="acestep-v15-turbo")
    tracks = g.generate(req, tmp_path / "out")
    p = state["payload"]
    assert p["prompt"] == "pop" and p["lyrics"].startswith("[Verse]") and p["audio_duration"] == 30
    assert p["batch_size"] == 2 and p["use_random_seed"] is False and p["seed"] == 5 and p["bpm"] == 120
    assert p["key_scale"] == "C major" and p["model"] == "acestep-v15-turbo"
    assert state["auth"] == "Bearer k123"
    assert len(tracks) == 2 and all(t.path.exists() for t in tracks)
    assert tracks[0].path.with_suffix(".json").exists()


def test_acestep_instrumental_payload():
    g = AceStepGenerator(base_url="http://127.0.0.1:9")
    p = g.build_payload(GenerationRequest(style="ambient", lyrics="text", instrumental=True, duration=5))
    assert p["lyrics"] == "[Instrumental]" and p["audio_duration"] == 10


def test_acestep_unavailable_message():
    ok, msg = AceStepGenerator(base_url="http://127.0.0.1:9", timeout=1).is_available()
    assert not ok and "acestep-api" in msg


@pytest.fixture
def gpt_server(tmp_path):
    audio = _wav_bytes(tmp_path)
    state = {"polls": 0, "body": None, "auth": []}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, obj, code=200):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if self.path.startswith("/api/"):
                state["auth"].append(self.headers.get("Authorization"))
            else:   # файлы хранилища: ключ туда не уходит
                assert self.headers.get("Authorization") is None
            if self.path == "/api/v2/media/models":
                return self._json({"code": 0, "models": [
                    {"id": "kling-v3", "type": "VIDEO", "params": []},
                    {"id": "suno", "type": "MUSIC", "price": 16.8, "price_unit": "per_generation",
                     "prompt": "optional", "params": [
                         {"key": "lyrics", "type": "string"}, {"key": "style", "type": "string"},
                         {"key": "title", "type": "string"}, {"key": "instrumental", "type": "boolean"},
                         {"key": "version", "type": "enum", "default": "v5",
                          "options": [{"value": "v4.5", "label": "4.5"}, {"value": "v5", "label": "5"}]}]}]})
            if self.path == "/api/v2/media/tasks/T9":
                state["polls"] += 1
                if state["polls"] < 2:
                    return self._json({"code": 0, "id": "T9", "status": "running", "result": []})
                return self._json({"code": 0, "id": "T9", "status": "done", "price": 16.8, "result": [
                    {"url": f"{srv.url}/files/a_1.mp3", "cover_url": f"{srv.url}/files/a_1.jpg", "title": "Ночь",
                     "lyric": "[Verse]", "duration": 128, "id": "p1", "tags": "pop"},
                    {"url": f"{srv.url}/files/a_2.mp3", "title": "Ночь", "duration": 131, "id": "p2"}]})
            if self.path.startswith("/files/"):
                self.send_response(200)
                self.send_header("Content-Length", str(len(audio)))
                self.end_headers()
                self.wfile.write(audio)
                return
            self._json({"code": 5}, 404)

        def do_POST(self):
            state["auth"].append(self.headers.get("Authorization"))
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/api/v2/media/tasks":
                state["body"] = body
                if set(body) - {"model", "prompt", "params", "inputs", "webhook_url", "idempotency_key", "wait"}:
                    return self._json({"code": 3, "details": "unknown field"}, 400)
                return self._json({"code": 0, "id": "T9", "status": "queued", "result": []})
            if self.path == "/api/v2/media/price":
                return self._json({"code": 0, "price": 16.8})
            self._json({"code": 5}, 404)

    srv = _Server(H)
    yield srv, state
    srv.close()


def test_gptunnel_protocol(gpt_server, tmp_path, monkeypatch):
    srv, state = gpt_server
    import studio.generators.gptunnel as mod
    monkeypatch.setattr(mod, "sleep_with_cancel", lambda s, c=None: None)
    g = GptunnelGenerator(api_key="KEY", base=srv.url + "/api/v2/media")
    ok, msg = g.is_available()
    assert ok, msg
    assert [m["id"] for m in g.models()] == ["suno"]
    schema = g.param_schema("suno")
    assert [f["key"] for f in schema] == ["version"] and schema[0]["options"] == ["v4.5", "v5"]
    req = GenerationRequest(title="Ночь", style="synthwave", lyrics="[Verse]\nтекст", model="suno",
                            variations=2, extra={"version": "v5"})
    assert "16.8" in g.estimate_price(req)
    tracks = g.generate(req, tmp_path / "o")
    b = state["body"]
    assert b["model"] == "suno" and b["params"]["lyrics"].startswith("[Verse]")
    assert b["params"]["style"] == "synthwave" and b["params"]["title"] == "Ночь"
    assert b["params"]["instrumental"] is False and b["params"]["version"] == "v5"
    assert b["idempotency_key"].startswith("ams-")
    assert all(a == "KEY" for a in state["auth"])          # без "Bearer"
    assert len(tracks) == 2 and tracks[0].cover and tracks[0].cover.exists()
    assert tracks[0].meta["price"] == 16.8


def test_gptunnel_requires_key():
    ok, msg = GptunnelGenerator(api_key="").is_available()
    assert not ok and "GPTUNNEL_API_KEY" in msg


def test_sidecar_survives_folder_move(tmp_path):
    """Пути в <песня>.json относительные: папку с песней можно перенести."""
    import shutil
    from studio.generators import DemoGenerator, GenerationRequest
    from studio.generators.base import GeneratedTrack
    t = DemoGenerator().generate(GenerationRequest(title="Move", duration=8, seed=3), tmp_path / "a")[0]
    side = t.path.with_suffix(".json")
    shutil.move(str(tmp_path / "a"), str(tmp_path / "b"))
    moved = GeneratedTrack.from_sidecar(tmp_path / "b" / side.relative_to(tmp_path / "a"))
    assert moved.path.exists()
    assert set(moved.stems) == {"drums", "bass", "keys", "lead"}
    assert all(p.exists() for p in moved.stems.values())
