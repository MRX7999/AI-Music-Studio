"""Engine server for the native macOS app: JSON lines over stdin/stdout.

Protocol (UTF-8, one JSON object per line):
    → {"id": 7, "method": "render.preview", "params": {...}}
    ← {"id": 7, "result": {...}}                                  success
    ← {"id": 7, "error": {"message": "...", "type": "ValueError"}}  failure
    ← {"event": "progress", "id": 7, "frac": 0.42, "msg": "Channel: Vocals"}

Long jobs (generate, render, separation, analysis) run in worker threads, so `cancel` and quick
calls are answered while a render is in progress. Jobs that share params["_group"] replace each
other: a new live preview cancels the previous one.

Run:  python -m studio.engine_server        (stdout carries only the protocol; any print() from
                                             libraries is redirected to stderr)
Secrets (API keys) arrive via environment variables or the `config.set` call on stdin — never as
command-line arguments.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, fields
from pathlib import Path

import numpy as np

from . import __version__
from . import stems as stems_mod
from .audio_io import have_ffmpeg, read_audio, write_audio
from .dsp import PREAMPS, TAPES
from .generators import ENGINES, GenerationRequest, get_engine
from .generators.acestep import LANGS
from .generators.base import GeneratedTrack, safe_name
from .i18n import localized, message
from .library import scan, track_entry
from .loudness import integrated_lufs, true_peak_db
from .mics import MICS, PATTERNS
from .render import channel_geometry, describe_scene, ref_distance, render_preview, render_session
from .scenes import AMBIENCE_KINDS, ROOM_TECHNIQUES, SCENES, critical_distance, room_pair
from .session import INSTRUMENTS, Channel, Recording, Session, session_from_stems

INLINE = {"ping", "cancel", "config.set", "shutdown"}


class Cancelled(Exception):
    pass


def _json_default(o):
    if isinstance(o, Path):
        return str(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (set, tuple)):
        return list(o)
    return str(o)


class Server:
    def __init__(self, out, lang: str | None = None, workers: int = 4):
        self.out = out
        self.lang = lang or os.environ.get("AMS_LANG", "en")
        self.lock = threading.Lock()
        self.jobs: dict = {}            # id → threading.Event (cancel)
        self.groups: dict = {}          # group → id
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ams-job")
        self.config = {
            "acestep_url": os.environ.get("ACESTEP_API_URL", ""),
            "acestep_key": os.environ.get("ACESTEP_API_KEY", ""),
            "gptunnel_key": os.environ.get("GPTUNNEL_API_KEY", ""),
        }
        self._engines: dict = {}
        self._analysis: dict = {}
        self._cache_lock = threading.Lock()
        self.preview_dir = Path(tempfile.gettempdir()) / "ams-engine" / f"previews-{os.getpid()}"
        self.running = True

    # ── transport ────────────────────────────────────────────
    def send(self, obj: dict) -> None:
        line = json.dumps(obj, ensure_ascii=False, default=_json_default)
        with self.lock:
            self.out.write(line + "\n")
            self.out.flush()

    def handle_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        try:
            req = json.loads(line)
            if not isinstance(req, dict):
                raise ValueError("request must be a JSON object")
        except ValueError as e:
            self.send({"id": None, "error": {"message": f"bad JSON: {e}", "type": "ProtocolError"}})
            return
        rid = req.get("id")
        method = str(req.get("method") or "")
        params = req.get("params") or {}
        fn = getattr(self, "m_" + method.replace(".", "_"), None)
        if fn is None:
            self.send({"id": rid, "error": {"message": f"unknown method: {method}", "type": "MethodNotFound"}})
            return
        if method in INLINE:
            self._run(fn, rid, params, None)
            return
        ev = threading.Event()
        with self.lock:
            self.jobs[rid] = ev
            group = params.get("_group")
            if group:
                prev = self.groups.get(group)
                if prev is not None and prev in self.jobs:
                    self.jobs[prev].set()
                self.groups[group] = rid
        self.pool.submit(self._run, fn, rid, params, ev)

    def _run(self, fn, rid, params, ev) -> None:
        last = [0.0]

        def progress(frac, msg=""):
            if ev is not None and ev.is_set():
                raise Cancelled()
            now = time.time()
            if frac >= 1.0 or now - last[0] >= 0.08:
                last[0] = now
                self.send({"event": "progress", "id": rid, "frac": round(float(frac), 4),
                           "msg": message(str(msg), self.lang)})

        def cancel():
            return ev is not None and ev.is_set()

        try:
            result = fn(params, progress=progress, cancel=cancel)
            if cancel():
                raise Cancelled()
            self.send({"id": rid, "result": result})
        except Exception as e:  # noqa: BLE001 — every failure goes back to the client
            name = type(e).__name__
            if isinstance(e, Cancelled) or name in ("RenderCancelled", "GenerationCancelled") or cancel():
                self.send({"id": rid, "error": {"message": message("Отменено", self.lang), "type": "Cancelled"}})
            else:
                traceback.print_exc(file=sys.stderr)
                self.send({"id": rid, "error": {"message": message(str(e), self.lang) or name, "type": name}})
        finally:
            if ev is not None:
                with self.lock:
                    self.jobs.pop(rid, None)
                    for g, j in list(self.groups.items()):
                        if j == rid:
                            self.groups.pop(g, None)

    # ── helpers ──────────────────────────────────────────────
    def _engine(self, engine_id: str):
        key = (engine_id, self.config["acestep_url"], self.config["acestep_key"], self.config["gptunnel_key"])
        eng = self._engines.get(key)
        if eng is None:
            if engine_id == "acestep":
                eng = get_engine(engine_id, base_url=self.config["acestep_url"] or None,
                                 api_key=self.config["acestep_key"] or None)
            elif engine_id == "gptunnel":
                eng = get_engine(engine_id, api_key=self.config["gptunnel_key"] or None)
            else:
                eng = get_engine(engine_id)
            self._engines[key] = eng
        return eng

    def _name(self, kind, item_id, ru):
        return localized(kind, item_id, "name", ru, self.lang)

    def _desc(self, kind, item_id, ru):
        return localized(kind, item_id, "description", ru, self.lang)

    def _name_channels(self, s: Session, only: set | None = None) -> Session:
        """Channels that still carry a preset name (Russian or English) get it in the interface language.

        Instrument presets are named in Russian; names the user typed are left alone.
        """
        for c in s.channels:
            if only is not None and c.id not in only:
                continue
            preset = INSTRUMENTS.get(c.instrument)
            if preset is None:
                continue
            defaults = {preset.name, localized("instrument", c.instrument, "name", preset.name, "en")}
            if c.name in defaults:
                c.name = self._name("instrument", c.instrument, preset.name)
        return s

    def _scene_report(self, d: dict) -> dict:
        """describe_scene() пишет по-русски — переводим имена для выбранного языка интерфейса."""
        d = dict(d or {})
        sid = d.get("id")
        if sid in SCENES:
            d["name"] = self._name("scene", sid, d.get("name", ""))
        tech = d.get("room_technique")
        if tech in ROOM_TECHNIQUES:
            d["room_technique_name"] = self._name("technique", tech, d.get("room_technique_name", ""))
        if self.lang == "en" and isinstance(d.get("size"), str):
            d["size"] = d["size"].replace(" м", " m")
        return d

    def _report(self, rep: dict) -> dict:
        rep = dict(rep)
        if "scene" in rep:
            rep["scene"] = self._scene_report(rep["scene"])
        return rep

    @staticmethod
    def _session(params) -> Session:
        d = params.get("session")
        if not isinstance(d, dict):
            raise ValueError("params.session is required")
        return Session.from_dict(d)

    @staticmethod
    def _request(d: dict) -> GenerationRequest:
        allowed = {f.name for f in fields(GenerationRequest)}
        r = GenerationRequest(**{k: v for k, v in (d or {}).items() if k in allowed})
        if r.bpm in (0, "", None):
            r.bpm = None
        if r.seed in ("", None) or (isinstance(r.seed, (int, float)) and r.seed < 0):
            r.seed = None
        return r

    def _schema(self, eng, model: str) -> list:
        out = []
        for f in eng.param_schema(model):
            f = dict(f)
            f["label"] = localized("param", f.get("key", ""), "name", f.get("label", ""), self.lang)
            out.append(f)
        return out

    # ── service ──────────────────────────────────────────────
    def m_ping(self, p, **_):
        return {"ok": True, "version": __version__, "python": sys.version.split()[0], "pid": os.getpid(),
                "numpy": np.__version__, "lang": self.lang}

    def m_shutdown(self, p, **_):
        self.running = False
        return {"ok": True}

    def m_cancel(self, p, **_):
        target = p.get("target")
        with self.lock:
            ev = self.jobs.get(target)
            group = p.get("group")
            if ev is None and group and self.groups.get(group) in self.jobs:
                ev = self.jobs[self.groups[group]]
        if ev is not None:
            ev.set()
        return {"ok": ev is not None}

    def m_config_set(self, p, **_):
        for k in ("acestep_url", "acestep_key", "gptunnel_key"):
            if k in p and p[k] is not None:
                self.config[k] = str(p[k]).strip()
        if p.get("lang") in ("en", "ru"):
            self.lang = p["lang"]
        self._engines.clear()
        return {"ok": True, "lang": self.lang}

    def m_info(self, p, **_):
        if p.get("lang") in ("en", "ru"):
            self.lang = p["lang"]
        scenes = []
        for sc in SCENES.values():
            x0, y0, x1, y1 = sc.stage_rect()
            lx, ly = sc.listener_pos()
            scenes.append({
                "id": sc.id, "name": self._name("scene", sc.id, sc.name),
                "description": self._desc("scene", sc.id, sc.description),
                "width": sc.width, "depth": sc.depth, "height": sc.height, "rt60": sc.rt60,
                "hf_ratio": sc.hf_ratio, "lf_ratio": sc.lf_ratio, "early_db": sc.early_db,
                "stage": [x0, y0, x1, y1], "listener": [lx, ly], "ambience": sc.ambience,
                "ambience_db": sc.ambience_db, "volume": round(sc.volume, 1),
                "critical_distance": round(critical_distance(sc, sc.rt60), 2) if sc.rt60 > 0 else None,
            })
        mics = [{"id": m.id, "name": self._name("mic", m.id, m.name),
                 "description": self._desc("mic", m.id, m.description), "kind": m.kind,
                 "pattern": m.pattern, "self_noise_dba": m.self_noise_dba,
                 "eq": [list(b) for b in m.eq]} for m in MICS.values()]
        patterns = [{"id": k, "name": self._name("pattern", k, v["name"]), "a": v["a"], "ree": v["ree"]}
                    for k, v in PATTERNS.items()]
        instruments = [{"id": i.id, "name": self._name("instrument", i.id, i.name), "mic": i.mic,
                        "distance_cm": i.distance_cm, "angle_deg": i.angle_deg, "color": i.color,
                        "stereo": i.stereo, "stage_pos": list(i.stage_pos)} for i in INSTRUMENTS.values()]
        methods = stems_mod.METHODS
        return {
            "version": __version__, "lang": self.lang,
            "scenes": scenes, "mics": mics, "patterns": patterns, "instruments": instruments,
            "preamps": [{"id": k, "name": self._name("preamp", k, v["name"])} for k, v in PREAMPS.items()],
            "tapes": [{"id": k, "name": self._name("tape", k, v["name"])} for k, v in TAPES.items()],
            "ambience": [{"id": k, "name": self._name("ambience", k, v)} for k, v in AMBIENCE_KINDS.items()],
            "techniques": [{"id": k, "name": self._name("technique", k, v["name"]), "pattern": v["pattern"],
                            "spacing": v["spacing"], "angle_deg": v["angle_deg"]}
                           for k, v in ROOM_TECHNIQUES.items()],
            "stem_methods": [{"id": k, "name": self._name("stem_method", k, v),
                              "available": k != "demucs" or stems_mod.demucs_available()}
                             for k, v in methods.items()],
            "engines": [{"id": k, "name": self._name("engine", k, c.name),
                         "description": self._desc("engine", k, c.description), "local": c.local}
                        for k, c in ENGINES.items()],
            "formats": ["wav", "flac", "alac", "mp3"],
            "languages": LANGS,
            "deps": {"ffmpeg": have_ffmpeg(), "demucs": stems_mod.demucs_available()},
            "defaults": {"channel": asdict(Channel(name="", source="")),
                         "recording": asdict(Recording()),
                         "session": {k: v for k, v in asdict(Session()).items()
                                     if k not in ("channels", "recording")}},
        }

    # ── generators ───────────────────────────────────────────
    def m_engine_status(self, p, **_):
        eng = self._engine(p.get("engine", "demo"))
        ok, status = eng.is_available()
        return {"ok": bool(ok), "status": message(status, self.lang)}

    def m_engine_models(self, p, **_):
        eng = self._engine(p.get("engine", "demo"))
        models = [{**m, "name": message(str(m.get("name") or m.get("id") or ""), self.lang)} for m in eng.models()]
        model = p.get("model") or next((m["id"] for m in models if m.get("default")),
                                       models[0]["id"] if models else "")
        return {"models": models, "model": model, "schema": self._schema(eng, model)}

    def m_engine_schema(self, p, **_):
        eng = self._engine(p.get("engine", "demo"))
        return {"schema": self._schema(eng, p.get("model", ""))}

    def m_engine_price(self, p, **_):
        eng = self._engine(p.get("engine", "demo"))
        return {"price": eng.estimate_price(self._request(p.get("request") or {}))}

    def m_generate(self, p, progress=None, cancel=None):
        eng = self._engine(p.get("engine", "demo"))
        req = self._request(p.get("request") or {})
        if not p.get("out_dir") and not p.get("root"):
            raise ValueError("params.root (project folder) or params.out_dir is required")
        out_dir = Path(p.get("out_dir") or Path(p["root"]).expanduser() / "generated").expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        tracks = eng.generate(req, out_dir, progress=progress, cancel=cancel)
        return {"tracks": [track_entry(t) for t in tracks]}

    # ── project folder ───────────────────────────────────────
    def m_library_scan(self, p, **_):
        if not p.get("root"):
            raise ValueError("params.root is required")
        return scan(p["root"])

    # ── sessions ─────────────────────────────────────────────
    def m_session_open_track(self, p, progress=None, cancel=None):
        """Song → studio session. Reuses an existing session of the song (keeps user settings)."""
        path = Path(p["path"]).expanduser()
        root = Path(p.get("root") or path.parent).expanduser()
        method = p.get("method") or "auto"
        if method == "auto":
            method = "demucs" if stems_mod.demucs_available() else "hpss"
        side = path if path.suffix.lower() == ".json" else path.with_suffix(".json")
        meta, stems = {}, {}
        if side.exists() and not side.name.endswith(".studio.json"):
            t = GeneratedTrack.from_sidecar(side)
            path = Path(t.path)
            meta = {**t.meta, "title": t.title, "lyrics": t.lyrics, "engine": t.engine}
            if t.cover:
                meta["cover"] = str(t.cover)
            stems = {k: str(v) for k, v in t.stems.items() if v and Path(v).exists()}
        meta.setdefault("title", path.stem)
        meta["source"] = str(path)
        name = meta.get("title") or path.stem
        if stems and not p.get("force_split"):
            sp = Path(next(iter(stems.values()))).parent.parent / "session.studio.json"
            if sp.exists() and not p.get("fresh"):
                return {"session": Session.load(sp).to_dict(), "path": str(sp), "created": False}
            s = self._name_channels(session_from_stems(stems, name=name, scene=p.get("scene") or "studio_a", meta=meta))
            s.save(sp)
            return {"session": s.to_dict(), "path": str(sp), "created": True}
        safe = "".join(c if c.isalnum() or c in " -_()" else "_" for c in name).strip() or "song"
        sdir = root / "sessions" / safe
        if (sdir / "session.studio.json").exists():
            if not p.get("fresh"):
                sp = sdir / "session.studio.json"
                return {"session": Session.load(sp).to_dict(), "path": str(sp), "created": False}
            sdir = sdir.with_name(f"{safe} {time.strftime('%Y%m%d-%H%M%S')}")
        st = stems_mod.separate(path, sdir / "stems", method, progress=progress, cancel=cancel)
        s = session_from_stems({k: str(v) for k, v in st.items()}, name=name, scene=p.get("scene") or "studio_a",
                               meta=meta)
        self._name_channels(s)
        sp = sdir / "session.studio.json"
        s.save(sp)
        return {"session": s.to_dict(), "path": str(sp), "created": True, "method": method}

    def m_session_new(self, p, **_):
        default_name = "Новая сессия" if self.lang == "ru" else "New session"
        s = Session(name=p.get("name") or default_name, scene=p.get("scene") or "studio_a")
        for src in p.get("sources") or []:
            s.add_channel(src)
        return {"session": self._name_channels(s).to_dict()}

    def m_session_load(self, p, **_):
        sp = Path(p["path"]).expanduser()
        return {"session": Session.load(sp).to_dict(), "path": str(sp)}

    def m_session_save(self, p, **_):
        s = self._session(p)
        sp = Path(p["path"]).expanduser()
        if sp.suffix.lower() != ".json":
            sp = sp / "session.studio.json"
        s.save(sp)
        return {"path": str(sp)}

    def m_session_op(self, p, **_):
        s = self._session(p)
        op = p.get("op")
        a = p.get("args") or {}
        if op == "set_scene":
            s.set_scene(a["scene"], keep_layout=bool(a.get("keep_layout", True)))
        elif op == "set_room_size":
            s.set_room_size(a.get("width"), a.get("depth"), a.get("height"))
        elif op == "reset_layout":
            s.set_scene(s.scene, keep_layout=False)
        elif op == "apply_instrument":
            ch = s.channel(a["channel"])
            if ch is None:
                raise KeyError(f"no channel {a['channel']}")
            s.apply_instrument(ch, a["instrument"])
        elif op == "add_channel":
            ch = s.add_channel(a["source"], name=a.get("name"), instrument=a.get("instrument"))
            if not a.get("name"):
                self._name_channels(s, {ch.id})
        elif op == "localize_names":
            self._name_channels(s)
        elif op == "remove_channel":
            s.channels = [c for c in s.channels if c.id != a["channel"]]
        elif op == "duplicate_channel":
            ch = s.channel(a["channel"])
            if ch is None:
                raise KeyError(f"no channel {a['channel']}")
            d = asdict(ch)
            d.pop("id")
            d["name"] = f"{ch.name} 2"
            d["x"] = min(ch.x + 0.8, s.scene_preset.width - 0.3)
            s.channels.insert(s.channels.index(ch) + 1, Channel(**d))
        else:
            raise ValueError(f"unknown session op: {op}")
        return {"session": s.to_dict()}

    def m_session_describe(self, p, **_):
        s = self._session(p)
        sc = s.scene_preset
        lx, ly = s.listener()
        x0, y0, x1, y1 = sc.stage_rect()
        rec = s.recording
        return {
            "scene": self._scene_report(describe_scene(s)),
            "room": {"width": sc.width, "depth": sc.depth, "height": sc.height, "rt60": s.rt60,
                     "stage": [x0, y0, x1, y1], "ambience": sc.ambience, "ambience_db": sc.ambience_db,
                     "early_db": sc.early_db, "hf_ratio": sc.hf_ratio, "lf_ratio": sc.lf_ratio},
            "listener": [lx, ly],
            "ref_distance_m": ref_distance(s),
            "critical_distance_m": critical_distance(sc, s.rt60) if s.rt60 > 0 else None,
            "pair": [{"x": c["pos"][0], "y": c["pos"][1], "z": c["pos"][2], "pattern": c["pattern"],
                      "axis_deg": c["axis_deg"]}
                     for c in room_pair(lx, ly, rec.room_technique, rec.pair_spacing_m, rec.room_height_m)],
            "channels": {c.id: channel_geometry(s, c) for c in s.channels},
        }

    # ── render ───────────────────────────────────────────────
    def m_render_preview(self, p, progress=None, cancel=None):
        s = self._session(p)
        start = float(p.get("start_s") or 0.0)
        dur = float(p.get("duration_s") or 20.0)
        r = render_preview(s, start_s=start, duration_s=dur, progress=progress, cancel=cancel, meters=True)
        self.preview_dir.mkdir(parents=True, exist_ok=True)
        old = sorted(self.preview_dir.glob("preview-*.wav"), key=lambda q: q.stat().st_mtime)
        for q in old[:-6]:
            q.unlink(missing_ok=True)
        out = self.preview_dir / f"preview-{int(time.time() * 1000)}.wav"
        write_audio(out, r.audio, r.sr, bit_depth=32, fmt="wav")
        return {"path": str(out), "report": self._report(r.report)}

    def m_render_final(self, p, progress=None, cancel=None):
        s = self._session(p)
        sp = p.get("session_path")
        if sp:
            sdir = Path(sp).expanduser().parent
        else:
            sdir = Path(p.get("root") or ".").expanduser() / "sessions" / safe_name(s.name, "session")
        if p.get("out_path"):
            out = Path(p["out_path"]).expanduser()
            base = out.name
        else:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            scene_name = self._name("scene", s.scene, s.base_scene.name).split(" (")[0]
            base = f"{s.meta.get('title') or s.name} — {scene_name} {stamp}"
            base = "".join(c if c.isalnum() or c in " -_()—" else "_" for c in base)
            out = sdir / "renders" / base
        stems_dir = (out.parent / f"{base} — stems") if p.get("export_stems") else None
        start = float(p.get("start_s") or 0.0)
        dur = p.get("duration_s")
        r = render_session(s, start_s=start, duration_s=float(dur) if dur else None, out_path=out,
                           export_stems_dir=stems_dir, progress=progress, cancel=cancel)
        rep = self._report(r.report)
        rp = r.path.with_name(f"{base}.report.json")
        rp.write_text(json.dumps(rep, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
        return {"path": str(r.path), "report_path": str(rp), "report": rep,
                "stems_dir": str(stems_dir) if stems_dir else None}

    # ── analysis ─────────────────────────────────────────────
    def m_analyze(self, p, progress=None, cancel=None):
        """Waveform overview + loudness of a file (cached by path, mtime, points)."""
        path = Path(p["path"]).expanduser()
        points = int(min(max(int(p.get("points") or 1200), 50), 20000))
        loud = bool(p.get("loudness", True))
        key = (str(path.resolve()), path.stat().st_mtime, points, loud)
        with self._cache_lock:
            hit = self._analysis.get(key)
        if hit is not None:
            return hit
        audio, sr = read_audio(path)
        n = audio.shape[1]
        hop = max(1, int(np.ceil(n / points)))
        nb = int(np.ceil(n / hop)) if n else 0
        peaks = []
        rms = []
        for ch in audio[:2]:
            pad = np.pad(np.abs(ch), (0, nb * hop - n)).reshape(nb, hop) if nb else np.zeros((0, 1))
            peaks.append(np.round(pad.max(axis=1), 4).tolist())
            rms.append(np.round(np.sqrt(np.mean(np.square(pad), axis=1)), 4).tolist())
        res = {"path": str(path), "sr": sr, "channels": int(audio.shape[0]), "duration": n / sr if sr else 0.0,
               "points": nb, "hop_s": hop / sr if sr else 0.0, "peaks": peaks, "rms": rms}
        if loud and n:
            res["lufs"] = round(integrated_lufs(audio, sr), 2)
            res["true_peak_db"] = round(true_peak_db(audio), 2)
            res["peak_db"] = round(float(20 * np.log10(np.max(np.abs(audio)) + 1e-12)), 2)
        with self._cache_lock:
            while len(self._analysis) > 64:
                self._analysis.pop(next(iter(self._analysis)))
            self._analysis[key] = res
        return res

    def m_stems_separate(self, p, progress=None, cancel=None):
        st = stems_mod.separate(Path(p["path"]).expanduser(), Path(p["out_dir"]).expanduser(),
                                p.get("method") or "hpss", progress=progress, cancel=cancel)
        return {"stems": {k: str(v) for k, v in st.items()}}

    # ── main loop ────────────────────────────────────────────
    def serve(self, inp) -> None:
        self.send({"event": "ready", "version": __version__, "pid": os.getpid()})
        for raw in inp:
            try:
                line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            except UnicodeDecodeError:
                self.send({"id": None, "error": {"message": "input is not UTF-8", "type": "ProtocolError"}})
                continue
            self.handle_line(line)
            if not self.running:
                break
        with self.lock:
            for ev in self.jobs.values():
                ev.set()
        self.pool.shutdown(wait=True, cancel_futures=True)


def main() -> int:
    # Protocol goes to the original stdout; everything printed by libraries ends up in stderr.
    proto_fd = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    out = os.fdopen(proto_fd, "w", encoding="utf-8", buffering=1)
    Server(out).serve(sys.stdin.buffer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
